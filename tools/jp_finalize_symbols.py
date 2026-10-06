#!/usr/bin/env python3
"""Write the GLOBAL_ASM stub symbols with vram taken from the JP yaml geometry.

Stubs without a verified location inside their subsegment are packed into the
gaps in US order and tagged PLACEHOLDER.

usage: tools/jp_finalize_symbols.py [repo_root]
writes: linker_scripts/jp/symbol_addrs_code.txt
"""
import csv
import pathlib
import sys
from collections import defaultdict

import yaml

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
CSV = ROOT / "yamls/jp/stubs.csv"

groups = yaml.safe_load((ROOT / "yamls/jp/header.yaml").read_text()
                        + (ROOT / "yamls/jp/rom.yaml").read_text())["segments"]
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
        sub[nm] = (off, own_vram if own_vram is not None else g_vram + (off - g_off),
                   nxt - off)


for g in groups:
    if isinstance(g, dict):
        walk(g.get("subsegments") or [], g.get("vram"), g.get("start"))

rows = list(csv.DictReader(CSV.open()))
VERIFIED = ("yes", "aligned", "structural")
TIER = {"yes": "exact", "aligned": "aligned", "structural": "structural"}

by_seg = defaultdict(list)
for r in rows:
    by_seg[r["seg"]].append(r)

out, counts, seen = [], {}, set()
for seg, rs in by_seg.items():
    s_off, s_vram, s_size = sub[seg]
    rs.sort(key=lambda r: int(r["us_rom"], 16))
    cursor = s_off
    for r in rs:
        name, size = r["name"], int(r["size"], 16)
        jp_rom = None
        tier = "PLACEHOLDER"
        if r["jp_rom"] and r["verified"] in VERIFIED:
            cand = int(r["jp_rom"], 16)
            if s_off <= cand < s_off + s_size:
                jp_rom, tier = cand, TIER[r["verified"]]

        sz = size if tier != "PLACEHOLDER" else min(size, s_size)
        if jp_rom is None:
            jp_rom = cursor
        jp_rom = max(s_off, min(max(jp_rom, cursor), s_off + s_size - sz))
        cursor = jp_rom + sz
        jp_vram = s_vram + (jp_rom - s_off)
        assert (seg, jp_vram) not in seen, f"{name}: duplicate vram in {seg}"
        assert s_vram <= jp_vram < s_vram + s_size, f"{name}: vram outside {seg}"
        seen.add((seg, jp_vram))
        counts[tier] = counts.get(tier, 0) + 1
        out.append((name, jp_vram, sz, tier))

sym = ROOT / "linker_scripts/jp/symbol_addrs_code.txt"
sym.write_text(
    "// JP addresses for the GLOBAL_ASM stubs. PLACEHOLDER entries have no location evidence.\n"
    + "\n".join(f"{n} = 0x{v:08X}; // size:0x{s:X} // {t}" for n, v, s, t in out) + "\n")

print(f"wrote {len(out)} symbols -> {sym.relative_to(ROOT)}")
for t, c in sorted(counts.items()):
    print(f"  {t:12s} {c}")
