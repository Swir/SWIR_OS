import { installWebKitInspectorWebSocketCompat } from './webkit_inspector_websocket_compat.mjs';

// WEBKIT_INSPECTOR_HTTP_SERVER exposes WebKit's outer Target control plane.
// Install the narrow compatibility adapter before loading the shared peer smoke
// so Runtime.* commands are wrapped in Target.sendMessageToTarget and replies
// are unwrapped from Target.dispatchMessageFromTarget.
const restore = installWebKitInspectorWebSocketCompat();
try {
  await import('./real_peer_smoke_core.mjs');
} finally {
  restore();
}
