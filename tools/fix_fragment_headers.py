#!/usr/bin/env python3
"""Recompute each fragment's in-ROM header from the linker symbols.

Why: the Fragment header (memmap.h) is a `textbin` subsegment, i.e. bytes copied out of the
retail ROM, and the loader trusts it - `Asset_LoadCompressed` copies `sizeInRom` bytes and
`Memmap_RelocateFragment` finds the relocation table at `relocOffset`. Retail values are only
correct while the fragment keeps its retail size, so any change to a fragment's code or data
silently makes the loader read the wrong bytes. Everything needed is already in the linker
script, so recompute it after linking instead of hardcoding it.

  relocOffset = fragment_relocs_ROM_START - fragment_ROM_START
  sizeInRom   = fragment_relocs_ROM_END   - fragment_ROM_START
  sizeInRam   = sizeInRom + fragment_BSS_SIZE - relocs_size

Verified against every retail fragment header: relocOffset 77/77, sizeInRom 77/77,
sizeInRam 75/77.

usage: fix_fragment_headers.py <elf> <rom> <fragment> [fragment ...]

The fragment list is required on purpose: sizeInRam does not fit every fragment in the
retail ROM (fragment50 and fragment73 differ), so patching anything you did not modify
risks corrupting a header that was already right.
"""
import re
import struct
import subprocess
import sys

HEADER_OFF = {"headerSize": 0x10, "relocOffset": 0x14, "sizeInRom": 0x18, "sizeInRam": 0x1C}
MAGIC_OFF = 0x08


def symbols(elf, nm="mips-linux-gnu-nm"):
    out = subprocess.run([nm, elf], capture_output=True, text=True, check=True).stdout
    syms = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3:
            syms[parts[2]] = int(parts[0], 16)
    return syms


def fragment_names(syms):
    return sorted({m.group(1) for k in syms if (m := re.fullmatch(r"(fragment\d+)_ROM_START", k))})


def fix(rom, syms, name):
    """-> (values written, message)"""
    try:
        start = syms[f"{name}_ROM_START"]
        relocs_start = syms[f"{name}_relocs_ROM_START"]
        relocs_end = syms[f"{name}_relocs_ROM_END"]
        bss = syms[f"{name}_BSS_SIZE"]
    except KeyError as e:
        return None, None, f"{name}: missing linker symbol {e}"
    reloc_offset = relocs_start - start
    size_in_rom = relocs_end - start
    size_in_ram = size_in_rom + bss - (relocs_end - relocs_start)
    if rom[start + MAGIC_OFF:start + MAGIC_OFF + 8] != b"FRAGMENT":
        return None, None, f"{name}: no FRAGMENT magic at 0x{start:X}, refusing to write"
    old = struct.unpack(">III", rom[start + 0x14:start + 0x20])
    rom[start + 0x14:start + 0x18] = struct.pack(">I", reloc_offset)
    rom[start + 0x18:start + 0x1C] = struct.pack(">I", size_in_rom)
    rom[start + 0x1C:start + 0x20] = struct.pack(">I", size_in_ram)
    return (reloc_offset, size_in_rom, size_in_ram), old, (
        f"{name}: relocOffset 0x{old[0]:X}->0x{reloc_offset:X}  "
        f"sizeInRom 0x{old[1]:X}->0x{size_in_rom:X}  sizeInRam 0x{old[2]:X}->0x{size_in_ram:X}")


def selftest():
    rom = bytearray(0x100)
    rom[0x00:0x08] = struct.pack(">II", 0x08000020, 0)
    rom[MAGIC_OFF:MAGIC_OFF + 8] = b"FRAGMENT"
    struct.pack_into(">III", rom, 0x14, 0x3440, 0x37F0, 0x3D00)
    syms = {
        "fragment59_ROM_START": 0x00,
        "fragment59_relocs_ROM_START": 0x3440,
        "fragment59_relocs_ROM_END": 0x37F0,
        "fragment59_BSS_SIZE": 0x8C0,
    }
    vals, old, msg = fix(rom, syms, "fragment59")
    assert vals == (0x3440, 0x37F0, 0x3D00), vals
    # grew by 0x80: relocs move, bss stays
    syms["fragment59_relocs_ROM_START"] += 0x80
    syms["fragment59_relocs_ROM_END"] += 0x80
    vals, old, msg = fix(rom, syms, "fragment59")
    assert vals == (0x34C0, 0x3870, 0x3D80), vals
    assert struct.unpack(">III", rom[0x14:0x20]) == vals
    assert len(rom) == 0x100, "header fix must not resize the ROM"
    # a non-fragment region is refused
    bad = bytearray(0x100)
    assert fix(bad, syms, "fragment59")[0] is None
    print("selftest ok")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        selftest()
        sys.exit(0)
    elf, rom_path = sys.argv[1], sys.argv[2]
    names = sys.argv[3:]
    if not names:
        sys.exit("give at least one fragment name (e.g. fragment59) - see the docstring")
    rom = bytearray(open(rom_path, "rb").read())
    syms = symbols(elf)
    changed = 0
    for name in names:
        vals, old, msg = fix(rom, syms, name)
        if vals is None:
            print(msg)
            continue
        if vals != old:
            changed += 1
            print(msg)
    if changed:
        open(rom_path, "wb").write(rom)
        print(f"patched {changed} fragment header(s) in {rom_path}")
    else:
        print("all fragment headers already match the linker layout")
