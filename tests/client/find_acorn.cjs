// ONE PLACE TO FIND acorn (a JavaScript parser the tests use to read the shipped client). It is not a dependency of this
// repo, so it is looked for where scripts/split_client_module.mjs looks: $PC_ACORN, the repo's node_modules, then the
// copies a development machine tends to have. Three tests hardcoded /opt/flood/node_modules -- one server's directory --
// and failed everywhere else, GitHub Actions included (2026-10-31).
const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const tries = [process.env.PC_ACORN, path.join(ROOT, 'node_modules/acorn'), '/opt/flood/node_modules/acorn',
               path.join(process.env.HOME || '', 'node_modules/acorn'), '/usr/lib/node_modules/acorn'].filter(Boolean);
let found = null;
for (const p of tries) { try { found = require(p); break; } catch (_) {} }
if (!found) throw new Error('acorn not found (set PC_ACORN or npm install acorn)');
module.exports = found;
