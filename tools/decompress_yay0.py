#!/usr/bin/env python3

import sys
import re
import os
from pathlib import Path
import crunch64

# This will only decompress an asset that has a single Yay0!
# usage: decompress_yay0.py [in file] [out file]

filepath = Path(sys.argv[1])
filebytes = filepath.read_bytes()

try:
    decompressed = crunch64.yay0.decompress(filebytes)
except Exception:
    print("SKIP", filepath, "- not Yay0 (offset likely wrong); left as-is")
    sys.exit(0)

fileout = Path(sys.argv[2])
fileout.write_bytes(decompressed)
