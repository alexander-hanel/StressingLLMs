#!/usr/bin/env python3
"""Print UTF-8 bytes and token density for the page's sample strings."""

from __future__ import annotations

import argparse

from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer


SAMPLES = {
    "short identifier": "compute_value",
    "natural English": "The quick brown fox jumps over the lazy dog.",
    "repetitive name": "TokenizerBench__DemangleLike__std__basic_string__",
    "random letters": "xkfjqzmwbp",
    "digits": "1234567890",
    "emoji": "😀",
    "high-plane OOV": chr(0x30000),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", help="Hugging Face tokenizer.json; defaults to model A")
    args = parser.parse_args()

    tokenizer = load_tokenizer(resolve_tokenizer(args.tokenizer, slot="a"))
    for label, text in SAMPLES.items():
        raw = text.encode("utf-8")
        hex_bytes = " ".join(f"{byte:02X}" for byte in raw)
        count = len(encode_verified(tokenizer, text).ids)
        print(
            f"{label:18} chars={len(text):3} bytes={len(raw):3} tokens={count:2} "
            f"tpc={count / len(text):.3f}  {hex_bytes}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
