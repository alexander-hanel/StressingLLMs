#!/usr/bin/env python3
"""Compare repetitive, diverse, and Unicode fixture source files."""

from __future__ import annotations

import argparse
from pathlib import Path

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    parser.add_argument("--repetitive", type=Path, default=Path("rep.c"))
    parser.add_argument("--diverse", type=Path, default=Path("div.c"))
    parser.add_argument("--unicode", type=Path, default=Path("hardest.c"))
    args = parser.parse_args()

    tokenizer = load_tokenizer(resolve_tokenizer(args.tokenizer, slot="a"))
    for label, path in [
        ("repetitive", args.repetitive),
        ("diverse", args.diverse),
        ("unicode OOV", args.unicode),
    ]:
        if not path.is_file():
            parser.error(f"source file not found: {path}")
        source = path.read_text(encoding="utf-8")
        count = len(encode_verified(tokenizer, source).ids)
        print(
            f"{label:12} chars={len(source):,}  bytes={len(source.encode()):,}  "
            f"tokens={count:,}  tpc={count / len(source):.3f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
