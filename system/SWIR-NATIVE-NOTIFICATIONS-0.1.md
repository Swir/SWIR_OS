# SWIR Native Notification Service 0.1

SWIR System Edition now owns a first-party native notification endpoint inside the authenticated GTK4 shell. The implementation serves the standard `org.freedesktop.Notifications` D-Bus interface, displays plain-text toasts in the SWIR shell, exposes a bounded Notification Center history, and keeps all notification handling in the signed-in user's session.

## Verified interface

The shell implements:

- `GetCapabilities`
- `Notify`
- `CloseNotification`
- `GetServerInformation`
- `NotificationClosed`
- `ActionInvoked`

Capabilities are deliberately limited to `actions`, `body`, and `persistence`. SWIR does **not** advertise body markup, arbitrary image loading, static icons, sound, privileged helpers, or shell-command actions in this milestone.

## Safety boundary

Notification input is untrusted application data. The shell therefore:

- renders summary/body using GTK plain-text labels rather than markup;
- strips control characters and enforces bounded app-name, summary, body, and action sizes;
- accepts at most six action pairs and emits only the standard action signal back to the originating session bus;
- ignores application icon paths and image hints instead of reading arbitrary files;
- performs no `sudo`, `pkexec`, package mutation, root helper, network fetch, or command execution on notification contents;
- clamps finite expiration requests to a verified maximum of 60 seconds while retaining the standard persistent (`0`) mode;
- keeps active notifications in memory and persists only inert history records, never executable action callbacks.

The service is intentionally same-session. It does not claim cross-user delivery or a privileged system-bus notification broker.

## Persistent history

History uses `swir.notification-history/0.1` under `${XDG_STATE_HOME:-~/.local/state}/swir/notifications/history.json`.

The store is:

- bounded to 200 records and 2 MiB on read;
- written atomically through an owner-only temporary file;
- forced to mode `0600`, with an owner-only state directory;
- rejected when the managed path resolves through a symbolic link;
- limited to inert fields (`id`, application name, summary, body, timestamp).

The Notification Center shows at most the 20 newest records at once while retaining the bounded history on disk. Clearing history rewrites the same owner-only store.

## Shell integration

The native SWIR shell owns `org.freedesktop.Notifications` on the user session bus. Existing native applications using standard Gio notifications can therefore publish without a browser runtime. Toasts, action buttons, dismissal and history are rendered inside the already-authenticated shell window, avoiding a second privileged daemon or an external web surface.

If the session bus is unavailable, the shell itself remains usable and records the notification service as unavailable; it does not fall back to an unsafe helper.

## Verification

`.github/workflows/system-native-notifications.yml` provides three gates:

1. static policy/self-tests for sanitization, history bounds, owner-only persistence and the advertised capability set;
2. a real GTK4 shell on headless Weston/Wayland inside `dbus-run-session`, followed by an actual standard D-Bus `Notify` request, persisted-history inspection, capability checks and `CloseNotification`;
3. the Debian 13 (`trixie`) GTK4/Gio target runtime.

The runtime gate intentionally sends markup-looking text, a control character and a fake image path. Evidence must prove literal/plain rendering, ignored image hints, bounded history, an owned notification bus name, no privileged operation and no shell execution.

## Roadmap accounting

This materially advances the System Edition integration requirement for native notifications and the broader `essential native Linux application suite for dependable daily use`. It does **not** close that broad suite item on its own and does not change the canonical roadmap percentage in this milestone.
