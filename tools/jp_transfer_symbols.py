#!/usr/bin/env python3
"""Transfer the US symbol map to JP by keeping each symbol's offset within its
subsegment: jp_vram = jp_subseg_vram + (us_vram - us_subseg_vram).

Overlay (fragments/*) interiors are reordered between versions, so those and
symbols with no JP subsegment are commented out in symbol_addrs and assigned
US placeholder values in undefined_syms.ld instead, which splat does not read.

usage: tools/jp_transfer_symbols.py [repo_root]
writes: linker_scripts/jp/symbol_addrs{,_code,_ultralib}.txt, undefined_syms.ld
"""
import csv
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def load_yaml(ver):
    return yaml.safe_load((ROOT / f"yamls/{ver}/header.yaml").read_text()
                          + (ROOT / f"yamls/{ver}/rom.yaml").read_text())["segments"]


def norm(s):
    if isinstance(s, dict):
        return (s.get("start"), s.get("type") or "", s.get("name") or "",
                s.get("subsegments") or [], s.get("vram"))
    return (s[0], s[1] if len(s) > 1 else "", s[2] if len(s) > 2 else "", [], None)


def collect(segments):
    """name -> [(rom, vram, size, type)] for every subsegment."""
    subs = {}

    def walk(entries, g_vram, g_off):
        entries = [norm(s) for s in entries]
        for i, (off, typ, name, nested, own_vram) in enumerate(entries):
            if nested:
                walk(nested, g_vram, g_off)
                continue
            if off is None:
                if name and own_vram is not None:
                    subs.setdefault(name, []).append((None, own_vram, 0, typ))
                continue
            nxt = next((o for o, *_ in entries[i + 1:] if o is not None), None)
            if name and nxt is not None and nxt > off:
                vram = own_vram if own_vram is not None else (
                    g_vram + (off - g_off) if g_vram is not None else None)
                subs.setdefault(name, []).append((off, vram, nxt - off, typ))

    for g in segments:
        if isinstance(g, dict):
            walk(g.get("subsegments") or [], g.get("vram"), g.get("start"))
    return subs


us_subs = collect(load_yaml("us"))
jp_subs = collect(load_yaml("jp"))

sym_re = re.compile(r"^(\w+)\s*=\s*0x([0-9A-Fa-f]+);(.*)$")
FILES = ("symbol_addrs_code.txt", "symbol_addrs.txt", "symbol_addrs_ultralib.txt")

verified = {}
for r in csv.DictReader((ROOT / "yamls/jp/stubs.csv").open()):
    if r["verified"] in ("yes", "aligned", "structural") and r["jp_vram"]:
        verified[r["name"]] = int(r["jp_vram"], 16)

out, gate, untransferred = {}, [], []
seen_vram = {}
for fname in FILES:
    src = ROOT / "linker_scripts/us" / fname
    if not src.exists():
        continue
    lines, n_ok, n_skip, n_dup = [], 0, 0, 0
    for line in src.read_text().splitlines():
        m = sym_re.match(line.strip())
        if not m:
            lines.append(line)
            continue
        name, us_vram, rest = m.group(1), int(m.group(2), 16), m.group(3)
        hit = None
        for nm, cands in us_subs.items():
            for (rom, vram, size, typ) in cands:
                if vram is not None and size and vram <= us_vram < vram + size:
                    hit = (nm, rom, vram, size, typ)
                    break
            if hit:
                break
        if hit is None or hit[1] is None:
            n_skip += 1
            untransferred.append((name, us_vram, "no JP subsegment"))
            lines.append(f"// {name} = 0x{us_vram:08X};{rest} // UNTRANSFERRED (no JP subsegment)")
            continue
        nm, us_rom, us_svram, size, typ = hit
        cands = jp_subs.get(nm)
        if not cands:
            n_skip += 1
            untransferred.append((name, us_vram, f"{nm} not in JP yaml"))
            lines.append(f"// {name} = 0x{us_vram:08X};{rest} // UNTRANSFERRED ({nm} not in JP yaml)")
            continue
        jp_rom, jp_svram, jp_size, jp_typ = cands[0]
        jp_vram = jp_svram + (us_vram - us_svram)
        if name in verified and verified[name] != jp_vram:
            gate.append((name, verified[name], jp_vram))
        if nm.startswith("fragments/"):
            n_skip += 1
            untransferred.append((name, jp_vram, f"overlay {nm}, offset not preserved"))
            lines.append(f"// {name} = 0x{jp_vram:08X};{rest} "
                         f"// OVERLAY, offset not preserved - needs per-function location")
            continue
        # splat rejects duplicate vrams
        if jp_vram in seen_vram:
            n_dup += 1
            lines.append(f"// {name} = 0x{jp_vram:08X};{rest} "
                         f"// duplicate of {seen_vram[jp_vram]}")
            continue
        seen_vram[jp_vram] = name
        lines.append(f"{name} = 0x{jp_vram:08X};{rest}")
        n_ok += 1
    (ROOT / "linker_scripts/jp" / fname).write_text("\n".join(lines) + "\n")
    out[fname] = (n_ok, n_skip, n_dup)

for f, (ok, skip, dup) in out.items():
    print(f"  {f:28s} {ok:5d} transferred, {skip:4d} untransferred, {dup:4d} deduped")
print(f"verified stubs: {len(verified) - len(gate)} agree, {len(gate)} disagree")
for n, v, got in gate:
    print(f"  {n:18s} verified 0x{v:08X}  computed 0x{got:08X}")

und = ROOT / "linker_scripts/jp/undefined_syms.ld"
base = und.read_text()
have = set(re.findall(r"^(\w+)\s*=", base, re.M))
add = [f"{n} = 0x{v:08X}; // PLACEHOLDER: {why}"
       for n, v, why in untransferred if n not in have and n not in seen_vram]
if add:
    und.write_text(base.rstrip() + "\n\n// Placeholders: no reliable JP address, US values\n"
                   + "\n".join(add) + "\n")
print(f"assigned {len(add)} placeholder symbols")
