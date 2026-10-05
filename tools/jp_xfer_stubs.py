#!/usr/bin/env python3
"""Locate the GLOBAL_ASM stub functions in the JP ROM by their masked
instruction stream.

usage: tools/jp_xfer_stubs.py [repo_root]
writes: yamls/jp/stubs.csv, linker_scripts/jp/symbol_addrs_code.txt
"""
import csv
import pathlib
import re
import struct
import sys
from array import array

import yaml

from jpmatch import masked_word

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
us = (ROOT / "baseroms/us/baserom.z64").read_bytes()
jp = (ROOT / "baseroms/jp/baserom.z64").read_bytes()

pragma_re = re.compile(r'#pragma GLOBAL_ASM\("asm/\w+/nonmatchings/([^"]+?)/(\w+)\.s"\)')
stubs = []
for c in sorted((ROOT / "src").rglob("*.c")):
    for m in pragma_re.finditer(c.read_text(errors="replace")):
        stubs.append((m.group(1), m.group(2)))
print(f"GLOBAL_ASM stubs found: {len(stubs)}")
assert len(stubs) == 31, f"expected 31 stubs, found {len(stubs)}"

sym_re = re.compile(r"^(\w+)\s*=\s*0x([0-9A-Fa-f]+);")
syms = {}
for f in ("symbol_addrs_code.txt", "symbol_addrs.txt", "symbol_addrs_ultralib.txt"):
    p = ROOT / "linker_scripts/us" / f
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        m = sym_re.match(line.strip())
        if m:
            syms[m.group(1)] = int(m.group(2), 16)

groups = yaml.safe_load((ROOT / "yamls/us/header.yaml").read_text()
                        + (ROOT / "yamls/us/rom.yaml").read_text())["segments"]
sub = {}


def norm(s):
    if isinstance(s, dict):
        return (s.get("start"), s.get("type") or "", s.get("name") or "",
                s.get("subsegments") or [], s.get("vram"))
    return (s[0], s[1] if len(s) > 1 else "", s[2] if len(s) > 2 else "", [], None)


def walk(subs, g_vram, g_off):
    entries = [norm(s) for s in subs]
    for i, (off, typ, name, nested, own_vram) in enumerate(entries):
        if off is None:
            continue
        if nested:
            walk(nested, g_vram, g_off)
            continue
        if typ != "c":
            continue
        nxt = next((o for o, t, *_ in entries[i + 1:] if o is not None), None)
        if nxt is None or nxt <= off:
            continue
        nm = name or f"{off:X}"
        vram = own_vram if own_vram is not None else g_vram + (off - g_off)
        assert nm not in sub or sub[nm] == (off, vram, nxt - off), f"conflicting {nm}"
        sub[nm] = (off, vram, nxt - off)


for g in groups:
    if isinstance(g, dict):
        walk(g.get("subsegments") or [], g.get("vram"), g.get("start"))

# ponytail: rebuilt every run (~30s); cache to disk if this runs often.
masked_jp = array("I", (masked_word(w) for w in
                        struct.unpack(f">{len(jp) // 4}I", jp[:len(jp) // 4 * 4])))

rows, out = [], []
for seg, fname in stubs:
    assert fname in syms, f"{fname} not in us symbol files"
    assert seg in sub, f"subsegment {seg} not found in us yaml"
    us_vram = syms[fname]
    s_off, s_vram, s_size = sub[seg]

    inside = sorted(a for a in set(syms.values())
                    if s_vram < a < s_vram + s_size and a > us_vram)
    size = (inside[0] if inside else s_vram + s_size) - us_vram
    us_rom = s_off + (us_vram - s_vram)
    if not (0 < size <= s_size and 0 <= us_rom < len(us)):
        print(f"  SKIP {fname} ({seg}): bad geometry")
        rows.append(dict(name=fname, seg=seg, us_vram=f"0x{us_vram:08X}",
                         us_rom="", size="", jp_vram="", jp_rom="", delta="",
                         cands=0, masked_match="geom-error", verified="NO"))
        continue

    us_words = struct.unpack(f">{size // 4}I", us[us_rom:us_rom + size // 4 * 4])
    us_masked = [masked_word(w) for w in us_words]
    if not us_masked:
        continue

    # Seed on one word from the head, middle and tail; rank by the longest
    # contiguous match from the start.
    best = None
    for key_idx in {0, len(us_masked) // 2, len(us_masked) - 1}:
        key = us_masked[key_idx]
        for i, w in enumerate(masked_jp):
            if w != key:
                continue
            start = i - key_idx
            if start < 0 or start >= len(masked_jp):
                continue
            pre = 0
            for k, mw in enumerate(us_masked):
                if start + k >= len(masked_jp) or masked_jp[start + k] != mw:
                    break
                pre += 1
            tot = sum(1 for k, mw in enumerate(us_masked)
                      if start + k < len(masked_jp) and masked_jp[start + k] == mw)
            if best is None or (pre, tot) > (best[0], best[1]):
                best = (pre, tot, start)

    pre, best_n, best = (best[0], best[1], best[2]) if best else (0, 0, None)
    ok = best is not None and pre == len(us_masked)
    near = best is not None and pre >= min(12, len(us_masked))
    jp_rom = best * 4 if best is not None else None
    delta = (jp_rom - us_rom) if jp_rom is not None else None
    rows.append(dict(name=fname, seg=seg, us_vram=f"0x{us_vram:08X}",
                     us_rom=f"0x{us_rom:X}", size=f"0x{size:X}",
                     jp_vram=f"0x{us_vram + delta:08X}" if delta is not None else "",
                     jp_rom=f"0x{jp_rom:X}" if jp_rom is not None else "",
                     delta=f"{delta:+#x}" if delta is not None else "",
                     cands=len(us_masked), masked_match=f"prefix {pre}/{len(us_masked)} tot {best_n}",
                     verified="yes" if ok else ("prefix-only" if near else "NO")))
    if ok:
        out.append(f"{fname} = 0x{us_vram + delta:08X}; // size:0x{size:X}")

dst = ROOT / "yamls/jp/stubs.csv"
with dst.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)

good = sum(1 for r in rows if r["verified"] == "yes")
print(f"located + verified: {good}/{len(rows)}")
if good:
    sym_dst = ROOT / "linker_scripts/jp/symbol_addrs_code.txt"
    sym_dst.write_text("// JP addresses for the GLOBAL_ASM stubs\n" + "\n".join(out) + "\n")
    print(f"wrote {len(out)} symbols -> {sym_dst.relative_to(ROOT)}")
