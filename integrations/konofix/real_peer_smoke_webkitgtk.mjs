import { installWebKitInspectorWebSocketCompat } from './webkit_inspector_websocket_compat.mjs';

// WEBKIT_INSPECTOR_HTTP_SERVER page sockets expose a Target.* control plane.
// Install the narrow compatibility wrapper so page-domain commands are routed
// through Target.sendMessageToTarget after Target.targetCreated arrives.
installWebKitInspectorWebSocketCompat();
await import('./real_peer_smoke_core.mjs');
