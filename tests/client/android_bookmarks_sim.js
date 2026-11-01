/* PosterFox for Android and a desktop Firefox, one relay — bookmark sync through the app's own storage.
 *
 * Firefox for Android has no bookmarks WebExtension API, so PosterFox for Android serves one from the app over native
 * messaging (extension/bookmarks-native.js on the extension side, PosterChanBookmarks.kt in the posterfox-android repo
 * on the app side). The engine itself is the desktop's bookmarks.js, unchanged. This runs the SHIPPED
 * bookmarks-native.js + bookmarks.js in one vm context (the Android browser) against FakeApp below, and the desktop
 * model of two_browser_sim.js in another, on the shared relay and clock of that simulation.
 *
 * FakeApp IS THE PROTOCOL. It answers exactly the messages the Kotlin bridge must answer — {id, op, args} in,
 * {id, ok, result | error} out — with the storage semantics of Firefox's places database: a `root________` root
 * holding menu/toolbar/unfiled/mobile, guid ids, a folder deleted with everything in it, and bookmarks the user adds
 * in the app filed under `mobile______` as Fenix does. The app's own bookmark screen edits the storage directly
 * (`app.userAdd` / `app.userDelete`), which the extension can only learn by reading the tree again — the poll.
 *
 * Usage: node android_bookmarks_sim.js → JSON list of {name, ok, detail}; non-zero exit on failure.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const S = require('./two_browser_sim.js');

const NATIVE = fs.readFileSync(path.join(__dirname, '..', '..', 'extension', 'bookmarks-native.js'), 'utf8');
const ROOTS = { menu________: 'menu', toolbar_____: 'toolbar', unfiled_____: 'unfiled', mobile______: 'mobile' };

/* Firefox for Android's bookmark storage, behind the native-messaging protocol. */
function makeApp(opts) {
  opts = opts || {};
  const nodes = { root________: { guid: 'root________', parentGuid: null, title: '', type: 'folder', children: [] } };
  for (const [g, t] of Object.entries(ROOTS)) {
    nodes[g] = { guid: g, parentGuid: 'root________', title: t, type: 'folder', children: [] };
    nodes.root________.children.push(g);
  }
  let seq = 0, writes = 0, failReads = false, disconnects = [];
  let listening = opts.listening !== false, pending = [], dropped = 0;
  const add = (parentGuid, title, url, type) => {
    if (!nodes[parentGuid] || nodes[parentGuid].type !== 'folder') throw new Error('no such folder ' + parentGuid);
    const guid = ('g' + (++seq)).padEnd(12, '_');
    nodes[guid] = { guid, parentGuid, title: title || '', url, type, dateAdded: S.CLOCK.t * 1000, children: [] };
    nodes[parentGuid].children.push(guid); writes++;
    return guid;
  };
  const del = (guid) => {
    const n = nodes[guid]; if (!n || ROOTS[guid] || guid === 'root________') return false;
    const kill = (g) => { for (const c of (nodes[g].children || []).slice()) kill(c); delete nodes[g]; };
    nodes[n.parentGuid].children = nodes[n.parentGuid].children.filter(c => c !== guid);
    kill(guid); writes++;
    return true;
  };
  const view = (guid, depth) => {
    const n = nodes[guid]; if (!n) return null;
    const p = n.parentGuid ? nodes[n.parentGuid].children.indexOf(guid) : null;
    const out = { guid, parentGuid: n.parentGuid, position: p, title: n.title, url: n.url || null,
                  type: n.type === 'folder' ? 'folder' : 'item', dateAdded: n.dateAdded || 0 };
    if (n.type === 'folder') out.children = depth === 0 ? null : n.children.map(c => view(c, depth - 1));
    return out;
  };
  const ops = {
    getTree: (a) => { if (failReads) throw new Error('storage busy'); return view(a.guid, a.recursive === false ? 1 : 1e9); },
    get: (a) => { const v = view(a.guid, 0); if (v) delete v.children; return v; },
    byUrl: (a) => Object.values(nodes).filter(n => n.url === a.url).map(n => ops.get({ guid: n.guid })),
    search: (a) => Object.values(nodes).filter(n => n.url && ((n.title || '').includes(a.query) || n.url.includes(a.query)))
      .map(n => ops.get({ guid: n.guid })),
    addItem: (a) => add(a.parentGuid, a.title, a.url, 'item'),
    addFolder: (a) => add(a.parentGuid, a.title, undefined, 'folder'),
    update: (a) => {
      const n = nodes[a.guid]; if (!n) throw new Error('no such bookmark ' + a.guid);
      if (a.title != null) n.title = a.title;
      if (a.url != null && n.type !== 'folder') n.url = a.url;
      if (a.parentGuid && a.parentGuid !== n.parentGuid) {
        nodes[n.parentGuid].children = nodes[n.parentGuid].children.filter(c => c !== a.guid);
        n.parentGuid = a.parentGuid; nodes[a.parentGuid].children.push(a.guid);
      }
      writes++; return null;
    },
    remove: (a) => del(a.guid),
  };
  return {
    nodes,
    writes: () => writes,
    set failReads(v) { failReads = v; },
    urls: () => Object.values(nodes).filter(n => n.url).map(n => n.url).sort(),
    inRoot(url) {               // the top-level container a bookmark sits under, by its root guid
      let n = Object.values(nodes).find(x => x.url === url);
      while (n && n.parentGuid && n.parentGuid !== 'root________') n = nodes[n.parentGuid];
      return n && n.guid;
    },
    folderOf(url) { const n = Object.values(nodes).find(x => x.url === url); return n && nodes[n.parentGuid].title; },
    userAdd(url, title) { return add('mobile______', title || url, url, 'item'); },     // Fenix files new bookmarks here
    userDelete(url) { const n = Object.values(nodes).find(x => x.url === url); return n && del(n.guid); },
    /* The app registering its listener, which it does only once the built-in extension has installed. */
    listen() {
      listening = true;
      const held = pending; pending = [];
      held.forEach(c => c());
    },
    /* runtime.connectNative as GeckoView gives a built-in extension. A connection made before the app listens is HELD
     * and handed to the app when it does; a message posted on the port before then is DROPPED (GeckoView's port has
     * no listener yet). On connect the app says hello (PosterChanBookmarks.onPortConnected). */
    runtime: {
      connectNative(name) {
        if (name !== 'posterfox_bookmarks') throw new Error('unknown native app ' + name);
        const onMsg = [], onDis = [];
        let connected = false;
        disconnects.push(onDis);
        const deliver = (m) => onMsg.forEach(f => f(JSON.parse(JSON.stringify(m))));
        const connect = () => { connected = true; setTimeout(() => deliver({ hello: true }), 0); };
        if (listening) connect(); else pending.push(connect);
        return {
          onMessage: { addListener: (f) => onMsg.push(f) },
          onDisconnect: { addListener: (f) => onDis.push(f) },
          disconnect() { connected = false; },
          postMessage(m) {
            if (!connected) { dropped++; return; }
            setTimeout(() => {
              let reply;
              try { reply = { id: m.id, ok: true, result: ops[m.op](m.args || {}) }; }
              catch (e) { reply = { id: m.id, ok: false, error: String(e.message || e) }; }
              deliver(reply);
            }, 0);
          },
        };
      },
    },
    dropped: () => dropped,
  };
}

/* PosterFox for Android: the shipped bookmarks-native.js then bookmarks.js, in their own context, with a `browser`
 * that has NO bookmarks API — exactly what Firefox for Android hands an extension. */
function makeAndroid(relay, app) {
  const store = {};
  const browser = {
    runtime: app.runtime,
    storage: { local: {
      get: async (keys) => { const out = {}; for (const k of [].concat(keys)) if (k in store) out[k] = store[k]; return out; },
      set: async (o) => { Object.assign(store, o); },
    } },
  };
  const ctx = vm.createContext({ crypto: require('crypto').webcrypto, setTimeout, clearTimeout, console,
                                 TextEncoder, TextDecoder, Date: S.FakeDate, Proxy,
                                 setInterval: () => 0,          // the poll is driven by hand: poll()
                                 browser });
  ctx.self = ctx;
  vm.runInContext(NATIVE, ctx);
  vm.runInContext(S.SRC, ctx);
  const B = ctx.PC_BROWSER;
  const engine = ctx.PCBookmarks.engine;
  return {
    B, engine, app,
    async init() {
      await engine.init({ B, open: async (ct) => JSON.parse(ct), publish: async (id, item) => relay.publish(id, item),
                          isFull: () => true, why: () => '' });
      await engine.setEnabled(true);
    },
    async pull() { for (const [id, ev] of relay.all()) await engine.absorb(id, ev); },
    async merge(o) { return engine.union(o); },
    async poll() { return B && B.bookmarks._refresh(); },     // what the 30 s timer does
  };
}

const DESKTOP_ROOTS = S.FIREFOX_ROOTS.concat([['mobile______', 'Mobile Bookmarks']]);   // desktop Firefox has it too
const drain = () => new Promise(r => setTimeout(r, 700));
async function settle(d, a) {
  for (let i = 0; i < 2; i++) {
    await a.poll();
    await d.pull(); await d.merge();
    await a.pull(); await a.merge();
    await drain(); await a.poll(); await drain();
  }
}

/* A change made in the app's own UI travels WITHOUT a merge: the poll reads the tree, the derived event reaches
 * bookmarks.js, which publishes; the desktop only absorbs. A merge would rediscover the change from the tree and hide
 * a stand-in that never fires its events -- so the live checks below never merge. */
async function live(d, a) { await a.poll(); await drain(); await d.pull(); await drain(); }

const results = [];
function check(name, ok, detail) { results.push({ name, ok: !!ok, detail }); if (!ok) process.exitCode = 1; }

(async () => {
  // ---- 0. The stand-in is what bookmarks.js gets, and only where there is no bookmarks API ---------------------
  {
    const relay = S.makeRelay(), app = makeApp();
    const a = makeAndroid(relay, app);
    const withApi = vm.createContext({ Proxy, setInterval: () => 0, setTimeout,
      browser: { bookmarks: { real: true }, runtime: app.runtime } });
    withApi.self = withApi; vm.runInContext(NATIVE, withApi);
    check('Android gets a bookmarks API from the app; a browser with its own keeps it',
      !!(a.B && a.B.bookmarks && typeof a.B.bookmarks.getTree === 'function' && a.B.storage)
        && withApi.PC_BROWSER === undefined,
      { android: !!a.B, desktopOverridden: withApi.PC_BROWSER !== undefined });
  }

  // ---- 1. A desktop toolbar folder arrives on the phone, on the toolbar, in its folder -------------------------
  {
    const relay = S.makeRelay(), app = makeApp();
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS), a = makeAndroid(relay, app);
    const work = d.mk('toolbar_____', 'Work', undefined);
    d.mk(work.id, 'Docs', 'https://docs.example/');
    d.mk('menu________', 'News', 'https://news.example/');
    await d.init(); await a.init();
    await settle(d, a);
    check('desktop bookmarks reach the phone in the right container and folder',
      app.urls().join() === 'https://docs.example/,https://news.example/'
        && app.inRoot('https://docs.example/') === 'toolbar_____' && app.folderOf('https://docs.example/') === 'Work'
        && app.inRoot('https://news.example/') === 'menu________',
      { phone: app.urls(), docs: [app.inRoot('https://docs.example/'), app.folderOf('https://docs.example/')] });
  }

  // ---- 2. Bookmarked in the app's own UI -> the desktop gets it -------------------------------------------------
  {
    const relay = S.makeRelay(), app = makeApp();
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS), a = makeAndroid(relay, app);
    await d.init(); await a.init(); await settle(d, a);
    app.userAdd('https://phone.example/', 'From the phone');
    await live(d, a);
    check('a bookmark made on the phone reaches the desktop', d.urls().includes('https://phone.example/'),
      { desktop: d.urls() });
  }

  // ---- 3. Deleted in the app's UI -> deleted on the desktop; deleted on the desktop -> deleted on the phone ----
  {
    const relay = S.makeRelay(), app = makeApp();
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS), a = makeAndroid(relay, app);
    d.mk('toolbar_____', 'Keep', 'https://keep.example/');
    d.mk('toolbar_____', 'Gone from phone', 'https://p-del.example/');
    d.mk('toolbar_____', 'Gone from desktop', 'https://d-del.example/');
    await d.init(); await a.init(); await settle(d, a);
    const synced = app.urls().length;
    app.userDelete('https://p-del.example/');
    await live(d, a);
    await d.ripLive('https://d-del.example/');
    await drain();
    await a.pull(); await drain(); await a.poll(); await drain();
    check('deletes cross both ways and nothing else goes',
      synced === 3 && app.urls().join() === 'https://keep.example/' && d.urls().join() === 'https://keep.example/',
      { syncedFirst: synced, phone: app.urls(), desktop: d.urls() });
  }

  // ---- 4. A tree the app could NOT read is not an empty tree ----------------------------------------------------
  {
    const relay = S.makeRelay(), app = makeApp();
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS), a = makeAndroid(relay, app);
    for (let i = 0; i < 4; i++) d.mk('toolbar_____', 'B' + i, `https://b${i}.example/`);
    await d.init(); await a.init(); await settle(d, a);
    const before = { phone: app.urls().length, live: relay.liveCount() };
    app.failReads = true;
    let mergeRefused = false;
    const p0 = relay.publishes;
    await a.poll();
    try { await a.merge(); } catch (_) { mergeRefused = true; }       // a merge cannot run on a tree it could not read
    await drain(); await a.poll(); await drain();
    await d.pull(); await drain();
    const during = { published: relay.publishes - p0, desktop: d.urls().length };   // measured INSIDE the outage
    app.failReads = false;
    await a.poll(); await drain();
    await d.pull(); await d.merge(); await drain();
    check('a failed read deletes nothing anywhere',
      before.phone === 4 && during.published === 0 && during.desktop === 4
        && app.urls().length === 4 && relay.liveCount() === before.live && d.urls().length === 4,
      { before, during, mergeRefused, phone: app.urls().length, live: relay.liveCount(), desktop: d.urls().length });
  }

  // ---- 5. Bookmarks the phone had BEFORE sync was switched on are a union, not a wipe ---------------------------
  {
    const relay = S.makeRelay(), app = makeApp();
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS), a = makeAndroid(relay, app);
    app.userAdd('https://old-phone.example/');
    d.mk('toolbar_____', 'Desk', 'https://desk.example/');
    await d.init(); await a.init(); await settle(d, a);
    check('first sync gains both sides and deletes none',
      app.urls().join() === 'https://desk.example/,https://old-phone.example/'
        && d.urls().join() === 'https://desk.example/,https://old-phone.example/',
      { phone: app.urls(), desktop: d.urls() });
  }

  // ---- 6. A settled pair goes quiet: polls and merges write nothing -------------------------------------------
  {
    const relay = S.makeRelay(), app = makeApp();
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS), a = makeAndroid(relay, app);
    const f = d.mk('toolbar_____', 'Folder', undefined);
    for (let i = 0; i < 6; i++) d.mk(i % 2 ? f.id : 'menu________', 'Q' + i, `https://q${i}.example/`);
    await d.init(); await a.init(); await settle(d, a); await settle(d, a);
    const p0 = relay.publishes, w0 = app.writes();
    for (let i = 0; i < 3; i++) await settle(d, a);
    check('a settled phone and desktop stop writing', relay.publishes === p0 && app.writes() === w0
      && app.urls().length === 6,
      { publishes: relay.publishes - p0, appWrites: app.writes() - w0, phone: app.urls().length });
  }

  // ---- 7. The app starts listening AFTER the extension's first read (what a real start looks like) --------------
  // GeckoView holds the early connection and drops what was posted on it; the old stand-in waited on that lost
  // answer for ever and never asked the app anything again -- measured on the emulator, not one bridge call.
  {
    const relay = S.makeRelay(), app = makeApp({ listening: false });
    const d = S.makeBrowser('f', relay, DESKTOP_ROOTS);
    d.mk('toolbar_____', 'Desk', 'https://desk-late.example/');
    const a = makeAndroid(relay, app);                       // the stand-in's baseline read goes out now
    await drain();
    app.listen();
    const deadline = (p, ms) => Promise.race([p.then(() => true), new Promise(r => setTimeout(() => r(false), ms))]);
    const ok = await deadline((async () => {
      await d.init(); await a.init(); await settle(d, a);
      app.userAdd('https://late-phone.example/');
      await live(d, a);
    })(), 8000);
    check('a phone whose app starts listening late still syncs both ways',
      ok && app.urls().includes('https://desk-late.example/') && d.urls().includes('https://late-phone.example/')
        && app.dropped() === 0,
      { finished: ok, phone: app.urls(), desktop: d.urls(), droppedBeforeListening: app.dropped() });
  }

  console.log(JSON.stringify(results, null, 1));
})();
