import { webcrack } from 'webcrack';
import fs from 'fs';
import path from 'path';
const [src, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
for (const f of fs.readdirSync(src)) {
  if (!f.endsWith('.js')) continue;
  const code = fs.readFileSync(path.join(src, f), 'utf8');
  if (!/^﻿?const _0x|_0x[0-9a-f]{4,}/.test(code)) { fs.copyFileSync(path.join(src, f), path.join(out, f)); continue; }
  try {
    const r = await webcrack(code, { jsx: false, unpack: false, deobfuscate: true, mangle: false });
    fs.writeFileSync(path.join(out, f), r.code);
    console.log('ok', f, r.code.length);
  } catch (e) {
    console.log('FAIL', f, e.message);
    fs.copyFileSync(path.join(src, f), path.join(out, f));
  }
}
