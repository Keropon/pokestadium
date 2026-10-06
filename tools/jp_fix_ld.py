#!/usr/bin/env python3
"""Fix up the splat-generated JP linker script, printing the result.

- define fragmentNN_TEXT_START inside every fragment section
- place .data for every libultra member

usage: tools/jp_fix_ld.py pokestadium.ld libultra.a
"""
import re
import subprocess
import sys

lines = open(sys.argv[1]).read().splitlines()
members = subprocess.run(["ar", "t", sys.argv[2]], capture_output=True, text=True,
                         check=True).stdout.split()

out = []
pending = None
last_libultra = None
for line in lines:
    out.append(line)
    m = re.match(r"^(\s*)\.(fragment\d+)\s+0x[0-9A-Fa-f]+\s*:", line)
    if m:
        pending = (m.group(1), m.group(2))
        continue
    if pending and re.match(r"^\s*FILL\(", line):
        indent, frag = pending
        out.append(f"{indent}    {frag}_TEXT_START = .;")
        pending = None
    if re.match(r"^\s*build/lib/libultra\.a:\S+\.o\(\.text\);", line):
        last_libultra = len(out) - 1

if last_libultra is not None:
    indent = re.match(r"^(\s*)", out[last_libultra]).group(1)
    existing = set(re.findall(r"libultra\.a:(\S+\.o)\(\.data\)", "\n".join(out)))
    for m in members:
        if m.endswith(".o") and m not in existing:
            out.insert(last_libultra + 1, f"{indent}build/lib/libultra.a:{m}(.data);")

print("\n".join(out))
