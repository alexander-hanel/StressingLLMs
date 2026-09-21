#!/usr/bin/env python3
"""Measure character, byte, and token density for a UTF-8 text file."""

from __future__ import annotations

import argparse
from pathlib import Path

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", default="hardest.c", type=Path)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    args = parser.parse_args()

    if not args.source.is_file():
        parser.error(f"source file not found: {args.source}")
    tokenizer = load_tokenizer(resolve_tokenizer(args.tokenizer, slot="a"))
    source = args.source.read_text(encoding="utf-8")
    count = len(encode_verified(tokenizer, source).ids)
    byte_count = len(source.encode("utf-8"))
    print(f"{len(source):,} chars -> {count:,} tokens")
    print(f"{count / len(source):.4f} tokens per character")
    print(f"{count / byte_count:.3f} tokens per byte")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
