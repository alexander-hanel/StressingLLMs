#!/usr/bin/env python3
"""Compare equal-length repetitive and diverse generated identifiers."""

from __future__ import annotations

import argparse

import gen_fixture as fixture
from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    parser.add_argument("--length", type=int, default=256)
    parser.add_argument("--seed", type=lambda value: int(value, 0), default=0xDEADBEEF)
    args = parser.parse_args()

    if args.length < 16:
        parser.error("--length must be at least 16")
    tokenizer = load_tokenizer(resolve_tokenizer(args.tokenizer, slot="a"))
    names = [
        ("repetitive", fixture.build_prefix(args.length)),
        ("diverse", fixture.build_diverse_body(args.length, seed=args.seed)),
    ]
    for label, name in names:
        count = len(encode_verified(tokenizer, name).ids)
        print(
            f"{label:11} {count:4d} tokens / {len(name)} chars = "
            f"{count / len(name):.3f} tpc"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
