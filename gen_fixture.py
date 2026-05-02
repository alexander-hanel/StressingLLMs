#!/usr/bin/env python3
import argparse
import random
import shlex
from ctypes import c_uint32, c_uint64
from dataclasses import dataclass
from pathlib import Path

MAX_ROUNDS = 0xFFFFFFFFF

DEFAULT_PREFIX_BASE = "TokenizerBench__"
DEFAULT_PREFIX_CHUNK = (
    "DemangleLike__std__basic_string__char__std__char_traits__char__"
    "std__allocator__char__vector__pair__basic_string__int__"
)


@dataclass(frozen=True)
class RoundSpec:
    variant: int
    c0: int
    c1: int
    c2: int
    rot: int


def u32(x: int) -> int:
    return c_uint32(x).value


def u64(x: int) -> int:
    return c_uint64(x).value


def parse_u32(s: str) -> int:
    v = int(s, 0)
    if not 0 <= v <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("value must be 0..0xffffffff")
    return v


def xorshift32(x: int) -> int:
    x = c_uint32(x)
    x.value ^= u32(x.value << 13)
    x.value ^= x.value >> 17
    x.value ^= u32(x.value << 5)
    return x.value


def rotl64(x: int, n: int) -> int:
    return u64((x << n) | (x >> (64 - n)))


def rotr64(x: int, n: int) -> int:
    return u64((x >> n) | (x << (64 - n)))


def sanitize_identifier(s: str) -> str:
    out = []
    for ch in s:
        if ch.isalnum() or ch == "_":
            out.append(ch)
        else:
            out.append("_")

    ident = "".join(out) or "GeneratedSymbol"
    if ident[0].isdigit():
        ident = "_" + ident
    return ident


def build_prefix(symbol_len: int, user_prefix: str | None = None) -> str:
    if user_prefix:
        return sanitize_identifier(user_prefix)

    prefix = DEFAULT_PREFIX_BASE
    while len(prefix) < symbol_len:
        prefix += DEFAULT_PREFIX_CHUNK
    return sanitize_identifier(prefix[:symbol_len])


def build_names(symbol_len: int, symbol_pad: int, user_prefix: str | None = None) -> tuple[str, str]:
    prefix = build_prefix(symbol_len, user_prefix)
    if symbol_pad > 0:
        prefix = f"{prefix}_Pad{'X' * symbol_pad}"

    type_name = f"{prefix}_Type__LongRecord__With__Lots__Of__Nested__Like__Tokens"
    return prefix, type_name


def base_constants(rounds: int, mode: str, const_seed: int) -> list[int]:
    if mode == "seq":
        return [u32(0x9E3779B9 + i) for i in range(rounds)]
    rng = random.Random(const_seed)
    return [rng.getrandbits(32) for _ in range(rounds)]


def make_round_specs(rounds: int, mode: str, const_seed: int) -> list[RoundSpec]:
    bases = base_constants(rounds, mode, const_seed)
    rng = random.Random((const_seed ^ 0xA5B35705) & 0xFFFFFFFF)

    specs: list[RoundSpec] = []
    for c0 in bases:
        specs.append(
            RoundSpec(
                variant=rng.randrange(0, 5),
                c0=u32(c0),
                c1=u32(rng.getrandbits(32)),
                c2=u32(rng.getrandbits(32)),
                rot=rng.randrange(3, 29),
            )
        )
    return specs


def round_func_py(a: int, b: int, c_field: int, spec: RoundSpec) -> tuple[int, int, int, int]:
    c0, c1, c2, rot = spec.c0, spec.c1, spec.c2, spec.rot

    if spec.variant == 0:
        m = xorshift32(c0 ^ u32(a))
        a = u64(a ^ u64((c0 << 32) | m))
        b = u64(b + u64(a ^ u64(c_field + c1)))
        c_field = rotl64(c_field ^ c2, rot)

    elif spec.variant == 1:
        m = xorshift32(c1 ^ u32(b))
        b = u64(b ^ u64((m << 32) | c0))
        c_field = u64(c_field + u64(b ^ c2))
        a = rotr64(a + u64(c1), rot)

    elif spec.variant == 2:
        t = u64(a ^ u64(c0))
        t = rotl64(t, rot)
        a = u64(t + u64(c1))
        b = u64((b ^ a) + u64(c2))
        c_field = u64(c_field ^ u64((xorshift32(c2 ^ u32(t)) << 32) | c0))

    elif spec.variant == 3:
        m = xorshift32(c2 + u32(c_field))
        a = u64(a + u64((m << 32) | c1))
        c_field = rotr64(c_field ^ a, rot)
        b = u64(b ^ u64(u32(c0 + m)))

    else:
        m1 = xorshift32(c0 ^ c1 ^ u32(a))
        m2 = xorshift32(c2 ^ u32(b))
        a = u64(a ^ u64((m1 << 32) | m2))
        b = rotl64(b + u64(c0 ^ m2), rot)
        c_field = u64((c_field + a) ^ u64(c1 ^ c2))

    r = u64(a ^ b ^ c_field ^ c0 ^ c1 ^ c2)
    ret = u32(r ^ (r >> 32))
    return a, b, c_field, ret


def derive_state(seed: int, specs: list[RoundSpec]) -> int:
    a = u64(seed)
    b = u64(seed ^ 0x12345678)
    c_field = u64(seed + 0x9)
    s = u32(seed)

    for spec in specs:
        a, b, c_field, ret = round_func_py(a, b, c_field, spec)
        s = u32(s ^ ret)

    return xorshift32(s)


def crypt_bytes(seed: int, specs: list[RoundSpec], data: bytes) -> bytes:
    s = c_uint32(derive_state(seed, specs))
    out = bytearray()

    for b in data:
        s.value = xorshift32(s.value + 0xA5A5A5A5)
        out.append(b ^ (s.value & 0xFF))
    return bytes(out)


def c_byte_array(data: bytes) -> str:
    return ", ".join(f"0x{b:02x}" for b in data)


def func_name(prefix: str, i: int) -> str:
    return f"{prefix}_R{i}"


def gen_round_body(spec: RoundSpec) -> str:
    c0 = f"0x{spec.c0:08x}u"
    c1 = f"0x{spec.c1:08x}u"
    c2 = f"0x{spec.c2:08x}u"
    rot = spec.rot
    rrot = 64 - rot

    if spec.variant == 0:
        return f"""    uint32_t m = xorshift32({c0} ^ (uint32_t)p->a);
    p->a ^= ((uint64_t){c0} << 32) | (uint64_t)m;
    p->b += p->a ^ (p->c + (uint64_t){c1});
    p->c = ((p->c ^ (uint64_t){c2}) << {rot}) | ((p->c ^ (uint64_t){c2}) >> {rrot});"""

    if spec.variant == 1:
        return f"""    uint32_t m = xorshift32({c1} ^ (uint32_t)p->b);
    p->b ^= ((uint64_t)m << 32) | (uint64_t){c0};
    p->c += p->b ^ (uint64_t){c2};
    p->a = (p->a + (uint64_t){c1});
    p->a = (p->a >> {rot}) | (p->a << {rrot});"""

    if spec.variant == 2:
        return f"""    uint64_t t = p->a ^ (uint64_t){c0};
    t = (t << {rot}) | (t >> {rrot});
    p->a = t + (uint64_t){c1};
    p->b = (p->b ^ p->a) + (uint64_t){c2};
    p->c ^= ((uint64_t)xorshift32({c2} ^ (uint32_t)t) << 32) | (uint64_t){c0};"""

    if spec.variant == 3:
        return f"""    uint32_t m = xorshift32({c2} + (uint32_t)p->c);
    p->a += ((uint64_t)m << 32) | (uint64_t){c1};
    p->c ^= p->a;
    p->c = (p->c >> {rot}) | (p->c << {rrot});
    p->b ^= (uint64_t)({c0} + m);"""

    return f"""    uint32_t m1 = xorshift32({c0} ^ {c1} ^ (uint32_t)p->a);
    uint32_t m2 = xorshift32({c2} ^ (uint32_t)p->b);
    p->a ^= ((uint64_t)m1 << 32) | (uint64_t)m2;
    p->b += (uint64_t)({c0} ^ m2);
    p->b = (p->b << {rot}) | (p->b >> {rrot});
    p->c = (p->c + p->a) ^ (uint64_t)({c1} ^ {c2});"""


def gen_functions(prefix: str, type_name: str, specs: list[RoundSpec]) -> str:
    blocks = []
    for i, spec in enumerate(specs):
        c0 = f"0x{spec.c0:08x}u"
        c1 = f"0x{spec.c1:08x}u"
        c2 = f"0x{spec.c2:08x}u"
        blocks.append(f"""
__attribute__((used, noinline))
uint32_t {func_name(prefix, i)}({type_name} *p) {{
{gen_round_body(spec)}
    uint64_t r = p->a ^ p->b ^ p->c ^ (uint64_t){c0} ^ (uint64_t){c1} ^ (uint64_t){c2};
    return (uint32_t)(r ^ (r >> 32));
}}
""")
    return "\n".join(blocks)


def gen_calls(prefix: str, rounds: int) -> str:
    return "\n".join(f"    s ^= {func_name(prefix, i)}(&x);" for i in range(rounds))


def generate_c(seed: int, specs: list[RoundSpec], encrypted: bytes, const_mode: str, const_seed: int,
               symbol_len: int, symbol_pad: int, prefix: str, type_name: str) -> str:
    rounds = len(specs)
    return f"""// Generated CTF-style static-analysis fixture
//
// Suggested build:
//   gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline -std=c11 fixture.c -o fixture.exe
//
// seed=0x{seed:08x}
// rounds={rounds}
// const_mode={const_mode}
// const_seed=0x{const_seed:08x}
// symbol_len={symbol_len}
// symbol_pad={symbol_pad}
// generated_prefix_length={len(prefix)}
//
// Notes:
// - Per-function constants are baked into each generated function.
// - Function bodies vary by generated round variant.
// - The plaintext is stored encrypted in the binary and decrypted at runtime.

#include <stdint.h>
#include <stdio.h>
#include <stddef.h>

typedef struct {type_name} {{
    uint64_t a;
    uint64_t b;
    uint64_t c;
}} {type_name};

static uint32_t xorshift32(uint32_t x) {{
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x;
}}

{gen_functions(prefix, type_name, specs)}

__attribute__((used, noinline))
uint32_t derive_state(uint32_t seed) {{
    {type_name} x = {{
        seed,
        seed ^ 0x12345678ULL,
        seed + 0x9ULL
    }};

    uint32_t s = seed;
{gen_calls(prefix, rounds)}

    s = xorshift32(s);
    return s;
}}

int main(void) {{
    uint8_t encrypted[] = {{ {c_byte_array(encrypted)}, 0x00 }};
    uint32_t s = derive_state(0x{seed:08x});

    for (size_t i = 0; i < sizeof(encrypted) - 1; i++) {{
        s = xorshift32(s + 0xA5A5A5A5u);
        encrypted[i] ^= (uint8_t)(s & 0xffu);
    }}

    puts((const char *)encrypted);
    return 0;
}}
"""


def validate_rounds(rounds: int) -> None:
    if not 1 <= rounds <= MAX_ROUNDS:
        raise SystemExit(f"--rounds must be 1..0x{MAX_ROUNDS:x}")


def parse_hex_bytes(s: str) -> bytes:
    cleaned = (
        s.replace(" ", "")
        .replace(",", "")
        .replace("0x", "")
        .replace("0X", "")
        .replace("\\x", "")
        .replace("\\X", "")
    )
    if len(cleaned) % 2 != 0:
        raise argparse.ArgumentTypeError("encrypted hex must contain an even number of hex digits")
    return bytes.fromhex(cleaned)


def gcc_command(out_c: str, exe: str) -> str:
    return " ".join(
        shlex.quote(x)
        for x in [
            "gcc",
            "-O0",
            "-g3",
            "-gdwarf-5",
            "-fno-omit-frame-pointer",
            "-fno-inline",
            "-std=c11",
            out_c,
            "-o",
            exe,
        ]
    )


def default_exe_for(out_c: str) -> str:
    return str(Path(out_c).with_suffix(".exe"))


def add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--seed", required=True, type=parse_u32, help="32-bit seed, e.g. 0xdeadbeef")
    p.add_argument("--rounds", required=True, type=lambda x: int(x, 0), help=f"1..0x{MAX_ROUNDS:x}")
    p.add_argument(
        "--const-mode",
        choices=("seq", "rand"),
        default="rand",
        help="rand uses deterministic random 32-bit constants; seq uses 0x9e3779b9+i",
    )
    p.add_argument("--const-seed", type=parse_u32, default=0xC001D00D, help="seed for --const-mode rand")
    p.add_argument("--symbol-len", type=int, default=160, help="approximate base prefix length for generated symbols")
    p.add_argument("--symbol-pad", type=int, default=0, help="extra repeated padding added to generated symbols")
    p.add_argument("--symbol-prefix", help="custom symbol prefix; invalid identifier chars become underscores")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a C static-analysis fixture with randomized per-function code and seed-derived XOR decoding."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    enc = sub.add_parser("encrypt", help="Encrypt a plaintext string and print byte array + hex")
    add_common(enc)
    enc.add_argument("--message", required=True)

    gen = sub.add_parser("generate", help="Generate C file from plaintext or encrypted bytes")
    add_common(gen)
    gen.add_argument("--message", help="plaintext message to encrypt into the C file")
    gen.add_argument("--encrypted-hex", type=parse_hex_bytes, help="encrypted bytes as hex, e.g. 3a917f")
    gen.add_argument("--out", default="fixture.c")
    gen.add_argument("--exe", help="executable name to show in the printed gcc command")

    args = parser.parse_args()
    validate_rounds(args.rounds)

    if args.symbol_len < 16:
        raise SystemExit("--symbol-len must be at least 16")
    if args.symbol_pad < 0:
        raise SystemExit("--symbol-pad must be >= 0")

    prefix, type_name = build_names(args.symbol_len, args.symbol_pad, args.symbol_prefix)
    specs = make_round_specs(args.rounds, args.const_mode, args.const_seed)

    if args.cmd == "encrypt":
        encrypted = crypt_bytes(args.seed, specs, args.message.encode("utf-8"))
        print(c_byte_array(encrypted))
        print(encrypted.hex())
        print(f"symbol_prefix_length={len(prefix)}")
        return

    if (args.message is None) == (args.encrypted_hex is None):
        raise SystemExit("Use exactly one of --message or --encrypted-hex")

    encrypted = crypt_bytes(args.seed, specs, args.message.encode("utf-8")) if args.message is not None else args.encrypted_hex

    Path(args.out).write_text(
        generate_c(
            seed=args.seed,
            specs=specs,
            encrypted=encrypted,
            const_mode=args.const_mode,
            const_seed=args.const_seed,
            symbol_len=args.symbol_len,
            symbol_pad=args.symbol_pad,
            prefix=prefix,
            type_name=type_name,
        ),
        encoding="utf-8",
    )

    exe = args.exe or default_exe_for(args.out)
    print(f"Wrote {args.out}")
    print(f"Generated symbol prefix length: {len(prefix)}")
    print("Compile with:")
    print(gcc_command(args.out, exe))


if __name__ == "__main__":
    main()
