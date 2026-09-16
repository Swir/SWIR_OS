import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const corePath = path.join(root, 'swir-media-core.js');
const playerPath = path.join(root, 'swir-player.html');
const workerPath = path.join(root, 'sw.js');
const appsPath = path.join(root, 'swir-apps.js');
const coreSource = fs.readFileSync(corePath, 'utf8');
const player = fs.readFileSync(playerPath, 'utf8');
const worker = fs.readFileSync(workerPath, 'utf8');
const apps = fs.readFileSync(appsPath, 'utf8');

function expect(condition, message) {
  if (!condition) throw new Error(message);
  console.log(`PASS ${message}`);
}
function requireText(source, needle, message) {
  expect(source.includes(needle), message);
}
function expectThrows(action, message) {
  try { action(); } catch { console.log(`PASS ${message}`); return; }
  throw new Error(`Expected rejection: ${message}`);
}

const window = {};
vm.runInContext(coreSource, vm.createContext({ window, Object, Array, Set, String, Number, Math, TypeError, RangeError, console }), { filename:'swir-media-core.js' });
const core = window.SwirMediaCore;
expect(core?.schema === 'swir.media-core/1.0', 'Media Core schema is exposed');
expect(core.repeatModes.join(',') === 'off,all,one', 'repeat contract is stable');

const a = { id:'a', title:'A', artist:'Artist A', src:'blob:a', kind:'local' };
const b = { id:'b', title:'B', artist:'Artist B', src:'blob:b', kind:'local' };
const c = { id:'c', title:'C', artist:'Artist C', src:'blob:c', kind:'local' };
const queue = core.createQueue({ tracks:[a,b,c] });
expect(queue.snapshot().count === 3 && queue.current().id === 'a', 'queue initializes with first track selected');
queue.select('b');
expect(queue.current().id === 'b', 'queue selects by stable track id');
queue.move(1, 2);
expect(queue.current().id === 'b' && queue.snapshot().tracks.map(t=>t.id).join(',') === 'a,c,b', 'reorder preserves current identity');
queue.setRepeat('all');
queue.select('b');
expect(queue.next({automatic:true}).id === 'a', 'repeat-all wraps automatic playback');
queue.setRepeat('one');
queue.select('c');
expect(queue.next({automatic:true}).id === 'c', 'repeat-one retains the current track on automatic advance');
queue.setRepeat('off');
queue.select('b');
expect(queue.next({automatic:true}) === null, 'repeat-off stops at the end of the queue');
queue.select('a');
expect(queue.previous().id === 'b', 'manual previous wraps to the end');
const removed = queue.remove('b');
expect(removed.id === 'b' && !queue.snapshot().tracks.some(track=>track.id==='b'), 'remove returns and deletes the selected track');
expectThrows(() => queue.add(a), 'duplicate track ids are rejected');
expectThrows(() => core.normalizeTrack({id:'bad id',src:'blob:x'}), 'unsafe track ids are rejected');
expectThrows(() => queue.setRepeat('forever'), 'unsupported repeat modes are rejected');

const shuffleQueue = core.createQueue({ tracks:[a,b,c], random:()=>0.99, shuffle:true });
shuffleQueue.select('a');
expect(shuffleQueue.next({automatic:true}).id === 'c', 'shuffle uses an injected/randomized next selection and avoids the current track');
let events = 0;
const stop = shuffleQueue.subscribe(()=>events++);
shuffleQueue.toggleShuffle();
stop();
expect(events === 1, 'queue state changes notify subscribers');

requireText(player, '<title>SWIR Player 2.0</title>', 'Player identifies the 2.0 experience');
requireText(player, './swir-media-core.js?v=1.0.0', 'Player loads the portable Media Core');
requireText(player, "'mediaSession'in navigator", 'Player integrates the browser Media Session bridge');
requireText(player, 'navigator.mediaSession.setActionHandler', 'Player exposes media-key actions');
requireText(player, "addEventListener('keydown'", 'Player provides keyboard media controls');
requireText(player, 'URL.createObjectURL(file)', 'Local files use session-scoped object URLs');
requireText(player, 'URL.revokeObjectURL', 'Local object URLs are explicitly revoked');
requireText(player, "file.type.startsWith('audio/')", 'Player filters local drops to audio media');
requireText(player, 'NOTHING UPLOADED', 'Player communicates the local-only privacy model');
requireText(player, "queue.next({automatic})", 'Playback completion delegates repeat/shuffle behavior to Media Core');
requireText(player, 'queue.cycleRepeat()', 'Repeat control uses Media Core state');
requireText(player, 'queue.toggleShuffle()', 'Shuffle control uses Media Core state');
requireText(apps, 'id:"player"', 'SWIR Player remains in the system application registry');
requireText(worker, "'./swir-media-core.js'", 'Media Core is precached for offline use');
requireText(worker, "'./swir-player.html'", 'SWIR Player remains precached for offline use');
requireText(worker, 'media-core-1.0.0', 'Service Worker cache invalidates for Media Core 1.0');

const inlineScripts = [...player.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map(match=>match[1]).filter(Boolean);
expect(inlineScripts.length === 1, 'Player has one reviewed inline controller script');
for (const [index, script] of inlineScripts.entries()) {
  try { new Function(script); }
  catch (error) { throw new Error(`Player inline script ${index + 1} failed JavaScript parse validation: ${error.message}`); }
}

console.log('SWIR Player 2.0 contract validated: portable queue core, repeat/shuffle, local-only files, Media Session, cleanup and offline integration.');
