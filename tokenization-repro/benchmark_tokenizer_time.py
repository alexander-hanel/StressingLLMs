#!/usr/bin/env python3
"""Measure tokenizer time for long, uninterrupted letter runs."""

from __future__ import annotations

import argparse
import time

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


def parse_sizes(value: str) -> list[int]:
    try:
        sizes = [int(item) for item in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("sizes must be comma-separated integers") from exc
    if not sizes or any(size <= 0 for size in sizes):
        raise argparse.ArgumentTypeError("sizes must be positive")
    return sizes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    parser.add_argument("--sizes", type=parse_sizes, default=parse_sizes("16000,64000,256000"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    if args.repeats < 1:
        parser.error("--repeats must be at least 1")
    tokenizer = load_tokenizer(resolve_tokenizer(args.tokenizer, slot="a"))
    for size in args.sizes:
        text = "a" * size
        encode_verified(tokenizer, text)
        samples = []
        for _ in range(args.repeats):
            started = time.perf_counter()
            tokenizer.encode(text)
            samples.append(time.perf_counter() - started)
        print(f"{size:7d} chars  {min(samples):.4f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
