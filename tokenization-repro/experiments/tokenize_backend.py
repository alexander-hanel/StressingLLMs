"""
Offline BPE tokenizer backend for the repetition-stress experiments.

No third-party packages are available in this environment (no network, no `regex`,
no `tiktoken`, no HF `tokenizers`). So this module:

  1. Loads a HuggingFace `tokenizer.json` (BPE) directly.
  2. Implements ByteLevel BPE in pure Python:
        - byte-level pre-tokenization (GPT-2 style byte<->unicode map)
        - a faithful subset of the HF `Split` pre-tokenizer regex, implemented
          WITHOUT the `regex` module by classifying characters via `unicodedata`
        - rank-based BPE merging
  3. Exposes a simple `Tokenizer` class with `.encode(text) -> list[int]`.

FIDELITY NOTE (important, read before trusting numbers):
  This is NOT bit-exact with `tokenizers`/`tiktoken` for arbitrary Unicode input.
  It is designed to be *exact for ASCII* (letters, digits, underscore, punct,
  whitespace) which is what `gen_fixture.py` emits, and to be *self-consistent*
  across all corpus items. For relative comparisons of repetition effects
  (tokens-per-char at fixed tokenizer + fixed alphabet) that is sufficient.
  Round-trip decode(encode(x)) == x is asserted as a guard.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


# ---------------------------------------------------------------------------
# Byte <-> unicode map (GPT-2 / ByteLevel)
# ---------------------------------------------------------------------------

def _bytes_to_unicode() -> dict[int, str]:
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, [chr(c) for c in cs]))


BYTE_TO_UNICODE = _bytes_to_unicode()
UNICODE_TO_BYTE = {v: k for k, v in BYTE_TO_UNICODE.items()}


def text_to_bytelevel(text: str) -> str:
    """UTF-8 encode then map each byte to its printable unicode surrogate."""
    return "".join(BYTE_TO_UNICODE[b] for b in text.encode("utf-8"))


def bytelevel_to_text(s: str) -> str:
    return bytes(UNICODE_TO_BYTE[ch] for ch in s).decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Minimal unicode-class helpers approximating \p{L}, \p{N}, \p{M}, \p{P}, \p{S}
# (good enough for ASCII; reasonable for common Unicode)
# ---------------------------------------------------------------------------

import unicodedata as _ud


def _cat(ch: str) -> str:
    return _ud.category(ch)


def is_letter(ch: str) -> bool:
    return _cat(ch)[0] == "L"


def is_number(ch: str) -> bool:
    return _cat(ch)[0] == "N"


def is_mark(ch: str) -> bool:
    return _cat(ch)[0] == "M"


def is_punct(ch: str) -> bool:
    return _cat(ch)[0] == "P"


def is_symbol(ch: str) -> bool:
    return _cat(ch)[0] == "S"


def is_upper_lt_lm_lo(ch: str) -> bool:
    return _cat(ch) in ("Lu", "Lt", "Lm", "Lo")


def is_lower_lm_lo(ch: str) -> bool:
    return _cat(ch) in ("Ll", "Lm", "Lo")


def is_space(ch: str) -> bool:
    return ch.isspace()


# ---------------------------------------------------------------------------
# Pre-tokenizer: implement the GPT-4 / cl100k-style Split regex.
#
# The HF pattern (for the nemotron tokenizer) is:
#   [^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]*[\p{Ll}\p{Lm}\p{Lo}\p{M}]+
# | [^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*
# | \p{N}
# |  ?[^\s\p{L}\p{N}]+[\r\n/]*
# | \s*[\r\n]+
# | \s+(?!\S)
# | \s+
#
# `behavior: Isolated` means matched pieces are separate tokens and the gaps
# BETWEEN matches are ALSO emitted as pieces. We implement a greedy scan that
# mirrors the alternation order (HF/tiktoken use leftmost-longest per the RE2
# ordering), which for ASCII identifiers/punctuation matches tiktoken closely.
# ---------------------------------------------------------------------------

@lru_cache(maxsize=64)
def _split_patterns(pattern_type: str):
    return pattern_type


def _match_gpt4_at(s: str, i: int) -> int:
    """Return end index of the longest match starting at i for the GPT-4-style
    alternation. Returns -1 if no alternative matches. Order matters."""
    n = len(s)

    def is_letter_or_number(ch: str) -> bool:
        return is_letter(ch) or is_number(ch)

    # alt 1: [^\r\n\p{L}\p{N}]? [\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]* [\p{Ll}\p{Lm}\p{Lo}\p{M}]+
    def alt1() -> int:
        j = i
        # optional single non-newline, non-letter, non-number char
        if j < n and s[j] not in "\r\n" and not is_letter_or_number(s[j]):
            j += 1
        # *[Lu Lt Lm Lo M]
        while j < n and is_upper_lt_lm_lo(s[j]) or (j < n and is_mark(s[j])):
            j += 1
        # +[Ll Lm Lo M]
        k = j
        while k < n and (is_lower_lm_lo(s[k]) or is_mark(s[k])):
            k += 1
        if k > j:
            return k
        return -1

    # alt 2: [^\r\n\p{L}\p{N}]?[\p{Lu}\p{Lt}\p{Lm}\p{Lo}\p{M}]+[\p{Ll}\p{Lm}\p{Lo}\p{M}]*
    def alt2() -> int:
        j = i
        if j < n and s[j] not in "\r\n" and not is_letter_or_number(s[j]):
            j += 1
        k = j
        while k < n and (is_upper_lt_lm_lo(s[k]) or is_mark(s[k])):
            k += 1
        if k > j:
            while k < n and (is_lower_lm_lo(s[k]) or is_mark(s[k])):
                k += 1
            return k
        return -1

    # alt 3: \p{N}   (single number)
    def alt3() -> int:
        if i < n and is_number(s[i]):
            return i + 1
        return -1

    # alt 4:  ?[^\s\p{L}\p{N}]+[\r\n/]*
    def alt4() -> int:
        j = i
        if j < n and s[j] == " ":
            j += 1
        k = j
        while k < n and (not is_space(s[k])) and (not is_letter(s[k])) and (not is_number(s[k])):
            k += 1
        if k > j:
            while k < n and s[k] in "\r\n/":
                k += 1
            return k
        return -1

    # alt 5: \s*[\r\n]+
    def alt5() -> int:
        j = i
        while j < n and is_space(s[j]) and s[j] not in "\r\n":
            j += 1
        k = j
        while k < n and s[k] in "\r\n":
            k += 1
        if k > j:
            return k
        return -1

    # alt 6: \s+(?!\S)
    def alt6() -> int:
        j = i
        while j < n and is_space(s[j]):
            j += 1
        if j > i and j == n:
            return j
        return -1

    # alt 7: \s+
    def alt7() -> int:
        j = i
        while j < n and is_space(s[j]):
            j += 1
        return j if j > i else -1

    best = -1
    for fn in (alt1, alt2, alt3, alt4, alt5, alt6, alt7):
        e = fn()
        if e > best:
            best = e
    return best


def pretokenize_isolated(text: str) -> list[str]:
    """Split `text` into pieces per the GPT-4-style Isolated Split."""
    pieces: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        e = _match_gpt4_at(text, i)
        if e <= i:
            # No match: emit the single char as its own piece (gap handling)
            pieces.append(text[i])
            i += 1
        else:
            pieces.append(text[i:e])
            i = e
    return pieces


# ---------------------------------------------------------------------------
# BPE
# ---------------------------------------------------------------------------

@dataclass
class Tokenizer:
    vocab: dict[str, int]
    merges: dict[tuple[str, str], int]  # (left, right) -> rank

    @classmethod
    def from_file(cls, path: str | Path) -> "Tokenizer":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        model = d["model"]
        if model.get("type") != "BPE":
            raise ValueError(f"unsupported model type: {model.get('type')}")
        vocab = model["vocab"]
        merges_raw = model["merges"]
        merges: dict[tuple[str, str], int] = {}
        for rank, m in enumerate(merges_raw):
            if isinstance(m, str):
                a, b = m.split(" ", 1)
            else:
                a, b = m[0], m[1]
            merges[(a, b)] = rank
        return cls(vocab=vocab, merges=merges)

    def _bpe(self, token: str) -> list[str]:
        """Apply BPE merges to a single pre-token (already byte-level encoded)."""
        if not token:
            return []
        # If the whole token is a known vocab entry, shortcut.
        if token in self.vocab:
            return [token]
        parts = list(token)
        merges = self.merges
        while True:
            best_rank = None
            best_idx = -1
            for i in range(len(parts) - 1):
                pair = (parts[i], parts[i + 1])
                r = merges.get(pair)
                if r is not None and (best_rank is None or r < best_rank):
                    best_rank = r
                    best_idx = i
            if best_idx == -1:
                break
            parts = (
                parts[:best_idx]
                + [parts[best_idx] + parts[best_idx + 1]]
                + parts[best_idx + 2 :]
            )
        return parts

    def encode(self, text: str) -> list[int]:
        ids: list[int] = []
        unk = self.vocab.get("<unk>")
        for piece in pretokenize_isolated(text):
            bl = text_to_bytelevel(piece)
            for tok in self._bpe(bl):
                tid = self.vocab.get(tok)
                if tid is None:
                    # Byte-level fallback: encode each byte separately.
                    for ch in tok:
                        bid = self.vocab.get(ch)
                        if bid is None:
                            if unk is None:
                                raise KeyError(f"no id for token piece {tok!r}")
                            bid = unk
                        ids.append(bid)
                else:
                    ids.append(tid)
        return ids

    def decode(self, ids: list[int]) -> str:
        inv = {v: k for k, v in self.vocab.items()}
        s = "".join(inv.get(i, "") for i in ids)
        return bytelevel_to_text(s)

    def count(self, text: str) -> int:
        return len(self.encode(text))
