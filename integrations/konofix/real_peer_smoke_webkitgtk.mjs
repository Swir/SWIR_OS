// WEBKIT_INSPECTOR_HTTP_SERVER exposes per-WebPage WebSocket targets.
// They already speak the Web Inspector protocol directly; wrapping them in a
// Target.* multiplexer prevents Runtime.evaluate from reaching the page.
// Keep Node's native WebSocket and let real_peer_smoke_core.mjs talk directly
// to the discovered /socket/.../WebPage endpoint.
await import('./real_peer_smoke_core.mjs');
