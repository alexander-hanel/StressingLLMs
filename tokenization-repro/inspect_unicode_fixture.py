#!/usr/bin/env python3
"""Validate the Unicode identifier in a generated fixture."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default="hardest.c", type=Path)
    parser.add_argument("--body-length", type=int, default=512)
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"source file not found: {args.source}")
    source = args.source.read_text(encoding="utf-8")
    match = re.search(r"typedef struct (\S+) \{", source)
    if not match:
        raise SystemExit(f"could not find the generated typedef in {args.source}")
    name = match.group(1)
    body = name[: args.body_length]
    print(f"{len(name)} chars")
    print(" ".join(f"U+{ord(char):05X}" for char in name[:20]))
    print("all in range:", all(0x30000 <= ord(char) <= 0x303FF for char in body))
    print("each is 4 bytes:", len(body.encode("utf-8")) == len(body) * 4)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
