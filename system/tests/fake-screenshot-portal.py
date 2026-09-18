#!/usr/bin/env python3
"""Controlled fake XDG Screenshot portal used only by SWIR Screenshot CI."""
from __future__ import annotations

import os
import pathlib
import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.Screenshot"
REQUEST_IFACE = "org.freedesktop.portal.Request"
XML = """
<node><interface name="org.freedesktop.portal.Screenshot">
  <method name="Screenshot">
    <arg direction="in" type="s" name="parent_window"/>
    <arg direction="in" type="a{sv}" name="options"/>
    <arg direction="out" type="o" name="handle"/>
  </method>
</interface></node>
"""


def main() -> int:
    source = pathlib.Path(os.environ["SWIR_SCREENSHOT_FAKE_SOURCE"]).resolve(strict=True)
    connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    node = Gio.DBusNodeInfo.new_for_xml(XML)
    counter = {"n": 0}

    def method_call(conn, _sender, _object, interface, method, params, invocation):
        if interface != IFACE or method != "Screenshot":
            invocation.return_dbus_error("org.freedesktop.portal.Error.NotFound", "unsupported method")
            return
        _parent, options = params.unpack()
        if not bool(options.get("interactive", False)):
            invocation.return_dbus_error("org.freedesktop.portal.Error.InvalidArgument", "interactive is required")
            return
        counter["n"] += 1
        token = str(options.get("handle_token", "swirtest"))
        handle = f"/org/freedesktop/portal/desktop/request/1_1/{token}_{counter['n']}"
        invocation.return_value(GLib.Variant("(o)", (handle,)))

        def respond():
            conn.emit_signal(None, handle, REQUEST_IFACE, "Response", GLib.Variant("(ua{sv})", (0, {"uri": GLib.Variant("s", source.as_uri())})))
            return False

        GLib.timeout_add(120, respond)

    registration = connection.register_object(PATH, node.interfaces[0], method_call, None, None)
    if not registration:
        raise RuntimeError("failed to register fake screenshot portal")
    owner = Gio.bus_own_name_on_connection(connection, BUS, Gio.BusNameOwnerFlags.NONE, None, None)
    if not owner:
        raise RuntimeError("failed to own fake screenshot portal bus name")
    print("fake screenshot portal ready", flush=True)
    GLib.MainLoop().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
