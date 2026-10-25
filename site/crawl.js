// Recursively mirror a Vite build starting from an index URL.
const fs = require('fs'), path = require('path');
const BASE = 'https://support.amkette.com';
const root = process.argv[2];          // e.g. /webapp/ghostx/ghostx/
const out = process.argv[3];
const seen = new Set();
const queue = [];
function add(p) { if (!seen.has(p)) { seen.add(p); queue.push(p); } }
async function get(p) {
  const r = await fetch(BASE + p);
  if (!r.ok) { console.log('FAIL', r.status, p); return null; }
  return Buffer.from(await r.arrayBuffer());
}
(async () => {
  const idx = await get(root);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(path.join(out, 'index.html'), idx);
  const re = /["'(]((?:\/webapp\/ghostx\/ghostx\/)?(?:\.\/|assets\/)?[A-Za-z0-9_@.\/-]+\.(?:js|css|json|png|svg|jpg|jpeg|webp|woff2?|ttf|wasm|mp3|gif|lottie))["')]/g;
  const scan = (txt, cur) => {
    let m;
    while ((m = re.exec(txt))) {
      let u = m[1];
      let abs;
      if (u.startsWith('/webapp/')) abs = u;
      else if (u.startsWith('./')) abs = path.posix.join(path.posix.dirname(cur), u);
      else if (u.startsWith('assets/')) abs = root + u;
      else continue;
      add(abs);
    }
  };
  scan(idx.toString('utf8'), root);
  while (queue.length) {
    const p = queue.shift();
    const buf = await get(p);
    if (!buf) continue;
    const f = path.join(out, p.slice(root.length));
    fs.mkdirSync(path.dirname(f), { recursive: true });
    fs.writeFileSync(f, buf);
    if (/\.(js|css)$/.test(p)) scan(buf.toString('utf8'), p);
  }
  console.log('done', seen.size);
})();
