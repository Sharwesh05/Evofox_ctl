# EvoFox Ghost X – reverse-engineering notes

Source: `https://support.amkette.com/webapp/ghostx/` (Vue 3 / Vite build, obfuscated with
obfuscator.io, WebHID). The device page is `/webapp/ghostx/ghostx/`; the launcher page only lists
HID devices and redirects there. Everything below was read from that JavaScript – nothing was
sniffed from a real device.

## How the site was analysed

1. Mirrored both builds (`site/dl`, `site/dev`) by following the Vite `import()`/modulepreload graph.
2. Decoded `\xNN` string escapes (`site/decode.js`), then ran `webcrack` to resolve the rotated
   string arrays (`site/wc/run.mjs`) → `site/devclean/*.js`.
3. Protocol lives in `DybcMjfDgff_Sc52H5v-*.js` (transport + register read/write),
   `DybcMjfDgff_AFyt95F-*.js` (button/DPI/LED “apply” logic), `DybcMjfDgff_Difr52V-*.js`
   (constants, default data, DPI tables) and `DybcMjfDgff_Uoi2Dy8-*.js` (device discovery,
   input-report handling).
4. `rea` (v6.7.0) was installed and healthy for the web analysis commands, but its
   `recover-javascript-sources` needs the external *Wakaru* binary, which is not installed, so
   `webcrack` was used for the de-obfuscation step.

## Device

| item | value |
|---|---|
| vendor id | `0xB6A4` |
| product ids | `0x40B0` wired (“EvoFox Ghost X”), `0x40C1` 2.4 GHz dongle (“EvoFox Ghost X-2.4G”) |
| series | M400 (report-rate codes 64…1) |
| buttons | 6 (left, middle, right, back, forward, DPI) + wheel up/down |
| profiles | 3 (`ProfileID` 0‥2); every setting below belongs to the active profile |
| DPI stages | 8 |
| lighting | the protocol has back-light (cmd 9) and DPI-colour (cmd 7) commands, but **this model has no lighting**, so the tool neither reads nor writes them |
| other HID ids | input report **5** = key/profile/DPI/dongle-link notifications (not needed to configure) |

The site also ships a filter list with other PIDs (`0x4000, 0x4001, 0x4080 … 0x40C1`) for sibling
products of the same vendor firmware family; only `0x40B0/0x40C1` are mapped to the Ghost X page.

## Transport

HID **feature report ID 6**. The array the site passes to `sendFeatureReport(6, data)` is
`reportCount` bytes long (largest feature `reportCount` of the descriptor); including the report ID
the OS frame is:

```
idx 0  6            report id
    1  0
    2  0
    3  cmd          (|0x80 for reads)
    4  seq          ++counter, wraps at 256
    5  did          distinguish id (sub-command)
    6  addr lo
    7  addr hi
    8  len          bytes to read / bytes written
    9… payload
```

* write = SET_FEATURE, wait 50 ms (30 ms before the next).
* read  = SET_FEATURE with `cmd|0x80`, wait 80 ms, GET_FEATURE; the reply is valid when
  `reply[8] != 0 && reply[3] == cmd|0x80 && reply[5] == did`, data starts at `reply[9]`. Up to 5 tries.
  (The site indexes the reply exactly like that, so the report ID is part of the buffer; the Python
  client also accepts the one-byte-shifted layout in case a host stack strips the ID.)

## Commands

| cmd | did | addr | len | meaning |
|---|---|---|---|---|
| 1 | 0 | 0 | 3 | read only: `[link, battery(bit7=charging,low7=%), sensor chip]` |
| 2 | 1 | `profile*2` | 2 | profile “random id” (big-endian). Written after every change so the web app knows the device changed |
| 2 | 2 | 0 | 1 | active profile 0‥2 |
| 2 | 3 | 0 | 2 | sleep time, seconds, LE (UI: 1‥30 min) |
| 2 | 4 | 0 | 2 | power-down time (unused by the UI) |
| 2 | 5 | 0 | 1 | bit7 tracking optimisation, bit2 motion sync, bit1 ripple control / jitter suppression, bit0 line correction |
| 2 | 6 | 0 | 1 | LOD (chip specific: 3395/3950/S301/S312 → 0 or 2, 3389 → 2 or 3) |
| 2 | 7 | 0 | 1 | charge count |
| 2 | 8 | 0 | 1 | scene mode: 1 “fire all out”, 17 “long endurance”, 33 “endurance” |
| 3 | 0 | 0 | 1 | report rate: 125→64, 250→32, 500→16, 1000→8, 2000→4, 4000→2, 8000→1 |
| 4 | 0 | `key*4` | 4 | button function slot (key 0‥5 = L, M, R, back, fwd, DPI) |
| 5 | 0 | `n*4` | 4 | wheel function slot (0 = up, 1 = down) |
| 6 | 0 | 0 | 20 | DPI: `[enable mask, current(1‥8), 8×u16 hardware value, u16 multiplier bits]` |
| 7 | 0 | 0 | 24 | DPI stage colours, 8×`[G,R,B]` |
| 8 | key | `page*32` | 32 | macro memory of one key (≤ 512 bytes) |
| 9 | 0 | 0 | 25 | back-light: `[0x80 \| smart<<6 \| mode, enable lo, enable hi, …]` |
| 9 | 0 | `mode*25` | 25 | per-mode block `[speed 1‥7, direction 0/1, 6‑brightness, colour-enable mask, 7×[G,R,B]]` |
| 10 | 1 | 0 | 1 | number of keys *(read only here)* |
| 10 | 2 | 0 | 1 | key debounce 1‥20 ms |
| 10 | 5 | 0 | 1 | number of LEDs *(read only here)* |
| 10 | 6 | 0 | 1 | wake on movement |
| 112/113 | | | | firmware-version commands – defined, never used by the site |
| **127** | | | | **bootloader – never sent by this tool** |

### Button slot (4 bytes)

`[class, a, b, c]` – `1` mouse (a = bitmask 1 L, 2 R, 4 M, 8 back, 16 fwd), `2` keyboard (up to 3 HID usages,
modifiers 224‥231), `3` ACPI (1 power, 2 sleep, 3 wake), `4` media/consumer (u16 usage), `5` scroll (1 up,
129 down), `6` rate switch, `7` LED (1 mode, 2 speed, 3 brightness, 4 on/off), `8` DPI (1 +, 2 −, 3 cycle),
`9` profile (1 +, 2 −, 3 cycle, 4 fixed + index), `10` macro `[10, repeatType | assign<<7, keyIndex,
randomDelayFlag<<7 | delay]`, `11` horizontal scroll (1 left, 129 right). Double/triple click, fire key and
“aim” are macros the site generates (see `ghostx/macros.py::preset`).

### DPI

Hardware value comes from a per-chip table (`ghostx/data/dpi_tables.json`, 14 sensors) – values above
the native table are the native entry with a 2-bit multiplier (`calcMul`). The sensor chip id is the third
byte of command 1.

### Macro bytes

See `ghostx/macros.py` docstring (u16 repeat, u16 length, entries for key / DPI / relative-move with short
and long delay forms).

## Things deliberately not reproduced

* writing `KeyNumMax` / `BackLightLedNumMax` parameters (factory parameters – the tool reads them only);
* the bootloader command;
* the site’s `localhost:62887` connection (listed in the CSP for the vendor’s optional desktop helper;
  the web page itself never calls it).
