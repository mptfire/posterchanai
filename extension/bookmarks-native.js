/* `browser.bookmarks` FOR POSTERFOX ON ANDROID, served by the app itself.
 *
 * Firefox for Android implements no bookmarks WebExtension API at all (MDN browser-compat-data: every method
 * version_added:false), so bookmark sync could not run there. PosterFox for Android bundles this extension as a
 * BUILT-IN extension, and built-in extensions may talk to the app over native messaging. The app's Kotlin side
 * (PosterChanBookmarks in the posterfox-android repo) answers each call from Firefox's own bookmark storage — the
 * one the browser's Bookmarks screen shows.
 *
 * So the sync logic stays ONE implementation: bookmarks.js runs here exactly as on the desktop, against this object.
 * Only the Android build of the extension loads this file (build.sh `android`); on the desktop `browser.bookmarks`
 * exists and nothing here runs.
 *
 * EVENTS ARE DERIVED, because the app's storage reports no changes. After every change made through this object and
 * every POLL_MS, the whole tree is read and compared with the last copy: a new id is onCreated, a missing one
 * onRemoved, a new title/url onChanged, a new parent onMoved. The first read is the baseline and fires nothing — a
 * bookmark that already existed was not just created. A read that FAILS fires nothing either: "could not ask" is
 * never "everything was removed".
 *
 * Node shapes are the WebExtension ones (BookmarkTreeNode: id, parentId, index, title, url, dateAdded, type,
 * children), and ids are the storage's guids, so the Firefox root ids bookmarks.js already knows ('toolbar_____',
 * 'menu________', 'unfiled_____', 'mobile______') mean the same thing here.
 *
 * Worker-safe and DOM-free; tests/test_bookmarks_native.py drives it under node with a fake app.
 */
(function (root) {
  'use strict';

  var APP = 'posterfox_bookmarks';
  var ROOT = 'root________';
  var POLL_MS = 30000;

  function makeEvent() {
    var fns = [];
    return {
      addListener: function (f) { if (fns.indexOf(f) < 0) fns.push(f); },
      removeListener: function (f) { var i = fns.indexOf(f); if (i >= 0) fns.splice(i, 1); },
      hasListener: function (f) { return fns.indexOf(f) >= 0; },
      _fire: function () {
        var args = arguments;
        fns.slice().forEach(function (f) { try { f.apply(null, args); } catch (e) { try { console.warn(e); } catch (_) {} } });
      },
    };
  }

  /* The app's node -> a WebExtension BookmarkTreeNode. */
  function toNode(n) {
    if (!n) return null;
    var out = {
      id: n.guid,
      title: n.title || '',
      dateAdded: n.dateAdded || 0,
      type: n.type === 'folder' ? 'folder' : n.type === 'separator' ? 'separator' : 'bookmark',
    };
    if (n.parentGuid) out.parentId = n.parentGuid;
    if (n.position != null) out.index = n.position;
    if (out.type === 'bookmark') out.url = n.url || '';
    if (n.children) out.children = n.children.map(toNode);
    return out;
  }

  /* id -> {parentId, index, title, url, node} for every node under the root. */
  function flatten(tree) {
    var out = {};
    (function walk(n) {
      if (!n) return;
      out[n.id] = { parentId: n.parentId || null, index: n.index, title: n.title, url: n.url, node: n };
      (n.children || []).forEach(walk);
    })(tree);
    return out;
  }

  /* What changed between two flattened trees, as the four events' argument lists. Pure; tested directly. */
  function diff(before, after) {
    var ev = { created: [], removed: [], changed: [], moved: [] };
    Object.keys(after).forEach(function (id) {
      var a = after[id], b = before[id];
      if (!b) { ev.created.push([id, a.node]); return; }
      if ((a.title || '') !== (b.title || '') || (a.url || '') !== (b.url || ''))
        ev.changed.push([id, { title: a.title || '', url: a.url }]);
      if (a.parentId !== b.parentId)
        ev.moved.push([id, { parentId: a.parentId, index: a.index, oldParentId: b.parentId, oldIndex: b.index }]);
    });
    Object.keys(before).forEach(function (id) {
      if (after[id]) return;
      var b = before[id];
      ev.removed.push([id, { parentId: b.parentId, index: b.index, node: b.node }]);
    });
    return ev;
  }

  function create(runtime, opts) {
    opts = opts || {};
    var port = null, seq = 0, waiting = {};
    var last = null;                         // flattened tree from the last successful read; null = no baseline yet
    var events = { onCreated: makeEvent(), onRemoved: makeEvent(), onChanged: makeEvent(), onMoved: makeEvent() };

    function connect() {
      if (port) return port;
      port = runtime.connectNative(APP);
      port.onMessage.addListener(function (m) {
        var w = m && waiting[m.id]; if (!w) return;
        delete waiting[m.id];
        if (m.ok) w.resolve(m.result); else w.reject(new Error(String(m.error || 'bookmark storage refused')));
      });
      port.onDisconnect.addListener(function () {
        port = null;
        Object.keys(waiting).forEach(function (k) { waiting[k].reject(new Error('bookmark storage went away')); });
        waiting = {};
      });
      return port;
    }

    function call(op, args) {
      return new Promise(function (resolve, reject) {
        var id = ++seq;
        waiting[id] = { resolve: resolve, reject: reject };
        try { connect().postMessage({ id: id, op: op, args: args || {} }); }
        catch (e) { delete waiting[id]; reject(e); }
      });
    }

    async function readTree() { return toNode(await call('getTree', { guid: ROOT })); }

    /* Read, compare, fire. Serialised so two refreshes never interleave their baselines. */
    var chain = Promise.resolve();
    function refresh() {
      var run = chain.then(_refresh, _refresh);
      chain = run.catch(function () {});
      return run;
    }
    async function _refresh() {
      var now;
      try { now = flatten(await readTree()); } catch (_) { return false; }   // could not ask: fire nothing
      var before = last; last = now;
      if (!before) return true;                                          // the baseline fires nothing
      var d = diff(before, now);
      d.created.forEach(function (a) { events.onCreated._fire(a[0], a[1]); });
      d.changed.forEach(function (a) { events.onChanged._fire(a[0], a[1]); });
      d.moved.forEach(function (a) { events.onMoved._fire(a[0], a[1]); });
      d.removed.forEach(function (a) { events.onRemoved._fire(a[0], a[1]); });
      return true;
    }
    async function after(p) { var r = await p; await refresh(); return r; }

    async function one(id) {
      var n = toNode(await call('get', { guid: String(id) }));
      if (!n) throw new Error('Bookmark not found: ' + id);
      return n;
    }

    var api = {
      getTree: async function () { var t = await readTree(); return t ? [t] : []; },
      get: async function (ids) {
        var list = Array.isArray(ids) ? ids : [ids], out = [];
        for (var i = 0; i < list.length; i++) out.push(await one(list[i]));
        return out;
      },
      getChildren: async function (id) {
        var n = toNode(await call('getTree', { guid: String(id), recursive: false }));
        if (!n) throw new Error('Bookmark not found: ' + id);
        return (n.children || []).map(function (c) { var x = Object.assign({}, c); delete x.children; return x; });
      },
      search: async function (q) {
        var nodes = (q && typeof q === 'object' && q.url)
          ? await call('byUrl', { url: String(q.url) })
          : await call('search', { query: typeof q === 'string' ? q : String((q && (q.query || q.title)) || '') });
        return (nodes || []).map(toNode);
      },
      create: function (d) {
        d = d || {};
        var args = { parentGuid: d.parentId || 'unfiled_____', title: d.title || '', position: d.index };
        var p = (d.url ? call('addItem', Object.assign(args, { url: d.url })) : call('addFolder', args))
          .then(function (guid) { return one(guid); });
        return after(p);
      },
      update: function (id, ch) {
        ch = ch || {};
        return after(call('update', { guid: String(id), title: ch.title, url: ch.url }).then(function () { return one(id); }));
      },
      move: function (id, dest) {
        dest = dest || {};
        return after(call('update', { guid: String(id), parentGuid: dest.parentId, position: dest.index })
          .then(function () { return one(id); }));
      },
      remove: function (id) { return after(call('remove', { guid: String(id) }).then(function () {})); },
      removeTree: function (id) { return after(call('remove', { guid: String(id) }).then(function () {})); },
      onCreated: events.onCreated, onRemoved: events.onRemoved, onChanged: events.onChanged, onMoved: events.onMoved,
      _refresh: refresh,
    };

    refresh();                                                            // take the baseline
    var every = opts.pollMs === 0 ? 0 : (opts.pollMs || POLL_MS);
    if (every) setInterval(refresh, every);
    return api;
  }

  var exported = { create: create, diff: diff, flatten: flatten, toNode: toNode };
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  root.PCNativeBookmarks = exported;

  /* On a browser WITHOUT a bookmarks API that can reach the app (PosterFox for Android): background.js builds its
   * browser object from PC_BROWSER, so the stand-in is used wherever B.bookmarks is read. Everything else is the
   * real `browser`, untouched. */
  try {
    var real = (typeof browser !== 'undefined') ? browser : null;
    if (real && !real.bookmarks && real.runtime && typeof real.runtime.connectNative === 'function') {
      var bm = create(real.runtime);
      root.PC_BROWSER = new Proxy(real, { get: function (t, k) { return k === 'bookmarks' ? bm : t[k]; } });
    }
  } catch (_) {}
})(typeof self !== 'undefined' ? self : this);
