#!/usr/bin/env python3
"""Shared tokenizer-file discovery for the runnable examples."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
SLOTS = {
    "a": ("TOKENIZER_A", ROOT / "tokenizer-data" / "model-a.json"),
    "b": ("TOKENIZER_B", ROOT / "tokenizer-data" / "model-b.json"),
}


def _as_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def resolve_tokenizer(
    explicit: str | Path | None,
    *,
    slot: str = "a",
    required: bool = True,
) -> Path | None:
    """Resolve an explicit, environment, or package-local tokenizer path."""
    if slot not in SLOTS:
        raise ValueError(f"unknown tokenizer slot: {slot}")

    env_name, packaged = SLOTS[slot]
    candidates: list[Path] = []
    if explicit:
        candidates.append(_as_path(explicit))
    if os.environ.get(env_name):
        candidates.append(_as_path(os.environ[env_name]))
    candidates.append(packaged)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    if not required:
        return None

    requested = "model A" if slot == "a" else "model B"
    tried = "\n  ".join(str(path) for path in candidates)
    raise SystemExit(
        f"No {requested} tokenizer.json was found.\n"
        f"Pass a tokenizer path, set {env_name}, or copy the file to {packaged}.\n"
        f"Checked:\n  {tried}"
    )


def load_tokenizer(path: str | Path):
    """Load a Hugging Face tokenizer with a useful dependency error."""
    try:
        from tokenizers import Tokenizer
    except ImportError as exc:
        raise SystemExit(
            "The 'tokenizers' package is not installed. Run:\n"
            "  python3 -m venv .venv\n"
            "  .venv/bin/python -m pip install -r requirements.txt"
        ) from exc
    return Tokenizer.from_file(str(path))


def encode_verified(tokenizer, text: str):
    """Encode text and require an exact decode before returning the encoding."""
    encoding = tokenizer.encode(text, add_special_tokens=False)
    decoded = tokenizer.decode(encoding.ids, skip_special_tokens=False)
    if decoded != text:
        raise RuntimeError(
            "tokenizer round-trip failed: decoded text does not match the input"
        )
    return encoding


def parse_named_tokenizers(items: Iterable[str]) -> dict[str, Path]:
    """Parse repeated NAME=PATH values, or discover model A and B defaults."""
    result: dict[str, Path] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"invalid --tokenizer value {item!r}; expected NAME=PATH")
        name, raw_path = item.split("=", 1)
        name = name.strip()
        if not name or not raw_path.strip():
            raise SystemExit(f"invalid --tokenizer value {item!r}; expected NAME=PATH")
        path = _as_path(raw_path.strip())
        if not path.is_file():
            raise SystemExit(f"tokenizer file not found: {path}")
        result[name] = path

    if result:
        return result

    model_a = resolve_tokenizer(None, slot="a", required=False)
    model_b = resolve_tokenizer(None, slot="b", required=False)
    if model_a:
        result["model-a"] = model_a
    if model_b:
        result["model-b"] = model_b
    if not result:
        resolve_tokenizer(None, slot="a", required=True)
    return result
