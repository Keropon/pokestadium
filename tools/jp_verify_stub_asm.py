#!/usr/bin/env python3
"""Assemble each emitted stub and compare it against the JP baserom slice.

usage: tools/jp_verify_stub_asm.py [repo_root]
"""
import csv
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
CROSS = os.environ.get("CROSS", "mips-linux-gnu-")
ROM = (ROOT / "baseroms/jp/baserom.z64").read_bytes()
ASM = ROOT / "asm/jp/nonmatchings"
TMP = pathlib.Path(tempfile.mkdtemp())
TMP_S, TMP_O, TMP_B = TMP / "stub.s", TMP / "stub.o", TMP / "stub.bin"

ok, bad, skipped, fails = 0, 0, 0, []
for r in csv.DictReader((ROOT / "yamls/jp/stubs.csv").open()):
    p = ASM / r["seg"] / f"{r['name']}.s"
    if not p.exists() or not r.get("jp_rom"):
        skipped += 1
        continue
    src = re.sub(r"^glabel \S+\n", "", p.read_text(), flags=re.M)
    src = ".set noat\n.set noreorder\n.set nomacro\n" + src
    TMP_S.write_text(src)
    a = subprocess.run([f"{CROSS}as", "-mips32r2", "-EB", "-o", str(TMP_O), str(TMP_S)],
                       capture_output=True)
    if a.returncode != 0:
        bad += 1
        fails.append((r["name"], a.stderr.decode()[:100].replace("\n", " ")))
        continue
    subprocess.run([f"{CROSS}objcopy", "-O", "binary", "-j", ".text",
                    str(TMP_O), str(TMP_B)], capture_output=True)
    off, size = int(r["jp_rom"], 16), int(r["size"], 16)
    # as pads .text, compare only the first size bytes
    want, got = ROM[off:off + size], TMP_B.read_bytes()[:size]
    if got == want:
        ok += 1
        continue
    bad += 1
    d = next((i for i in range(0, min(len(got), len(want)), 4) if got[i:i + 4] != want[i:i + 4]), 0)
    fails.append((r["name"], f"word {d // 4}: want {want[d:d + 4].hex()} got {got[d:d + 4].hex()}"))

print(f"stub asm round-trip: identical {ok}, failed {bad}, skipped {skipped}")
for n, e in fails:
    print(f"   {n}: {e}")
sys.exit(1 if bad else 0)
