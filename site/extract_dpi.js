const fs = require('fs');
const src = fs.readFileSync('D:/Workspace/evofox_ctl/site/devclean/DybcMjfDgff_Difr52V-D7foCCV_.js', 'utf8');
const start = src.indexOf('dpiGearList: {');
let i = src.indexOf('{', start);
let depth = 0, j = i;
for (; j < src.length; j++) {
  if (src[j] === '{') depth++;
  else if (src[j] === '}') { depth--; if (depth === 0) break; }
}
const lit = src.slice(i, j + 1);
const obj = eval('(' + lit + ')');
const out = {};
for (const [chip, v] of Object.entries(obj)) {
  out[chip] = { dpiMax: v.dpiMax, dpiMin: v.dpiMin, dpiStep: v.dpiStep, dpi: v.dpi.map(d => [d.value, d.hardwareValue]) };
}
fs.writeFileSync('D:/Workspace/evofox_ctl/site/dpi_tables.json', JSON.stringify(out));
for (const [c, v] of Object.entries(out)) console.log(c, v.dpi.length, v.dpiMin, v.dpiMax, v.dpiStep, JSON.stringify(v.dpi.slice(-2)));
