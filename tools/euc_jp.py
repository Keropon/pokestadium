#!/usr/bin/env python3

import codecs
import os
import sys
from pathlib import Path
import find_sym

if len(sys.argv) == 2:
    print(codecs.decode(sys.argv[1].replace("0x", ""), "hex").decode("euc-jp"))
else:
    offset = find_sym.find(sys.argv[2])["rom"]
    version = os.environ.get("VERSION", "us")
    data = (Path(sys.argv[0]).absolute().parent / f"../baseroms/{version}/baserom.z64").read_bytes()

    s = data[offset:data.find(b"\x00", offset)]
    print(s.decode("euc-jp"))
