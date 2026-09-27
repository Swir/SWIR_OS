// WEBKIT_INSPECTOR_HTTP_SERVER exposes per-page inspector WebSockets in the
// discovery HTML. real_peer_smoke_core.mjs already discovers those exact page
// sockets and speaks the Runtime domain directly when KONOFIX_INSPECTOR is
// webkitgtk. Do not wrap them in Chromium-style Target.* multiplexing: that
// outer control-plane handshake can swallow direct Runtime replies and caused
// the two-peer Linux qualification to time out while both native clients were
// otherwise alive.
await import('./real_peer_smoke_core.mjs');
