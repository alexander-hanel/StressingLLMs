#!/usr/bin/env python3
"""Compare emoji and high-plane Unicode under two vocabularies."""

from __future__ import annotations

import argparse

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer-a", help="model A tokenizer.json")
    parser.add_argument("--tokenizer-b", help="model B tokenizer.json")
    args = parser.parse_args()

    model_a = load_tokenizer(resolve_tokenizer(args.tokenizer_a, slot="a"))
    model_b = load_tokenizer(resolve_tokenizer(args.tokenizer_b, slot="b"))
    samples = [
        ("emoji x100", "😀" * 100),
        ("oov x100", "".join(chr(0x30000 + index) for index in range(100))),
    ]
    for label, text in samples:
        a_count = len(encode_verified(model_a, text).ids)
        b_count = len(encode_verified(model_b, text).ids)
        print(f"{label:10} model A={a_count}  model B={b_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
