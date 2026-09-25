import { installWebKitInspectorWebSocketCompat } from './webkit_inspector_websocket_compat.mjs';

installWebKitInspectorWebSocketCompat();
await import('./real_peer_smoke_core.mjs');
