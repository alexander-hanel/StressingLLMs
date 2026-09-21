#!/usr/bin/env python3
"""Measure how much of a generated C file is spent on its long type name."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default="hardest.c", type=Path)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"source file not found: {args.source}")
    source = args.source.read_text(encoding="utf-8")
    match = re.search(r"typedef struct (\S+) \{", source)
    if not match:
        raise SystemExit(f"could not find the generated typedef in {args.source}")

    tokenizer = load_tokenizer(resolve_tokenizer(args.tokenizer, slot="a"))
    name = match.group(1)
    name_tokens = len(encode_verified(tokenizer, name).ids)
    name_uses = source.count(name)
    total = len(encode_verified(tokenizer, source).ids)
    print(f"name: {len(name)} chars / {len(name.encode())} bytes -> {name_tokens} tokens")
    print(f"name appears {name_uses} times")
    print(f"tokens spent on the name: ~{name_tokens * name_uses:,}")
    print(f"share of all tokens: {name_tokens * name_uses / total * 100:.1f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
