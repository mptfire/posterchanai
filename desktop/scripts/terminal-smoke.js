#!/usr/bin/env node
'use strict';
/* THE LOCAL TERMINAL, RUN FOR REAL ON THE MACHINE THAT BUILT THE APP.
 *
 * "that shell has exited" (the Windows app, 2026-10-31): the bridge spawned bash through util-linux `script`, which
 * Windows does not have, so every terminal died at once -- and nothing here ran on Windows to see it. CI runs this on
 * each OS before packaging: start a shell through desktop/localterm.js exactly as the app does, type a command, require
 * its OUTPUT back (not the echo of what was typed), resize, and close. Exit 1 with what came back otherwise.
 */
const term = require('../localterm.js');

const MARK = 'PCTERM' + '_' + 'OK';   // split so the typed line itself cannot satisfy the check
const nl = process.platform === 'win32' ? '\r' : '\n';
const cmd = process.platform === 'win32' ? `Write-Output ('PCTERM' + '_OK')` : `echo PCTERM''_OK`;

let out = '', ended = null;
const s = term.start({ cols: 100, rows: 30 });
term.subscribe(s.id, (ev) => { if (ev.t === 'out') out += ev.d; if (ev.t === 'end') ended = ev.code; });

const t0 = Date.now();
setTimeout(() => term.write(s.id, cmd + nl), 1500);
const tick = setInterval(() => {
  // Shells wrap output in escape sequences (titles, OSC 3008 command marks, colours): compare the text, not the bytes.
  const text = out.replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '').replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, '');
  const got = text.split(/\r?\n/).some((l) => l.trim() === MARK);
  if (got) {
    const r = term.resize(s.id, 120, 40);
    clearInterval(tick);
    term.close(s.id);
    if (!r.ok) { console.error('resize refused on a live terminal'); process.exit(1); }
    console.log(`terminal OK on ${process.platform} in ${Date.now() - t0} ms`);
    process.exit(0);
  }
  if (ended !== null || Date.now() - t0 > 30000) {
    clearInterval(tick);
    console.error(`terminal FAILED on ${process.platform}: ${ended !== null ? 'the shell exited (' + ended + ')' : 'no output in 30 s'}`);
    console.error('--- what came back ---\n' + out.slice(-3000));
    process.exit(1);
  }
}, 200);
