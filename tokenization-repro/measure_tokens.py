#!/usr/bin/env python3
"""Count tokens for the sample strings in the tokenization walkthrough."""

from __future__ import annotations

import argparse

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


SAMPLES = [
    "compute_value",
    "TokenizerBench__DemangleLike__std__basic_string__char__std__char_traits__",
    "😀" * 10,
    "0" * 10,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    args = parser.parse_args()

    path = resolve_tokenizer(args.tokenizer, slot="a")
    tokenizer = load_tokenizer(path)
    for sample in SAMPLES:
        count = len(encode_verified(tokenizer, sample).ids)
        print(
            f"{count:3d} tokens / {len(sample):3d} chars = "
            f"{count / len(sample):.3f} tpc"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
