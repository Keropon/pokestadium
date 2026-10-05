#!/usr/bin/env python3
"""Locate the remaining stubs inside a window bounded by verified anchors,
accepting only structurally valid candidates (prologue or matching first word,
jr ra near the end, length within SIZE_TOL of the US function).

Accepted locations are tagged STRUCTURAL: not byte-verified.

usage: tools/jp_bound_stubs.py [repo_root]
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
MARGIN = 0x4000
IDENT_MIN = 0.55
MARGIN_MIN = 0.05
SIZE_TOL = 0.10
JR_RA = 0x03E00008
PROLOGUE_MASK = 0xFFFF0000
PROLOGUE_VAL = 0x27BD0000  # addiu sp,sp,-N

jp = (ROOT / "baseroms/jp/baserom.z64").read_bytes()
us = (ROOT / "baseroms/us/baserom.z64").read_bytes()
words_jp = struct.unpack(f">{len(jp) // 4}I", jp[:len(jp) // 4 * 4])
masked_jp = array("I", (masked_word(w) for w in words_jp))


def align(us_m, start, slack=48):
    n = len(us_m)
    limit = min(len(masked_jp), start + n + slack)
    i, j, matches, last = 0, start, 0, start
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
        last = j
    return matches, n, i, last


rows = list(csv.DictReader(CSV.open()))
VERIFIED = ("yes", "aligned", "structural")
frag_anchors = {}
for r in rows:
    if r["verified"] in VERIFIED and r["delta"]:
        frag_anchors.setdefault(r["seg"].rsplit("/", 1)[0], []).append(int(r["delta"], 16))
anchors = sorted((int(r["us_rom"], 16), int(r["delta"], 16))
                 for r in rows
                 if r["verified"] in VERIFIED and r["delta"] and r["us_rom"])
print(f"anchors: {len(anchors)} verified functions in {len(frag_anchors)} fragments")

out = []
for r in rows:
    if r["verified"] not in ("prefix-only", "NO"):
        continue
    seg = r["seg"]
    us_rom, size = int(r["us_rom"], 16), int(r["size"], 16)
    us_vram = int(r["us_vram"], 16)
    same = frag_anchors.get(seg.rsplit("/", 1)[0], [])

    if same:
        lo_d, hi_d, margin = min(same), max(same), MARGIN
    else:
        # Fragments keep their order, so bracket by the nearest anchors.
        before = [d for o, d in anchors if o < us_rom]
        after = [d for o, d in anchors if o > us_rom]
        if before and after:
            lo_d, hi_d, margin = before[-1], after[0], MARGIN * 16
        elif before or after:
            lo_d = hi_d = (before[-1] if before else after[0])
            margin = MARGIN * 32
        else:
            print(f"  {r['name']:18s} no anchor, skipped")
            continue

    lo = us_rom + lo_d - margin
    hi = us_rom + hi_d + margin
    if r["jp_rom"]:
        c = int(r["jp_rom"], 16)
        lo, hi = min(lo, c - 0x1000), max(hi, c + 0x1000)
    lo = max(0, lo) // 4
    hi = min(len(masked_jp), hi // 4 + size // 4)
    n = size // 4
    us_m = [masked_word(w) for w in struct.unpack(f">{n}I", us[us_rom:us_rom + n * 4])]
    if len(us_m) < 4:
        continue
    us_first, us_len = us_m[0], n

    scored = []
    for s in range(lo, max(lo, hi - n)):
        w = words_jp[s]
        if not (w & PROLOGUE_MASK == PROLOGUE_VAL or masked_jp[s] == us_first):
            continue
        m, tot, consumed, last = align(us_m, s)
        if consumed != tot:
            continue
        span = last - s
        tail = words_jp[max(s, last - 8):last + 2]
        ends_ok = JR_RA in tail
        len_ok = abs(span - us_len) <= max(4, int(us_len * SIZE_TOL))
        if ends_ok and len_ok:
            scored.append((m / tot, m, s, span))
    scored.sort(reverse=True)
    if not scored:
        print(f"  {r['name']:18s} no structurally valid candidate")
        continue
    (ident, m, s, tot) = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    delta = s * 4 - us_rom
    ok = ident >= IDENT_MIN and ident > second + MARGIN_MIN
    print(f"  {r['name']:18s} ident={ident:.3f} 2nd={second:.3f} "
          f"jp_rom=0x{s * 4:X} {'ACCEPT' if ok else 'reject'}")
    if ok:
        r["jp_rom"] = f"0x{s * 4:X}"
        r["jp_vram"] = f"0x{us_vram + delta:08X}"
        r["delta"] = f"{delta:+#x}"
        r["masked_match"] = f"structural {ident:.3f} ({m}/{tot})"
        r["verified"] = "structural"
        out.append((r["name"], us_vram + delta, size))

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
for nm, addr, size in out:
    existing[nm] = f"0x{addr:08X}; // size:0x{size:X} // STRUCTURAL, not byte-verified"
sym.write_text("// JP addresses for the GLOBAL_ASM stubs\n"
               + "\n".join(f"{k} = {v}" for k, v in sorted(existing.items())) + "\n")
print(f"structural accepts: {len(out)}, symbols now: {len(existing)}")
