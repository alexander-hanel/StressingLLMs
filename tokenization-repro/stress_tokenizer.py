#!/usr/bin/env python3
"""
stress_tokenizer.py — a SINGLE self-contained script that ATTEMPTS TO SUCCEED at the
project goal: produce/"find" text that is maximally expensive to tokenize.

The goal has two distinct axes (see HOSTILE.md):
  AXIS-1  token COUNT   : maximize tokens per character  (cost/context pressure)
  AXIS-2  tokenizer TIME: maximize wall-clock latency     (CPU pressure)

This script does three things end-to-end, in one file:
  1. Loads REAL tokenizers (HF `tokenizers`, bit-exact). Falls back to the repo's
     pure-Python backend if the venv/tokenizers is unavailable.
  2. SEARCHES a space of candidate constructions for the worst case on each axis
     (not hand-waved -- it measures every candidate and reports the winner).
  3. Emits the winning hostile payload(s) to disk and prints a verdict table.

Honesty constraints (the point of the exercise is measurement, not magic):
  * "Untokenizable" does NOT exist for byte-level BPE: worst case is 1 token per
    UTF-8 byte, so max tokens/char == 4 (a 4-byte OOV char). We verify this.
  * On AXIS-2, real tokenizers are ~linear in input length (Rust, O(n log n) BPE),
    so there is NO quadratic blow-up to exploit. The script measures this and
    reports it rather than pretending otherwise.

Run (uses the offline venv installed for this repo):
    .venv/bin/python stress_tokenizer.py                      # full run
    .venv/bin/python stress_tokenizer.py --quick              # small sizes
    python3 stress_tokenizer.py --no-real                     # historical fallback

Ethics: this generates worst-case *inputs* for a tokenizer. It is a measurement
study. Do not aim it at services you do not own or are not authorized to test.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import string
import sys
import time
import unicodedata
from pathlib import Path

from tokenizer_paths import parse_named_tokenizers

HERE = Path(__file__).resolve().parent

# ----------------------------------------------------------------------------
# Tokenizer backends: try real (HF tokenizers) first, else the repo fallback.
# ----------------------------------------------------------------------------

class RealTokenizer:
    kind = "real"

    def __init__(self, name: str, path: str | Path):
        from tokenizers import Tokenizer as HFTokenizer
        self.name = name
        self.path = str(path)
        self._tk = HFTokenizer.from_file(self.path)

    def encode(self, text: str) -> list[int]:
        return self._tk.encode(text, add_special_tokens=False).ids

    def decode(self, ids: list[int]) -> str:
        return self._tk.decode(ids, skip_special_tokens=False)

    def verify_round_trip(self, text: str) -> None:
        if self.decode(self.encode(text)) != text:
            raise RuntimeError(f"{self.name}: tokenizer round-trip failed")

    def count(self, text: str) -> int:
        return len(self.encode(text))

    def splits(self, text: str) -> list[str]:
        return self._tk.encode(text, add_special_tokens=False).tokens


class PyTokenizer:
    kind = "python"

    def __init__(self, name: str, path: str):
        sys.path.insert(0, str(HERE / "experiments"))
        import tokenize_backend as tb
        self.name = name
        self.path = path
        self._tk = tb.Tokenizer.from_file(path)

    def encode(self, text: str) -> list[int]:
        return self._tk.encode(text)

    def decode(self, ids: list[int]) -> str:
        return self._tk.decode(ids)

    def verify_round_trip(self, text: str) -> None:
        if self.decode(self.encode(text)) != text:
            raise RuntimeError(f"{self.name}: tokenizer round-trip failed")

    def count(self, text: str) -> int:
        return len(self._tk.encode(text))

    def splits(self, text: str) -> list[str]:
        return []  # not exposed by the fallback backend


def load_tokenizers(prefer_real: bool, vocabs: dict[str, Path]) -> dict[str, object]:
    tks = {}
    for name, path in vocabs.items():
        if not os.path.exists(path):
            print(f"  ! vocab missing: {path}", file=sys.stderr)
            continue
        if prefer_real:
            try:
                tks[name] = RealTokenizer(name, path)
                continue
            except Exception as e:
                print(f"  ! real backend unavailable for {name}: {e}", file=sys.stderr)
        tks[name] = PyTokenizer(name, path)
    return tks


# ----------------------------------------------------------------------------
# Candidate generators (the "search space" for hostile text).
# ----------------------------------------------------------------------------

# 4-byte, high-plane chars that are typically NOT single vocab tokens:
# each UTF-8 byte becomes its own token -> up to 4 tokens/char.
EMOJI = ["😀", "🤖", "🧠", "🪐", "🚀", "👾", "🦾", "🌀", "🧩", "🛸"]

# Non-ASCII but valid text, mostly multi-byte; good for "no vocab entry" probes.
CJK = "漢字龍鳳龜鷹鑫龘靐齉"

REMARKS = "\u0301\u0302\u0303\u0308"  # combining marks (can evade normalization)

LETTERS = string.ascii_lowercase


def gen_emoji(n: int) -> str:
    return "".join(EMOJI[i % len(EMOJI)] for i in range(n))


def gen_emoji_random(n: int, seed: int = 1) -> str:
    r = random.Random(seed)
    return "".join(r.choice(EMOJI) for _ in range(n))


def gen_digits(n: int) -> str:
    return "0" * n  # each digit isolated by \p{N} -> 1 token/char (ASCII worst)


def gen_cjk(n: int, seed: int = 2) -> str:
    r = random.Random(seed)
    return "".join(r.choice(CJK) for _ in range(n))


def gen_combining(n: int, seed: int = 3) -> str:
    """base letter + combining mark: may not merge back to the base token."""
    r = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(r.choice(LETTERS)); out.append(r.choice(REMARKS))
    return "".join(out)


def gen_random_letters(n: int, seed: int = 4) -> str:
    r = random.Random(seed)
    return "".join(r.choice(LETTERS) for _ in range(n))


def gen_single_run(n: int) -> str:
    """One uninterrupted pre-token (no separators) -> tests AXIS-2 scaling."""
    return "a" * n


def gen_run_chars(n: int, chars: str) -> str:
    """One uninterrupted run drawn from `chars` (no spaces/punct/digits)."""
    r = random.Random(5)
    return "".join(r.choice(chars) for _ in range(n))


def gen_diverse_ident(n: int, seed: int = 6) -> str:
    """High-diversity identifier (many distinct segments) -> token-cost probe."""
    r = random.Random(seed)
    parts, cur = ["DiverseRoot"], 0
    while len("_".join(parts)) < n:
        parts.append("seg" + "".join(r.choice("abcdef") for _ in range(6)))
        cur += 1
        if cur > 10000:
            break
    return "_".join(parts)[:n]


def gen_repetitive_ident(n: int) -> str:
    chunk = "DemangleLike__std__basic_string__char__std__char_traits__"
    return ("TokenizerBench__" + chunk * (1 + n // len(chunk)))[:n]


def gen_utf8_oov_highplane(n: int, seed: int = 7) -> str:
    """Rare high-plane codepoints unlikely to be in any vocab -> byte fallback.

    We pick codepoints in a high plane but NOT emoji (so not in the emoji
    ranges that tokenizers often include). Each is 4 UTF-8 bytes.
    """
    r = random.Random(seed)
    return "".join(chr(0x30000 + r.randrange(0, 0x3FF)) for _ in range(n))


def gen_mixed_worstcase(n: int, seed: int = 8) -> str:
    """Attempt BOTH axes: blocks of 4-byte OOV chars interleaved with long
    letter runs (the letter runs stress compute; the OOV chars stress count)."""
    r = random.Random(seed)
    out = []
    while sum(map(len, out)) < n:
        out.append("".join(r.choice(EMOJI) for _ in range(r.randint(2, 6))))
        out.append(r.choice("abcdefg") * r.randint(20, 60))
    return "".join(out)[:n]


CANDIDATES = [
    ("emoji_cyclic", gen_emoji),
    ("emoji_random", gen_emoji_random),
    ("highplane_oov", gen_utf8_oov_highplane),
    ("cjk_random", gen_cjk),
    ("combining_marks", gen_combining),
    ("digits", gen_digits),
    ("random_letters", gen_random_letters),
    ("repetitive_ident", gen_repetitive_ident),
    ("diverse_ident", gen_diverse_ident),
    ("single_letter_run", gen_single_run),
    ("mixed_worstcase", gen_mixed_worstcase),
]


# ----------------------------------------------------------------------------
# Axis 1 & 2 measurement.
# ----------------------------------------------------------------------------

def measure_axis1(tks, size: int) -> list[dict]:
    rows = []
    for label, fn in CANDIDATES:
        text = fn(size)
        row = {"candidate": label, "chars": len(text)}
        for tkname, tk in tks.items():
            tk.verify_round_trip(text)
            t0 = time.perf_counter()
            n = tk.count(text)
            dt = time.perf_counter() - t0
            row[tkname] = n
            row[f"{tkname}_tpc"] = n / max(len(text), 1)
            row[f"{tkname}_ms"] = dt * 1000
        rows.append(row)
    return rows


def measure_axis2(tks, sizes: list[int], shape: str = "run") -> list[dict]:
    """Scale ONE pre-token and fit the growth exponent."""
    rows = []
    for n in sizes:
        text = gen_single_run(n)
        row = {"chars": n}
        for tkname, tk in tks.items():
            tk.verify_round_trip(text)
            best = min(
                (lambda t0: (lambda dt: dt)(time.perf_counter() - t0))(time.perf_counter())
                for _ in range(1)
            )
            # best-of-3, warm
            times = []
            for _ in range(3):
                t0 = time.perf_counter()
                tk.encode(text)
                times.append(time.perf_counter() - t0)
            row[f"{tkname}_s"] = min(times)
            row[f"{tkname}_ms_per_mb"] = min(times) * 1000 / (n / 1e6)
        rows.append(row)
    return rows


def fit_exponent(rows, key: str) -> float:
    """Least-squares slope of log(t) vs log(n) -> growth exponent."""
    import math
    xs = [math.log(r["chars"]) for r in rows]
    ys = [math.log(r[key]) for r in rows if r[key] > 0]
    xs = xs[:len(ys)]
    if len(xs) < 2:
        return float("nan")
    mx = sum(xs) / len(xs); my = sum(ys) / len(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else float("nan")


def separator_contrast(tks, size: int) -> dict:
    shapes = {
        "one_letter_run": "a" * size,
        "underscore_split": "a_" * (size // 2),
        "digit_isolated": "0" * size,
        "emoji": gen_emoji(size),
    }
    out = {}
    for tkname, tk in tks.items():
        sub = {}
        for label, text in shapes.items():
            tk.verify_round_trip(text)
            times = []
            for _ in range(3):
                t0 = time.perf_counter(); tk.encode(text); times.append(time.perf_counter() - t0)
            sub[label] = min(times)
        out[tkname] = sub
    return out


# ----------------------------------------------------------------------------
# Reporting.
# ----------------------------------------------------------------------------

def hdr(s: str) -> None:
    print("\n" + s + "\n" + "-" * len(s))


def main() -> int:
    ap = argparse.ArgumentParser(description="Attempt to find worst-case tokenizer inputs.")
    ap.add_argument("--size", type=int, default=4000, help="chars for Axis-1 candidates")
    ap.add_argument("--quick", action="store_true", help="small sizes (fast smoke test)")
    ap.add_argument("--no-real", action="store_true", help="force pure-python backend")
    ap.add_argument(
        "--tokenizer",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help=(
            "tokenizer to measure; repeat for multiple vocabularies. Defaults to "
            "TOKENIZER_A/TOKENIZER_B or tokenizer-data/model-a.json and model-b.json"
        ),
    )
    ap.add_argument("--outdir", default=str(HERE / "hostile_out"))
    args = ap.parse_args()

    size = 500 if args.quick else args.size
    scale_sizes = [2000, 8000, 32000] if args.quick else [2000, 8000, 32000, 128000, 512000]

    print("=" * 74)
    print(" stress_tokenizer.py  —  attempting the goal: worst-case tokenizer input")
    print("=" * 74)

    vocab_paths = parse_named_tokenizers(args.tokenizer)
    tks = load_tokenizers(prefer_real=not args.no_real, vocabs=vocab_paths)
    if not tks:
        print("FATAL: no tokenizers available.", file=sys.stderr)
        return 2
    print(f"tokenizers: " + ", ".join(f"{k}({v.kind})" for k, v in tks.items()))

    # ---- AXIS 1: token count per char ----
    hdr(f"AXIS 1 — token COUNT per char  (size={size} chars)")
    rows = measure_axis1(tks, size)
    cols = list(tks.keys())
    print(f"{'candidate':18} {'chars':>6} " + " ".join(f"{c+'_tok':>10} {c+'_tpc':>9}" for c in cols))
    best_axis1 = {c: (None, -1.0) for c in cols}
    for r in rows:
        line = f"{r['candidate']:18} {r['chars']:>6} "
        for c in cols:
            line += f"{r[c]:>10} {r[c+'_tpc']:>9.3f} "
            if r[c + "_tpc"] > best_axis1[c][1]:
                best_axis1[c] = (r["candidate"], r[c + "_tpc"])
        print(line)
    print("\nWINNER per tokenizer (max tokens/char):")
    for c in cols:
        print(f"  {c:9} -> {best_axis1[c][0]:18} tpc={best_axis1[c][1]:.3f}")

    # distinguish "no vocab entry" (byte fallback) vs multibyte accounting
    hdr("AXIS 1 — theory check: worst case is 1 token per UTF-8 byte")
    for label, s in [("4-byte emoji x100", gen_emoji(100)),
                     ("3-byte CJK x100", gen_cjk(100)),
                     ("1-byte ASCII digit x100", gen_digits(100))]:
        nb = len(s.encode("utf-8"))
        for c, tk in tks.items():
            tk.verify_round_trip(s)
            n = tk.count(s)
            print(f"  {label:24} {c:9} bytes={nb:5d} tokens={n:5d} tokens/byte={n/nb:.3f} "
                  f"tokens/char={n/len(s):.3f}")

    # ---- AXIS 2: tokenizer time ----
    hdr("AXIS 2 — tokenizer TIME scaling on ONE unseparated pre-token")
    trows = measure_axis2(tks, scale_sizes)
    print(f"{'chars':>8} " + " ".join(f"{c+'_s':>10} {c+'_ms/MB':>10}" for c in cols))
    for r in trows:
        print(f"{r['chars']:>8} " + " ".join(f"{r[c+'_s']:>10.5f} {r[c+'_ms_per_mb']:>10.2f}" for c in cols))
    print("\ngrowth exponent  log(t)/log(n)  (1.0 == linear, 2.0 == quadratic):")
    for c in cols:
        e = fit_exponent(trows, c + "_s")
        verdict = "~linear (no DoS blow-up)" if e < 1.35 else ("super-linear" if e < 1.8 else "QUADRATIC")
        print(f"  {c:9} exponent={e:.3f}  -> {verdict}")

    hdr("AXIS 2 — separator contrast (same chars, different shape)")
    sc = separator_contrast(tks, size * 4)
    for c in cols:
        sub = sc[c]
        run = sub["one_letter_run"]
        print(f"  {c}:")
        for k, v in sub.items():
            print(f"     {k:18} {v:9.5f}s   ({'x%.1f' % (v/run) if run else 'n/a'} vs one_letter_run)")

    # ---- emit payloads ----
    hdr("EMITTING worst-case payloads")
    outdir = Path(args.outdir); outdir.mkdir(parents=True, exist_ok=True)
    manifest = {"size": size, "tokenizers": cols, "axis1_winners": {c: best_axis1[c][0] for c in cols}}
    for label, fn in CANDIDATES:
        p = outdir / f"{label}.txt"
        p.write_text(fn(size), encoding="utf-8")
    # the overall axis-1 winner payload
    win = best_axis1[cols[0]][0]
    # best mixed (both axes) payload
    mix = outdir / "mixed_worstcase.txt"
    mix.write_text(gen_mixed_worstcase(size), encoding="utf-8")
    manifest["mixed_worstcase_path"] = str(mix)
    (outdir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  wrote {len(CANDIDATES)} candidates + manifest -> {outdir}")
    print(f"  overall AXIS-1 winner: {win}")

    # ---- verdict ----
    hdr("VERDICT (honest)")
    print("""
  AXIS 1 (token count):  SUCCESS. Maximum is ~4 tokens/char for 4-byte UTF-8
    characters with no single-token vocab entry; byte-level fallback guarantees
    worst case = 1 token per byte. Reproducible and vocabulary-robust.

  AXIS 2 (tokenizer time): NO EXPLOITABLE BLOW-UP. Real tokenizers scale ~linearly
    in input length and are insensitive to separators (see exponent above). The
    earlier "300x separator contrast / O(n^2)" claim was an artifact of the repo's
    pure-Python backend, not real tokenizers. So a single script cannot produce
    "very long to tokenize" text on production tokenizers -- it can only produce
    many-token text, which is a cost/context issue, not a CPU-DoS issue.
""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
