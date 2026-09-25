"""Offline tests use synthetic bytes, never execute an installer or a chat peer."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

from prepare import Asset, PreparationError, ReleaseRedirects, load_asset, prepare, trusted_url, verify, main

PIN = Path(__file__).with_name("upstream.json")
DATA = b"Synthetic inert test data: not an executable."
REAL = load_asset()
ASSET = Asset(REAL.name, REAL.url, len(DATA), hashlib.sha256(DATA).hexdigest())


class Response(io.BytesIO):
    def __init__(self, data=DATA, *, url=ASSET.url, status=200, headers=None):
        super().__init__(data)
        self.url, self.status = url, status
        self.headers = {"Content-Length": str(len(data))} if headers is None else headers

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        assert request.full_url == ASSET.url
        assert request.get_method() == "GET"
        assert timeout == 30
        assert request.get_header("Accept-encoding") == "identity"
        assert request.get_header("Authorization") is None
        return self.response


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "stage"

    def assert_rejected(self, response):
        with self.assertRaises(PreparationError):
            prepare(ASSET, self.output, opener=Opener(response))
        self.assertEqual(list(self.output.iterdir()), [])

    def test_reviewed_production_pin(self):
        pin = json.loads(PIN.read_text())
        self.assertEqual(pin["sourceCommit"], "31298cc732c97ff90230c3743cd1c3be17f40b6c")
        self.assertEqual(REAL.size, 8448999)
        self.assertEqual(REAL.sha256, "9d0ae79d32d49272ec597cfaae19023a5d0a3a1c8dc23d622b987bb2bc250de6")
        self.assertIs(pin["automaticExecution"], False)
        self.assertIs(pin["linuxGuiQualified"], False)

    def test_prepare_and_idempotent_rerun(self):
        opener = Opener(Response())
        result = prepare(ASSET, self.output, opener=opener)
        self.assertEqual(result.read_bytes(), DATA)
        self.assertEqual(prepare(ASSET, self.output, opener=opener), result)
        self.assertEqual(opener.calls, 1)
        self.assertEqual(list(self.output.iterdir()), [result])

    def test_same_size_tampering(self):
        self.assert_rejected(Response(b"x" * len(DATA)))

    def test_short_stream(self):
        self.assert_rejected(Response(DATA[:-1], headers={}))

    def test_oversized_stream(self):
        self.assert_rejected(Response(DATA + b"x", headers={}))

    def test_incorrect_content_length(self):
        self.assert_rejected(Response(headers={"Content-Length": "10"}))

    def test_invalid_content_length(self):
        self.assert_rejected(Response(headers={"Content-Length": "not-a-number"}))

    def test_compressed_transfer(self):
        self.assert_rejected(Response(headers={"Content-Encoding": "gzip"}))

    def test_partial_response(self):
        self.assert_rejected(Response(status=206))

    def test_unexpected_final_host(self):
        self.assert_rejected(Response(url="https://example.org/fake.exe"))

    def test_existing_bad_file_is_not_overwritten(self):
        self.output.mkdir()
        target = self.output / ASSET.name
        target.write_bytes(b"preserve this")
        opener = Opener(Response())
        with self.assertRaises(PreparationError):
            prepare(ASSET, self.output, opener=opener)
        self.assertEqual(target.read_bytes(), b"preserve this")
        self.assertEqual(opener.calls, 0)

    def test_existing_directory_is_not_overwritten(self):
        (self.output / ASSET.name).mkdir(parents=True)
        with self.assertRaises(PreparationError):
            prepare(ASSET, self.output, opener=Opener(Response()))
        self.assertTrue((self.output / ASSET.name).is_dir())

    def test_symlink_is_rejected(self):
        self.output.mkdir()
        victim = self.root / "victim"
        victim.write_bytes(DATA)
        target = self.output / ASSET.name
        try:
            target.symlink_to(victim)
        except OSError:
            self.skipTest("Host does not permit unprivileged symlink creation")
        with self.assertRaises(PreparationError):
            verify(target, ASSET)
        self.assertEqual(victim.read_bytes(), DATA)

    def test_publication_race_preserves_existing_file(self):
        def collision(source, destination):
            destination.write_bytes(b"another publisher")
            raise FileExistsError("already exists")
        with patch("prepare.os.link", side_effect=collision), self.assertRaises(FileExistsError):
            prepare(ASSET, self.output, opener=Opener(Response()))
        self.assertEqual((self.output / ASSET.name).read_bytes(), b"another publisher")
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_network_failure_cleans_partial_file(self):
        opener = Opener(Response())
        with patch.object(opener, "open", side_effect=TimeoutError), self.assertRaises(TimeoutError):
            prepare(ASSET, self.output, opener=opener)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_time_budget(self):
        with patch("prepare.time.monotonic", side_effect=[0, 121]):
            self.assert_rejected(Response())

    def test_trusted_redirects_only(self):
        self.assertTrue(trusted_url(ASSET.url, ASSET.url))
        self.assertTrue(trusted_url("https://release-assets.githubusercontent.com/path?token=example", ASSET.url))
        for url in ("http://release-assets.githubusercontent.com/a", "https://github.com/Other/Repo/a",
                    "https://release-assets.githubusercontent.com.evil.test/a", "https://localhost/a",
                    "https://user:pass@release-assets.githubusercontent.com/a",
                    "https://release-assets.githubusercontent.com:444/a",
                    "https://release-assets.githubusercontent.com:invalid/a",
                    "https://release-assets.githubusercontent.com/a#fragment",
                    "https://release-assets.githubusercontent.com/a\n", "file:///etc/passwd"):
            with self.subTest(url=url):
                self.assertFalse(trusted_url(url, ASSET.url))

    def test_redirect_count_limit(self):
        handler = ReleaseRedirects(ASSET.url)
        request = urllib.request.Request(ASSET.url)
        for _ in range(3):
            self.assertIsNotNone(handler.redirect_request(request, None, 302, "Found", {},
                                                          "https://release-assets.githubusercontent.com/a"))
        with self.assertRaises(PreparationError):
            handler.redirect_request(request, None, 302, "Found", {},
                                     "https://release-assets.githubusercontent.com/a")

    def test_redirect_handler_rejects_other_host(self):
        with self.assertRaises(PreparationError):
            ReleaseRedirects(ASSET.url).redirect_request(urllib.request.Request(ASSET.url), None,
                                                       302, "Found", {}, "https://example.org/a")

    def test_cli_verify_does_not_claim_installation(self):
        existing = self.root / ASSET.name
        existing.write_bytes(DATA)
        output = io.StringIO()
        with patch("prepare.load_asset", return_value=ASSET), patch("sys.stdout", output):
            self.assertEqual(main(["--verify", str(existing)]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "verified-download-only")
        self.assertIs(result["installed"], False)
        self.assertIs(result["executed"], False)
        self.assertIs(result["linuxGuiQualified"], False)

    def test_asset_validation(self):
        for fields in (("../escape.exe", ASSET.url, ASSET.size, ASSET.sha256),
                       (ASSET.name, "https://example.org/fake.exe", ASSET.size, ASSET.sha256),
                       (ASSET.name, ASSET.url, True, ASSET.sha256),
                       (ASSET.name, ASSET.url, 0, ASSET.sha256),
                       (ASSET.name, ASSET.url, 300 * 1024 * 1024, ASSET.sha256),
                       (ASSET.name, ASSET.url, ASSET.size, "not-a-digest")):
            with self.subTest(fields=fields), self.assertRaises(PreparationError):
                Asset(*fields)

    def test_pin_rejects_unqualified_identity_or_policy(self):
        original = json.loads(PIN.read_text())
        for field, value in (("repository", "Other/Konofix"), ("sourceCommit", "abc123"),
                             ("platform", "linux"), ("url", "https://example.org/fake.exe"),
                             ("version", "latest"), ("automaticExecution", True),
                             ("automaticExecution", 0), ("linuxGuiQualified", True),
                             ("size", True), ("assetId", 0), ("releaseId", False),
                             ("sha256", int("1" * 64)), ("sourceCommit", int("1" * 40))):
            bad = self.root / "bad.json"
            bad.write_text(json.dumps({**original, field: value}))
            with self.subTest(field=field, value=value), self.assertRaises(PreparationError):
                load_asset(bad)


if __name__ == "__main__":
    unittest.main()
