#!/usr/bin/env python3
"""Create a placeholder .s for every GLOBAL_ASM pragma path, since
asm-processor opens it even when NON_MATCHING selects the C body.

usage: tools/jp_place_stubs.py [repo_root]
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

pragmas = set()
for c in (ROOT / "src").rglob("*.c"):
    pragmas.update(re.findall(r'GLOBAL_ASM\(\s*"([^"]+)"', c.read_text(errors="replace")))

made = 0
for rel in sorted(pragmas):
    if not rel.startswith("asm/"):
        continue
    p = ROOT / rel.replace("asm/us/", "asm/jp/", 1)
    if p.exists():
        continue
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(".text\n")
    made += 1

print(f"created {made} placeholder stubs")
