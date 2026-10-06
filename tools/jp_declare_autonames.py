#!/usr/bin/env python3
"""Declare splat auto-names (D_<addr>, func_<addr>) that the link reports as
undefined. A name inside a JP yaml span is a rom offset and gets that span's
vram; any other name is its own address.

usage: tools/jp_declare_autonames.py [repo_root] build_log
"""
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(sys.argv[1])
LOG = pathlib.Path(sys.argv[2])

log = LOG.read_text(errors="replace").replace("\r", "\n")
names = sorted(set(re.findall(r"undefined reference to .([A-Za-z_0-9]+)", log)))

txt = (ROOT / "yamls/jp/header.yaml").read_text() + (ROOT / "yamls/jp/rom.yaml").read_text()
spans = []
for g in ((yaml.safe_load(txt) or {}).get("segments") or []):
    if not isinstance(g, dict):
        continue
    gs, gv = g.get("start"), g.get("vram")
    if gs is None or gv is None:
        continue
    entries = [(s[0] if isinstance(s, list) and s else (s.get("start") if isinstance(s, dict) else None))
               for s in (g.get("subsegments") or [])]
    offs = [o for o in entries if isinstance(o, int)]
    for i, off in enumerate(offs):
        nxt = next((o for o in offs[i + 1:] if o > off), None)
        if nxt:
            spans.append((off, nxt, gv + (off - gs)))
spans.sort()

lines = []
for n in names:
    if not re.fullmatch(r"[A-Za-z]+_[0-9A-Fa-f]{4,8}", n):
        continue
    val = int(n.rsplit("_", 1)[1], 16)
    hit = next(((s, e, v) for (s, e, v) in spans if s <= val < e), None)
    if hit is not None:
        s, e, v = hit
        lines.append(f"{n} = 0x{v + (val - s):08X}; // auto-name, from JP rom 0x{val:X}")
    else:
        lines.append(f"{n} = 0x{val:08X}; // auto-name, address taken from the name")

und = ROOT / "linker_scripts/jp/undefined_syms.ld"
base = und.read_text()
have = set(re.findall(r"^(\w+)\s*=", base, re.M))
add = [l for l in lines if l.split(" = ")[0] not in have]
if add:
    und.write_text(base.rstrip() + "\n\n// splat auto-names defined by nothing\n"
                   + "\n".join(add) + "\n")
print(f"declared {len(add)} auto-names")
