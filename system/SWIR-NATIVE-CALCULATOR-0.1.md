# SWIR Native Calculator 0.1

## Scope

SWIR Calculator is a first-party, unprivileged GTK4 utility for System Edition. It provides dependable local arithmetic without a browser runtime, network access, shell execution or privileged operations.

## Safe expression engine

Calculator expressions are parsed with Python `ast.parse(..., mode="eval")` and evaluated through an explicit node/operator allowlist. The application does **not** call Python `eval`/`exec` and rejects function calls, names, attributes, collections and every other non-arithmetic syntax class.

Supported operators:

```text
+  -  *  /  %  **
unary + / -
parentheses
```

Safety bounds are part of the runtime contract:

- maximum expression length: 256 characters;
- maximum AST node count: 64;
- exponent magnitude: 12;
- finite result magnitude: at most `1e100`;
- division/modulo by zero fails closed;
- in-memory history is bounded to 20 entries.

The UI exposes direct keypad entry, keyboard/Enter calculation, sign toggle, square helper, bounded history and clipboard copy of the displayed result.

## System integration

`system/session/provision-graphical-session.sh` installs the app from the trusted repository source into `/usr/local/bin/swir-calculator`. `swir-shell.py` exposes only that fixed launcher path. No user-controlled command is interpolated into a shell.

## Verification

`.github/workflows/system-native-calculator.yml` verifies:

1. Python compilation and self-tests for accepted/rejected expressions;
2. absence of shell/privilege escape patterns;
3. native GTK4 mapping on a headless Wayland compositor with runtime evidence;
4. the exact Debian 13 GTK4 target runtime;
5. shell and System Edition provisioning integration.

This closes a real missing application in the Product Baseline, but it does **not** by itself complete the broader `essential native Linux application suite for dependable daily use` roadmap checkbox.
