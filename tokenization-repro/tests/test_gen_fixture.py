#!/usr/bin/env python3
"""
Tests for gen_fixture.py — focused on the REAL end-to-end contract: the generated
C file must compile and, when run, print back the exact plaintext that was
encrypted into it.

No pytest is available offline, so this is a self-contained stdlib runner:

    python3 tests/test_gen_fixture.py            # run all tests
    python3 tests/test_gen_fixture.py -v         # verbose (show each step)
    python3 tests/test_gen_fixture.py -k decrypt # filter by name substring

Coverage:
  A. COMPILE + DECRYPT CONTRACT (the main thing you asked for)
     - plaintext of varied length/charset survives generate -> gcc -> run
     - the two-step path (encrypt -> --encrypted-hex -> generate -> run) agrees
     - byte-for-byte equality with the requested message
  B. DETERMINISM
     - same seed/rounds/message => byte-identical C file
     - different seed => different ciphertext (non-degenerate)
  C. FIXTURE-LEVEL INVARIANTS
     - symbol names actually appear in the compiled binary (nm lookup)
     - --symbol-len / --symbol-pad / --symbol-prefix lengths behave as documented
     - --segment-aligned produces whole-segment names that still compile
  D. EDGE CASES / HARDENING (the fixes made this session)
     - Unicode prefix is sanitized to ASCII and still compiles
     - huge --rounds is rejected (practical bound)
     - empty message, UTF-8 message, very long message
     - header build command matches --out/--exe
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GEN = REPO / "gen_fixture.py"
TOKENIZER_A = REPO / "tokenizer-data" / "model-a.json"
GCC = shutil.which("gcc")
NM = shutil.which("nm")

VERBOSE = False
_TMP = None


# --------------------------------------------------------------------------- #
# tiny test harness
# --------------------------------------------------------------------------- #

_TESTS: list[tuple[str, callable]] = []
_FAILS: list[tuple[str, str]] = []


def test(fn):
    _TESTS.append((fn.__name__, fn))
    return fn


class AssertionFail(Exception):
    pass


def eq(got, want, what=""):
    if got != want:
        raise AssertionFail(f"{what}: got {got!r}, want {want!r}")


def truthy(cond, what=""):
    if not cond:
        raise AssertionFail(what or "expected truthy")


def run(argv: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    if VERBOSE:
        print("      $ " + " ".join(argv))
    p = subprocess.run(argv, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise AssertionFail(
            f"command failed ({p.returncode}): {' '.join(argv)}\n"
            f"--- stdout ---\n{p.stdout}\n--- stderr ---\n{p.stderr}"
        )
    return p


def tmpdir() -> Path:
    global _TMP
    if _TMP is None:
        _TMP = Path(tempfile.mkdtemp(prefix="genfx-test-"))
    return _TMP


def gen_c(out: Path, *, seed="0xdeadbeef", rounds=3, message=None,
          encrypted_hex=None, symbol_len=64, symbol_pad=0,
          symbol_prefix=None, segment_aligned=False, diverse_body=False,
          unicode_body=False, allow_unicode=False, exe=None,
          const_mode="rand", const_seed="0xC001D00D") -> str:
    """Invoke gen_fixture.py generate and return its stdout."""
    argv = [sys.executable, str(GEN), "generate",
            "--seed", str(seed), "--rounds", str(rounds),
            "--const-mode", const_mode, "--const-seed", str(const_seed),
            "--symbol-len", str(symbol_len), "--symbol-pad", str(symbol_pad),
            "--out", str(out)]
    if message is not None:
        argv += ["--message", message]
    if encrypted_hex is not None:
        argv += ["--encrypted-hex", encrypted_hex]
    if symbol_prefix is not None:
        argv += ["--symbol-prefix", symbol_prefix]
    if segment_aligned:
        argv += ["--segment-aligned"]
    if diverse_body:
        argv += ["--symbol-diverse-body"]
    if unicode_body:
        argv += ["--symbol-unicode-body"]
    if allow_unicode:
        argv += ["--allow-unicode-symbols"]
    if exe is not None:
        argv += ["--exe", exe]
    return run(argv).stdout


def compile_and_run(c_path: Path, *, flags=("-O0", "-std=c11")) -> str:
    """Compile the C fixture with gcc and run it; return stdout."""
    if not GCC:
        raise AssertionFail("gcc not found on PATH")
    exe = c_path.with_suffix(".bin")
    run([GCC, *flags, str(c_path), "-o", str(exe)])
    p = run([str(exe)])
    return p.stdout


def encrypt_hex(message: str, seed="0xdeadbeef", rounds=3) -> str:
    """Call gen_fixture.py encrypt and return the bare hex line."""
    out = run([sys.executable, str(GEN), "encrypt",
               "--seed", str(seed), "--rounds", str(rounds),
               "--message", message]).stdout
    lines = [l for l in out.splitlines() if l.strip()]
    # encrypt prints: byte-array, hex, symbol_prefix_length
    for l in lines:
        s = l.strip()
        if s and all(ch in "0123456789abcdefABCDEF" for ch in s) and len(s) % 2 == 0:
            return s
    raise AssertionFail(f"could not find hex line in encrypt output:\n{out}")


# --------------------------------------------------------------------------- #
# A. compile + decrypt contract  (the main ask)
# --------------------------------------------------------------------------- #

@test
def test_basic_decrypt_roundtrip():
    """The canonical case: message survives generate -> gcc -> run, exactly."""
    msg = "PLAN_AUDIT_REPETITION_STRESS_OK"
    out = tmpdir() / "basic.c"
    gen_c(out, message=msg)
    got = compile_and_run(out)
    eq(got, msg + "\n", "stdout")


@test
def test_decrypt_matches_message_byte_for_byte():
    """No trailing junk, no truncation: the printed string equals the message."""
    msg = "decrypt-me-exactly"
    out = tmpdir() / "exact.c"
    gen_c(out, message=msg)
    got = compile_and_run(out).rstrip("\n")
    eq(got, msg, "decrypted string")


@test
def test_two_step_encrypt_then_generate():
    """encrypt -> --encrypted-hex -> generate must decode to the same plaintext."""
    msg = "ROUNDTRIP_VIA_HEX"
    hx = encrypt_hex(msg)
    out = tmpdir() / "twostep.c"
    gen_c(out, message=None, encrypted_hex=hx)
    got = compile_and_run(out).rstrip("\n")
    eq(got, msg, "decrypted string (two-step path)")


@test
def test_two_step_agrees_with_direct_generate():
    """The two-step path and --message path must embed the SAME ciphertext."""
    msg = "SAME_CIPHERTEXT"
    hx = encrypt_hex(msg)
    direct = tmpdir() / "direct.c"
    stepped = tmpdir() / "stepped.c"
    gen_c(direct, message=msg)
    gen_c(stepped, message=None, encrypted_hex=hx)

    def ciphertext(p: Path) -> str:
        for line in p.read_text().splitlines():
            if "encrypted[]" in line:
                return line.strip()
        raise AssertionFail(f"no encrypted[] line in {p}")

    eq(ciphertext(direct), ciphertext(stepped), "embedded ciphertext line")


@test
def test_varied_messages_and_rounds():
    """Different messages and round counts all decrypt correctly."""
    cases = [
        ("short", 1),
        ("a", 1),
        ("x" * 200, 1),
        ("multi_round_msg", 5),
        ("under_score__dashes-and.dots", 4),
    ]
    for msg, rounds in cases:
        out = tmpdir() / f"vary_{len(msg)}_{rounds}.c"
        gen_c(out, rounds=rounds, message=msg)
        got = compile_and_run(out).rstrip("\n")
        eq(got, msg, f"msg={msg!r} rounds={rounds}")


@test
def test_utf8_message():
    """Non-ASCII plaintext is encrypted as UTF-8 bytes and decrypted intact."""
    msg = "héllo-世界-😀"
    out = tmpdir() / "utf8.c"
    gen_c(out, message=msg)
    got = compile_and_run(out, flags=("-O0", "-std=c11")).rstrip("\n")
    eq(got, msg, "utf8 decrypted string")


@test
def test_empty_message():
    """An empty message should compile and print just a newline."""
    out = tmpdir() / "empty.c"
    gen_c(out, message="")
    got = compile_and_run(out)
    eq(got, "\n", "stdout for empty message")


@test
def test_long_message():
    """A long plaintext must round-trip (exercises the byte-array emitter)."""
    msg = "LONG_" + "ABC123_" * 100
    out = tmpdir() / "long.c"
    gen_c(out, message=msg)
    got = compile_and_run(out).rstrip("\n")
    eq(got, msg, "long decrypted string")


# --------------------------------------------------------------------------- #
# B. determinism
# --------------------------------------------------------------------------- #

@test
def test_deterministic_output():
    """Same inputs => identical generated CODE (fixtures are reproducible).

    NOTE: the header comment intentionally embeds the --out/--exe paths, so two
    runs with different filenames differ in those comment lines. We therefore
    compare everything AFTER the header (the actual C code), which is what
    determinism means here.
    """
    a = tmpdir() / "det_a.c"
    b = tmpdir() / "det_b.c"
    gen_c(a, seed="0xdeadbeef", rounds=4, message="DET")
    gen_c(b, seed="0xdeadbeef", rounds=4, message="DET")

    def body(p: Path) -> str:
        text = p.read_text()
        return text[text.index("#include"):]  # drop header comments

    eq(body(a), body(b), "identical generated C body")
    # and the ciphertext line specifically must match
    ca = next(l for l in a.read_text().splitlines() if "encrypted[]" in l)
    cb = next(l for l in b.read_text().splitlines() if "encrypted[]" in l)
    eq(ca, cb, "identical ciphertext")


@test
def test_seed_changes_ciphertext():
    """A different seed must change the embedded ciphertext (not a constant)."""
    def cipher(p: Path) -> str:
        return next(l for l in p.read_text().splitlines() if "encrypted[]" in l)
    a = tmpdir() / "seed_a.c"
    b = tmpdir() / "seed_b.c"
    gen_c(a, seed="0x11111111", rounds=2, message="SEEDED")
    gen_c(b, seed="0x22222222", rounds=2, message="SEEDED")
    truthy(cipher(a) != cipher(b), "ciphertext should differ across seeds")
    # both must still decrypt to the same plaintext
    eq(compile_and_run(a).rstrip("\n"), "SEEDED")
    eq(compile_and_run(b).rstrip("\n"), "SEEDED")


# --------------------------------------------------------------------------- #
# C. fixture invariants
# --------------------------------------------------------------------------- #

@test
def test_symbols_present_in_binary():
    """The generated long symbol names must survive compilation into the binary."""
    out = tmpdir() / "symbols.c"
    gen_c(out, rounds=2, message="SYM")
    exe = out.with_suffix(".bin")
    run([GCC, "-O0", "-std=c11", str(out), "-o", str(exe)])
    if not NM:
        return  # skip silently if nm unavailable
    syms = run([NM, str(exe)]).stdout
    truthy("TokenizerBench" in syms, "expected generated symbol prefix in nm output")


@test
def test_symbol_len_exact_default():
    """Default truncation is exact: prefix length == --symbol-len."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    eq(len(g.build_prefix(160)), 160, "len(symbol_len=160)")
    eq(len(g.build_prefix(4096)), 4096, "len(symbol_len=4096)")


@test
def test_symbol_pad_is_additive():
    """--symbol-pad appends '_Pad'+N X's on top of the base length."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    base = len(g.build_prefix(160))
    pr, _ = g.build_names(160, 64)
    eq(len(pr), base + 4 + 64, "effective prefix length with pad=64")


@test
def test_segment_aligned_names_compile():
    """--segment-aligned yields whole-segment names that still compile + decrypt."""
    out = tmpdir() / "aligned.c"
    gen_c(out, symbol_len=300, symbol_pad=16, segment_aligned=True, message="ALIGNED")
    got = compile_and_run(out).rstrip("\n")
    eq(got, "ALIGNED", "aligned decrypted string")
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    p = g.build_prefix(300, segment_aligned=True)
    truthy(len(p) <= 300, f"aligned prefix must not exceed requested (got {len(p)})")
    # whole-segment property: it must not end mid-segment (next source char is '_')
    full = g.DEFAULT_PREFIX_BASE + g.DEFAULT_PREFIX_CHUNK * 10
    nxt = full[len(p)] if len(p) < len(full) else ""
    truthy(p.endswith("_") or nxt == "_",
           f"aligned prefix ended mid-segment: {p!r} (next={nxt!r})")


@test
def test_custom_prefix_appears():
    """--symbol-prefix is reflected in the generated type/function names."""
    out = tmpdir() / "custom.c"
    gen_c(out, symbol_prefix="MyCustomPrefix", message="CUSTOM")
    text = out.read_text()
    truthy("MyCustomPrefix" in text, "custom prefix in C source")
    eq(compile_and_run(out).rstrip("\n"), "CUSTOM", "custom decrypted string")


# --------------------------------------------------------------------------- #
# D. edge cases / hardening (from this session's fixes)
# --------------------------------------------------------------------------- #

@test
def test_unicode_prefix_sanitized_ascii_and_compiles():
    """A Unicode --symbol-prefix is sanitized to ASCII and the C still compiles."""
    out = tmpdir() / "uniprefix.c"
    gen_c(out, symbol_prefix="héllo_世界_😀", message="UNI")
    text = out.read_text()
    truthy(all(ord(c) < 128 for c in text), "file should contain no non-ASCII bytes")
    eq(compile_and_run(out).rstrip("\n"), "UNI", "unicode-prefix decrypted string")


@test
def test_huge_rounds_rejected():
    """--rounds beyond the practical bound must fail fast, not emit GBs."""
    out = tmpdir() / "huge.c"
    p = run([sys.executable, str(GEN), "generate",
             "--seed", "1", "--rounds", "1000000000",
             "--message", "X", "--out", str(out)], check=False)
    truthy(p.returncode != 0, "expected non-zero exit for absurd --rounds")
    truthy("rounds" in (p.stdout + p.stderr).lower(), "error should mention --rounds")


@test
def test_max_allowed_rounds_ok():
    """The documented maximum (100000) is accepted... but we only build a small one."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    g.validate_rounds(g.MAX_ROUNDS)  # must not raise


@test
def test_header_build_command_matches_out_and_exe():
    """The in-file 'Suggested build' must reference the real --out/--exe."""
    out = tmpdir() / "hdr.c"
    gen_c(out, exe="myprog", message="HDR")
    line = next(l for l in out.read_text().splitlines() if l.strip().startswith("//   gcc"))
    truthy(str(out) in line, f"--out missing from header: {line!r}")
    truthy("myprog" in line, f"--exe missing from header: {line!r}")


@test
def test_encrypted_hex_requires_even_digits():
    """Malformed --encrypted-hex (odd length) must be rejected."""
    out = tmpdir() / "badhex.c"
    p = run([sys.executable, str(GEN), "generate",
             "--seed", "1", "--rounds", "1",
             "--encrypted-hex", "abc", "--out", str(out)], check=False)
    truthy(p.returncode != 0, "odd-length hex should be rejected")


@test
def test_message_and_hex_mutually_exclusive():
    """Supplying both --message and --encrypted-hex must error."""
    out = tmpdir() / "both.c"
    p = run([sys.executable, str(GEN), "generate",
             "--seed", "1", "--rounds", "1",
             "--message", "X", "--encrypted-hex", "aabb", "--out", str(out)],
            check=False)
    truthy(p.returncode != 0, "both inputs should be rejected")


# --------------------------------------------------------------------------- #
# E. diverse-body mode (the fix for "varying tail doesn't help")
# --------------------------------------------------------------------------- #

@test
def test_diverse_body_compiles_and_decrypts():
    """--symbol-diverse-body must still produce a valid, runnable fixture."""
    out = tmpdir() / "diverse.c"
    gen_c(out, symbol_len=256, diverse_body=True, message="DIVERSE_OK")
    got = compile_and_run(out).rstrip("\n")
    eq(got, "DIVERSE_OK", "diverse-body decrypted string")


@test
def test_diverse_body_is_non_recurring():
    """The diverse body must be built from DISTINCT segments (no long repeat)."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    body = g.build_diverse_body(256, seed=0xDEADBEEF)
    segs = body.split("_")
    truthy(len(segs) > 5, f"expected many segments, got {len(segs)}")
    uniq = len(set(segs)) / len(segs)
    truthy(uniq > 0.75, f"segments should be mostly distinct, unique_ratio={uniq:.2f}")


@test
def test_diverse_body_is_deterministic():
    """Same seed => same body; different seed => different body."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    a = g.build_diverse_body(256, seed=0xDEADBEEF)
    b = g.build_diverse_body(256, seed=0xDEADBEEF)
    c = g.build_diverse_body(256, seed=0x12345678)
    eq(a, b, "same seed should give identical body")
    truthy(a != c, "different seed should give a different body")


@test
def test_diverse_body_is_portable_ascii_identifier():
    """Diverse body must be plain ASCII and a valid (non-reserved) C identifier."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    d = g.build_diverse_body(300, seed=7)
    truthy(all(ord(ch) < 128 for ch in d), "must be ASCII")
    truthy(all(ch.isalnum() or ch == "_" for ch in d), "must be identifier chars")
    truthy(d and (d[0].isalpha() or d[0] == "_"), "must not start with a digit")
    truthy(not (d.startswith("__") or (len(d) > 1 and d[0] == "_" and d[1].isupper())),
           "must not be a reserved identifier")


@test
def test_diverse_body_costs_more_than_repetitive():
    """The whole point: diverse body should cost MORE tokens/char than repetitive.

    Uses the real tokenizer if the venv is importable; skips silently otherwise.
    """
    try:
        from tokenizers import Tokenizer  # type: ignore
    except Exception:
        return  # tokenizers not available in this interpreter -> skip
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    if not TOKENIZER_A.is_file():
        return
    tk = Tokenizer.from_file(str(TOKENIZER_A))

    def tpc(s):
        return len(tk.encode(s).ids) / len(s)

    for sl in (128, 256, 512):
        rep = g.build_prefix(sl)
        div = g.build_diverse_body(sl, seed=0xDEADBEEF)
        truthy(tpc(div) > tpc(rep) * 1.2,
               f"len={sl}: diverse tpc {tpc(div):.3f} should exceed repetitive {tpc(rep):.3f} by >20%")


@test
def test_diverse_body_ignored_when_user_prefix_given():
    """--symbol-prefix wins over --symbol-diverse-body (documented behaviour)."""
    out = tmpdir() / "div_user.c"
    gen_c(out, symbol_prefix="ExplicitName", diverse_body=True, message="X")
    truthy("ExplicitName" in out.read_text(), "explicit prefix should be used")
    eq(compile_and_run(out).rstrip("\n"), "X")


# --------------------------------------------------------------------------- #
# F. hardest-case mode (--symbol-unicode-body)
# --------------------------------------------------------------------------- #

@test
def test_unicode_body_compiles_and_decrypts_c11():
    """The hardest mode must still produce a valid, runnable fixture under C11."""
    out = tmpdir() / "hardest.c"
    gen_c(out, symbol_len=128, unicode_body=True, message="HARDEST_OK")
    got = compile_and_run(out, flags=("-O0", "-std=c11")).rstrip("\n")
    eq(got, "HARDEST_OK", "unicode-body decrypted string")


@test
def test_unicode_body_is_high_plane():
    """Body characters must all be in the OOV high-plane range U+30000..U+303FF."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    body = g.build_unicode_body(256, seed=0xDEADBEEF)
    eq(len(body), 256, "requested length")
    truthy(all(0x30000 <= ord(c) <= 0x303FF for c in body),
           "all chars should be in U+30000..U+303FF")
    truthy(len(set(body)) > 200, f"should be diverse, distinct={len(set(body))}")


@test
def test_unicode_body_is_4_bytes_per_char():
    """Every character must be 4 UTF-8 bytes (the source of the 4 tokens/char cost)."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    body = g.build_unicode_body(100, seed=1)
    eq(len(body.encode("utf-8")), 400, "100 chars x 4 bytes")


@test
def test_unicode_body_is_deterministic():
    """Same seed => same body (reproducible fixtures)."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    eq(g.build_unicode_body(64, seed=7), g.build_unicode_body(64, seed=7), "same seed")
    truthy(g.build_unicode_body(64, seed=7) != g.build_unicode_body(64, seed=8),
           "different seed should differ")


@test
def test_unicode_body_rejected_by_c89():
    """Documented constraint: C89 rejects these identifiers (raw multi-byte bytes)."""
    if not GCC:
        return
    out = tmpdir() / "hardest_c89.c"
    gen_c(out, symbol_len=64, unicode_body=True, message="X")
    p = run([GCC, "-std=c89", "-fsyntax-only", str(out)], check=False)
    truthy(p.returncode != 0, "C89 should reject a Unicode identifier")


@test
def test_unicode_body_costs_more_than_diverse():
    """The whole point: unicode body should be far more expensive than diverse.

    Uses the real tokenizer; skips silently if `tokenizers` is unavailable.
    """
    try:
        from tokenizers import Tokenizer  # type: ignore
    except Exception:
        return
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    if not TOKENIZER_A.is_file():
        return
    tk = Tokenizer.from_file(str(TOKENIZER_A))

    def tpc(s):
        return len(tk.encode(s).ids) / len(s)

    for n in (64, 128):
        uni = g.build_unicode_body(n, seed=0xDEADBEEF)
        div = g.build_diverse_body(n, seed=0xDEADBEEF)
        truthy(tpc(uni) > tpc(div) * 3,
               f"n={n}: unicode tpc {tpc(uni):.3f} should far exceed diverse {tpc(div):.3f}")


@test
def test_allow_unicode_symbols_keeps_letters():
    """--allow-unicode-symbols must keep non-ASCII letters instead of mapping to _."""
    sys.path.insert(0, str(REPO))
    import gen_fixture as g
    eq(g.sanitize_identifier("héllo", keep_unicode=True), "héllo", "unicode letters preserved")
    eq(g.sanitize_identifier("héllo"), "h_llo", "default still ASCII-only")


@test
def test_unicode_body_ignored_when_user_prefix_given():
    """--symbol-prefix wins over --symbol-unicode-body."""
    out = tmpdir() / "uni_user.c"
    gen_c(out, symbol_prefix="ExplicitName", unicode_body=True, message="X")
    truthy("ExplicitName" in out.read_text(encoding="utf-8"), "explicit prefix used")


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #

def main() -> int:
    global VERBOSE
    ap = argparse.ArgumentParser(description="Run gen_fixture.py tests")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("-k", "--filter", default=None, help="substring filter on test name")
    args = ap.parse_args()
    VERBOSE = args.verbose

    if not GCC:
        print("FATAL: gcc is required for the compile+decrypt tests.", file=sys.stderr)
        return 2

    tests = _TESTS
    if args.filter:
        tests = [(n, f) for n, f in tests if args.filter in n]
    if not tests:
        print(f"no tests matched filter {args.filter!r}", file=sys.stderr)
        return 2

    print(f"running {len(tests)} tests (gcc={shutil.which('gcc')})")
    passed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionFail as e:
            _FAILS.append((name, str(e)))
            print(f"  FAIL {name}\n       {e}")
        except Exception as e:  # unexpected error
            _FAILS.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERROR {name}\n       {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"  ok   {name}" if not VERBOSE else f"  ok   {name}")

    print(f"\n{passed}/{len(tests)} passed, {len(_FAILS)} failed")
    if _FAILS:
        print("\nfailures:")
        for n, e in _FAILS:
            print(f"  - {n}: {e}")
    return 1 if _FAILS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        if _TMP and _TMP.exists():
            shutil.rmtree(_TMP, ignore_errors=True)
