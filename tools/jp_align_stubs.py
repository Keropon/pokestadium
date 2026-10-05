#!/usr/bin/env python3
"""Locate the 'prefix-only' stubs with an insert/delete tolerant alignment.

usage: tools/jp_align_stubs.py [repo_root]
updates: yamls/jp/stubs.csv, linker_scripts/jp/symbol_addrs_code.txt
"""
import csv
import pathlib
import struct
import sys
from array import array

from jpmatch import masked_word

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
CSV = ROOT / "yamls/jp/stubs.csv"
ACCEPT = 0.90

us = (ROOT / "baseroms/us/baserom.z64").read_bytes()
jp = (ROOT / "baseroms/jp/baserom.z64").read_bytes()
masked_jp = array("I", (masked_word(w) for w in
                        struct.unpack(f">{len(jp) // 4}I", jp[:len(jp) // 4 * 4])))


def align_score(us_m, start, slack=32):
    """Greedy alignment allowing single-step indels: (matches, length, consumed)."""
    n = len(us_m)
    limit = min(len(masked_jp), start + n + slack)
    i, j, matches = 0, start, 0
    if start < 0:
        return 0, n, 0
    while i < n and j < limit:
        if us_m[i] == masked_jp[j]:
            matches += 1
            i += 1
            j += 1
        elif i + 1 < n and us_m[i + 1] == masked_jp[j]:
            i += 1
        elif j + 1 < limit and us_m[i] == masked_jp[j + 1]:
            j += 1
        else:
            i += 1
            j += 1
    return matches, n, i


def candidates(us_m):
    n = len(us_m)
    starts = set()
    for k in sorted({0, n // 5, (2 * n) // 5, (3 * n) // 5, (4 * n) // 5, n - 3}):
        if k < 0 or k + 3 > n:
            continue
        seed = us_m[k], us_m[k + 1], us_m[k + 2]
        for i, w in enumerate(masked_jp):
            if w != seed[0] or i + 2 >= len(masked_jp):
                continue
            if masked_jp[i + 1] == seed[1] and masked_jp[i + 2] == seed[2]:
                s = i - k
                if 0 <= s < len(masked_jp):
                    starts.add(s)
    return starts


rows = list(csv.DictReader(CSV.open()))
upgraded = []
for r in rows:
    if r["verified"] != "prefix-only" or not r["us_rom"]:
        continue
    us_rom = int(r["us_rom"], 16)
    size = int(r["size"], 16)
    us_vram = int(r["us_vram"], 16)
    us_m = [masked_word(w) for w in
            struct.unpack(f">{size // 4}I", us[us_rom:us_rom + size // 4 * 4])]
    if len(us_m) < 4:
        continue

    scored = []
    for s in candidates(us_m):
        m, n, consumed = align_score(us_m, s)
        if consumed == n:
            scored.append((m / n, m, s))
    scored.sort(reverse=True)
    if not scored:
        print(f"  {r['name']}: no candidate spanned the window")
        continue

    best, second = scored[0], (scored[1] if len(scored) > 1 else (0, 0, 0))
    ident, m, s = best
    jp_rom = s * 4
    delta = jp_rom - us_rom
    ok = ident >= ACCEPT and ident > second[0] + 0.03
    print(f"  {r['name']:18s} ident={ident:.3f} runner-up={second[0]:.3f} "
          f"jp_rom=0x{jp_rom:X} {'ACCEPT' if ok else 'reject'}")
    if ok:
        r["jp_rom"] = f"0x{jp_rom:X}"
        r["jp_vram"] = f"0x{us_vram + delta:08X}"
        r["delta"] = f"{delta:+#x}"
        r["masked_match"] = f"aligned {ident:.3f} ({m}/{len(us_m)})"
        r["verified"] = "aligned"
        upgraded.append((r["name"], us_vram + delta, size))

with CSV.open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
    w.writeheader()
    w.writerows(rows)

sym = ROOT / "linker_scripts/jp/symbol_addrs_code.txt"
existing = {}
for line in sym.read_text().splitlines():
    if " = 0x" in line:
        nm, rest = line.split(" = ", 1)
        existing[nm.strip()] = rest.strip()
for nm, addr, size in upgraded:
    existing[nm] = f"0x{addr:08X}; // size:0x{size:X}"
sym.write_text("// JP addresses for the GLOBAL_ASM stubs\n"
               + "\n".join(f"{k} = {v}" for k, v in sorted(existing.items())) + "\n")
print(f"aligned {len(upgraded)}, symbols now: {len(existing)}")
