# Stressing LLMs

Generate C binaries with long, configurable symbol names and a seed-based XOR decryption routine.

This repo is for static-analysis testing, reverse-engineering practice, and evaluating how LLM-assisted workflows degrade under code-complexity and tokenization pressure.

- **Introductory blog post:**
  <https://hooked-on-mnemonics.blogspot.com/2026/05/stressing-llms-triage-stage.html>

- **Local Model Results**
  <https://alexander-hanel.github.io/StressingLLMs/>

- **OpenCode Model Results**
  <https://alexander-hanel.github.io/StressingLLMs/opencode.html>

- **Tokenization**
  <https://alexander-hanel.github.io/StressingLLMs/tokens.html>


**Tokenization experiments:** [tokenization-repro/](tokenization-repro/) contains a standalone set of
Python examples, dependencies, tests, and tokenizer data for comparing token counts across ASCII
and Unicode inputs. See its [README](tokenization-repro/README.md) for setup and
[manual](tokenization-repro/MANUAL.md) for commands and expected results. Note: I still need to do validation on a seperate machine. 

## Overview

`gen_fixture.py` generates a C program that:

- creates a large number of uniquely named functions
- uses per-round constants, either sequential or deterministic-random
- derives a keystream from a seed and those functions
- embeds an encrypted string into the binary
- decrypts and prints the original string at runtime

The Python implementation mirrors the generated C logic, so encryption and decryption stay consistent between the generator and the emitted C.

## Quick Start

### Generate a C file from a plaintext message:

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef \
  --rounds 1024 \
  --message "Hello, World" \
  --out fixture.c
```

### Compile:

```bash
gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline -std=c11 fixture.c -o fixture.exe
```

### Run:

```bash
./fixture.exe
```

**Expected output:**

```text
Hello, World
```

## Two-Step Mode

This mode separates encryption from code generation.

### Step 1: Encrypt

```bash
python3 gen_fixture.py encrypt --seed 0xdeadbeef --rounds 1024 --message "Secret"
```

This prints:

- a C-style byte array
- a hex string representing the encrypted data
- the generated symbol prefix length

### Step 2: Generate from encrypted data

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef \
  --rounds 1024 \
  --encrypted-hex <hex_here> \
  --out fixture.c
```

Compile and run as usual.

## Parameters

| Argument | Description |
| --- | --- |
| `--seed` | 32-bit seed used for key derivation |
| `--rounds` | Number of generated functions; accepts large values, but compile time and binary size grow quickly |
| `--message` | Plaintext string to embed |
| `--encrypted-hex` | Pre-encrypted byte string in hex |
| `--const-mode` | `rand` (default) or `seq` |
| `--const-seed` | Seed for deterministic random constants |
| `--symbol-len` | Base prefix length for generated symbols; minimum `16` |
| `--symbol-pad` | Extra repeated padding appended to generated symbols |
| `--symbol-prefix` | Custom symbol prefix; invalid identifier characters become underscores |
| `--out` | Output C file name for `generate` |
| `--exe` | Executable name shown in the printed `gcc` command for `generate` |

Exactly one of `--message` or `--encrypted-hex` must be passed to `generate`.

## Symbol Configuration

Generated symbol names are controlled with:

- `--symbol-len`: base length of the generated prefix
- `--symbol-pad`: repeated padding to make symbols even longer
- `--symbol-prefix`: fully custom prefix

These knobs are the main mechanism for the token-inflation side of the experiments.

**Example:**

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef \
  --rounds 1024 \
  --symbol-len 512 \
  --symbol-pad 128 \
  --message "Hello, World" \
  --out fixture.c
```

## Constant Generation Modes

- `rand` (default): deterministic random constants derived from `--const-seed`
- `seq`: predictable incremental constants of the form `0x9E3779B9 + i`

`rand` is generally the better default if you want less regular-looking disassembly.

## Notes

- The encryption scheme is XOR-based and not cryptographically secure.
- Large `--rounds` values can dramatically increase compile time and binary size.
- `-g3 -gdwarf-5` preserves symbol names and debug metadata for tools like Ghidra and IDA.
- All parameters must match between encryption and generation for correct output.
