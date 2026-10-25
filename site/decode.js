const fs = require('fs'), path = require('path');
const dir = process.argv[2], out = process.argv[3];
fs.mkdirSync(out, { recursive: true });
const BS = String.fromCharCode(92);
const reHex = new RegExp(BS + BS + 'x([0-9a-fA-F]{2})', 'g');
const reProp = /\['([A-Za-z_$][A-Za-z0-9_$]*)'\]/g;
for (const f of fs.readdirSync(dir)) {
  if (!f.endsWith('.js')) continue;
  let s = fs.readFileSync(path.join(dir, f), 'utf8');
  s = s.replace(reHex, (m, h) => {
    const c = parseInt(h, 16);
    if (c === 0x27) return BS + "'";
    if (c === 0x5c) return BS + BS;
    if (c === 0x22) return BS + '"';
    if (c === 0x60) return BS + '`';
    if (c >= 0x20 && c < 0x7f) return String.fromCharCode(c);
    return m;
  });
  s = s.replace(reProp, '.$1');
  fs.writeFileSync(path.join(out, f), s);
}
