#!/usr/bin/env python3
"""Declare undefined JP link symbols whose US value is layout independent:
hardware/RDRAM addresses and library, DSP and linker-generated names. Values
come from a US extract's auto scripts and symbol files.

usage: tools/jp_declare_us_auto.py repo_root build_log [us_root]
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(sys.argv[1])
LOG = pathlib.Path(sys.argv[2])
US_ROOT = pathlib.Path(sys.argv[3] if len(sys.argv) > 3 else sys.argv[1])

HW_RANGES = ((0x02000000, 0x04000000), (0x04000000, 0x04100000),
             (0x05000000, 0x07000000))

log = LOG.read_text(errors="replace").replace("\r", "\n")
undef = sorted(set(re.findall(r"undefined reference to .([A-Za-z_0-9]+)", log)))

us = {}
for f in ("auto/undefined_syms_auto.ld", "auto/undefined_funcs_auto.ld",
          "symbol_addrs.txt", "symbol_addrs_code.txt"):
    p = US_ROOT / "linker_scripts/us" / f
    if not p.exists():
        continue
    for line in p.read_text().splitlines():
        m = re.match(r"^\s*(\w+)\s*=\s*0x([0-9A-Fa-f]+)\s*;", line)
        if m:
            us.setdefault(m.group(1), int(m.group(2), 16))

add = []
for n in undef:
    v = us.get(n)
    if v is None:
        continue
    hw = any(lo <= v < hi for lo, hi in HW_RANGES)
    if hw or n.startswith(("__os", "os", ".L")) or n.endswith("_TEXT_START") \
            or ("Main" in n and n.endswith("Start")) or n == "Gallery_Dispatch":
        add.append(f"{n} = 0x{v:08X}; // declared from the US build"
                   + (" (hardware/RDRAM, layout-independent)" if hw else " (library/DSP)"))

und = ROOT / "linker_scripts/jp/undefined_syms.ld"
base = und.read_text()
have = set(re.findall(r"^(\w+)\s*=", base, re.M))
new = [l for l in add if l.split(" = ")[0] not in have]
if new:
    und.write_text(base.rstrip() + "\n\n// Layout-independent symbols from the US build\n"
                   + "\n".join(new) + "\n")
print(f"undefined: {len(undef)}, declared: {len(new)}")
