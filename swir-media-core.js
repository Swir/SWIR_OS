/* SWIR Media Core 1.0 — edition-neutral queue/state contract for SWIR Player */
(() => {
  'use strict';

  const REPEAT = Object.freeze(['off', 'all', 'one']);

  function cleanText(value, fallback = '') {
    const text = String(value ?? '').trim();
    return (text || fallback).slice(0, 240);
  }

  function normalizeTrack(track) {
    if (!track || typeof track !== 'object' || Array.isArray(track)) throw new TypeError('Track must be an object.');
    const id = cleanText(track.id);
    const src = cleanText(track.src);
    if (!/^[A-Za-z0-9._:-]{1,128}$/.test(id)) throw new TypeError('Track id is invalid.');
    if (!src || src.length > 4096) throw new TypeError('Track source is invalid.');
    return Object.freeze({
      id,
      title: cleanText(track.title, 'Untitled'),
      artist: cleanText(track.artist, 'Local audio'),
      album: cleanText(track.album),
      src,
      mime: cleanText(track.mime),
      kind: cleanText(track.kind, 'local'),
      size: Number.isFinite(Number(track.size)) && Number(track.size) >= 0 ? Number(track.size) : 0,
      duration: Number.isFinite(Number(track.duration)) && Number(track.duration) >= 0 ? Number(track.duration) : null
    });
  }

  class MediaQueue {
    #tracks = [];
    #index = -1;
    #repeat = 'off';
    #shuffle = false;
    #listeners = new Set();
    #random;

    constructor(options = {}) {
      this.#random = typeof options.random === 'function' ? options.random : Math.random;
      if (options.repeat && REPEAT.includes(options.repeat)) this.#repeat = options.repeat;
      this.#shuffle = options.shuffle === true;
      if (Array.isArray(options.tracks)) this.addMany(options.tracks);
      if (this.#tracks.length && Number.isInteger(options.index)) this.select(options.index);
    }

    subscribe(listener) {
      if (typeof listener !== 'function') throw new TypeError('Listener must be a function.');
      this.#listeners.add(listener);
      return () => this.#listeners.delete(listener);
    }

    #emit(reason) {
      const state = this.snapshot();
      for (const listener of this.#listeners) {
        try { listener(state, reason); } catch {}
      }
      return state;
    }

    snapshot() {
      return Object.freeze({
        schema: 'swir.media-queue/1.0',
        tracks: Object.freeze(this.#tracks.slice()),
        count: this.#tracks.length,
        index: this.#index,
        current: this.current(),
        repeat: this.#repeat,
        shuffle: this.#shuffle
      });
    }

    current() {
      return this.#index >= 0 && this.#index < this.#tracks.length ? this.#tracks[this.#index] : null;
    }

    add(track) {
      const normalized = normalizeTrack(track);
      if (this.#tracks.some(item => item.id === normalized.id)) throw new TypeError(`Duplicate track id: ${normalized.id}`);
      this.#tracks.push(normalized);
      if (this.#index < 0) this.#index = 0;
      this.#emit('add');
      return normalized;
    }

    addMany(tracks) {
      if (!Array.isArray(tracks)) throw new TypeError('Track list must be an array.');
      const normalized = tracks.map(normalizeTrack);
      const seen = new Set(this.#tracks.map(item => item.id));
      for (const track of normalized) {
        if (seen.has(track.id)) throw new TypeError(`Duplicate track id: ${track.id}`);
        seen.add(track.id);
      }
      if (!normalized.length) return this.snapshot();
      this.#tracks.push(...normalized);
      if (this.#index < 0) this.#index = 0;
      return this.#emit('add-many');
    }

    select(indexOrId) {
      let index = Number.isInteger(indexOrId) ? indexOrId : this.#tracks.findIndex(track => track.id === String(indexOrId));
      if (index < 0 || index >= this.#tracks.length) throw new RangeError('Track selection is outside the queue.');
      this.#index = index;
      this.#emit('select');
      return this.current();
    }

    remove(indexOrId) {
      let index = Number.isInteger(indexOrId) ? indexOrId : this.#tracks.findIndex(track => track.id === String(indexOrId));
      if (index < 0 || index >= this.#tracks.length) return null;
      const [removed] = this.#tracks.splice(index, 1);
      if (!this.#tracks.length) this.#index = -1;
      else if (index < this.#index) this.#index--;
      else if (index === this.#index) this.#index = Math.min(this.#index, this.#tracks.length - 1);
      this.#emit('remove');
      return removed;
    }

    move(from, to) {
      if (!Number.isInteger(from) || !Number.isInteger(to) || from < 0 || to < 0 || from >= this.#tracks.length || to >= this.#tracks.length) throw new RangeError('Queue move is outside the track list.');
      if (from === to) return this.snapshot();
      const current = this.current();
      const [item] = this.#tracks.splice(from, 1);
      this.#tracks.splice(to, 0, item);
      this.#index = current ? this.#tracks.findIndex(track => track.id === current.id) : -1;
      return this.#emit('move');
    }

    clear() {
      this.#tracks = [];
      this.#index = -1;
      return this.#emit('clear');
    }

    setRepeat(mode) {
      const value = String(mode || '').toLowerCase();
      if (!REPEAT.includes(value)) throw new TypeError('Repeat mode must be off, all or one.');
      this.#repeat = value;
      return this.#emit('repeat');
    }

    cycleRepeat() {
      const next = REPEAT[(REPEAT.indexOf(this.#repeat) + 1) % REPEAT.length];
      return this.setRepeat(next);
    }

    setShuffle(enabled) {
      this.#shuffle = enabled === true;
      return this.#emit('shuffle');
    }

    toggleShuffle() {
      return this.setShuffle(!this.#shuffle);
    }

    next(options = {}) {
      if (!this.#tracks.length) return null;
      const automatic = options.automatic === true;
      if (automatic && this.#repeat === 'one') return this.current();
      if (this.#tracks.length === 1) {
        if (this.#repeat === 'all' || this.#repeat === 'one') return this.current();
        return automatic ? null : this.current();
      }
      if (this.#shuffle) {
        let candidate = this.#index;
        for (let attempt = 0; attempt < 8 && candidate === this.#index; attempt++) candidate = Math.floor(this.#random() * this.#tracks.length);
        if (candidate === this.#index) candidate = (this.#index + 1) % this.#tracks.length;
        this.#index = candidate;
        this.#emit('next');
        return this.current();
      }
      if (this.#index < this.#tracks.length - 1) this.#index++;
      else if (this.#repeat === 'all' || !automatic) this.#index = 0;
      else return null;
      this.#emit('next');
      return this.current();
    }

    previous() {
      if (!this.#tracks.length) return null;
      if (this.#tracks.length === 1) return this.current();
      if (this.#shuffle) return this.next({ automatic:false });
      this.#index = this.#index > 0 ? this.#index - 1 : this.#tracks.length - 1;
      this.#emit('previous');
      return this.current();
    }
  }

  window.SwirMediaCore = Object.freeze({
    schema: 'swir.media-core/1.0',
    repeatModes: REPEAT,
    normalizeTrack,
    createQueue: options => new MediaQueue(options),
    MediaQueue
  });
})();