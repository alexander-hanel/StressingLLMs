#!/usr/bin/env python3
"""Check Python, package, tokenizer data, and optional compiler prerequisites."""

from __future__ import annotations

import argparse
import importlib.metadata
import shutil
import sys

from tokenizer_paths import resolve_tokenizer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-model-b", action="store_true")
    args = parser.parse_args()

    failures = []
    print(f"Python: {sys.version.split()[0]}")
    try:
        from tokenizers import Tokenizer
        del Tokenizer
        tokenizer_version = importlib.metadata.version("tokenizers")
    except (ImportError, importlib.metadata.PackageNotFoundError):
        failures.append("tokenizers package is not installed")
    else:
        print(f"tokenizers: {tokenizer_version}")

    model_a = resolve_tokenizer(None, slot="a", required=False)
    model_b = resolve_tokenizer(None, slot="b", required=False)
    print(f"model A: {model_a or 'not configured'}")
    print(f"model B: {model_b or 'not configured'}")
    print(f"gcc: {shutil.which('gcc') or 'not installed (needed only to compile fixtures)'}")
    if not model_a:
        failures.append("model A tokenizer is not configured")
    if args.require_model_b and not model_b:
        failures.append("model B tokenizer is not configured")

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1
    print("Setup is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
