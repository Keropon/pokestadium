#!/usr/bin/env python3
"""Disassemble each located GLOBAL_ASM stub from the JP baserom into asm that
reassembles to the same bytes.

usage: tools/jp_emit_stub_asm.py [repo_root]
writes: asm/jp/nonmatchings/<seg>/<name>.s
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
CSV = ROOT / "yamls/jp/stubs.csv"
BASEROM = ROOT / "baseroms/jp/baserom.z64"
OUT = ROOT / "asm/jp/nonmatchings"

REGS = r"zero|at|v[01]|a[0-3]|t[0-9]|s[0-8]|k[01]|gp|sp|fp|ra"
RE_REG = re.compile(rf"(?<![\w$])({REGS})(?![\w])")
RE_JMP = re.compile(r"^(j|jal)\b")
RE_HEXARG = re.compile(r"\b(0x[0-9a-f]+)\s*$")


def disassemble(blob, vram):
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "slice.bin"
        path.write_bytes(blob)
        # no-aliases keeps encodings that round-trip
        out = subprocess.run(
            [f"{CROSS}objdump", "-D", "-b", "binary", "-m", "mips:isa32r2", "-EB",
             "-M", "no-aliases", f"--adjust-vma={vram:#x}", str(path)],
            capture_output=True).stdout.decode("utf-8", "replace")
    rows = []
    for line in out.splitlines():
        m = re.match(r"\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(.*)$", line)
        if m:
            rows.append((int(m.group(1), 16), m.group(2), re.sub(r"\s+", " ", m.group(3).strip())))
    return rows


rows = list(csv.DictReader(CSV.open()))
rom = BASEROM.read_bytes()

written = skipped = 0
for r in rows:
    name, seg = r["name"], r["seg"]
    if not (r.get("jp_rom") and r.get("jp_vram") and r.get("size")):
        skipped += 1
        continue
    off, vram, size = int(r["jp_rom"], 16), int(r["jp_vram"], 16), int(r["size"], 16)
    if off + size > len(rom):
        skipped += 1
        continue

    body = disassemble(rom[off:off + size], vram)
    if not body:
        skipped += 1
        continue

    targets = set()
    for a, _w, ins in body:
        if not RE_JMP.match(ins):
            m = RE_HEXARG.search(ins)
            if m and int(m.group(1), 16) >= 0x80000000:
                targets.add(int(m.group(1), 16))

    lines = [".set noat", ".set noreorder", ".set nomacro", f"glabel {name}"]
    for a, word, ins in body:
        ins = RE_REG.sub(r"$\1", ins)
        ins = ins.replace("c1_fcsr", "$31")
        if not RE_JMP.match(ins):
            m = RE_HEXARG.search(ins)
            if m and int(m.group(1), 16) >= 0x80000000:
                t = int(m.group(1), 16)
                if vram <= t < vram + size:
                    ins = ins[:m.start(1)] + f".L{t:X}"
                else:
                    ins = ins[:m.start(1)] + f".+{t - a}"
        if a in targets:
            lines.append(f".L{a:X}:")
        lines.append(f"    /* {off + (a - vram):X} {a:08X} {word.upper()} */  {ins}")
    lines.append(".set at")

    target = OUT / seg / f"{name}.s"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n")
    written += 1

print(f"emitted: {written}, skipped: {skipped}")
