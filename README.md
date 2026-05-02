# Stressing LLMs

Generate C binaries with long, configurable symbol names and a seed-based XOR decryption routine.  
This tool is intended for static analysis testing, reverse engineering practice, and CTF-style challenges for evaluating LLMs. 

The goal of this project is to better understand LLMs under stress. See the following introductory blog post. 

https://hooked-on-mnemonics.blogspot.com/2026/05/stressing-llms-triage-stage.html

Note:
This is part of a series of weekend projects in which I vibe code tooling to better understand LLMs/AI-Agents.


## Overview

This script generates a C program that:

- Creates a large number of uniquely named functions
- Uses per-round constants (sequential or deterministic random)
- Derives a keystream from a seed and those functions
- Embeds an encrypted string into the binary
- Decrypts and prints the original string at runtime

The Python implementation mirrors the generated C logic exactly, ensuring encryption and decryption remain consistent.


## Quick Start

Generate a C file from a plaintext message:

```bash
python gen_fixture.py generate --seed 0xdeadbeef --rounds 1024 --message "Hello, World" --out fixture.c
```

Compile:

```bash
gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline -std=c11 fixture.c -o fixture.exe
```

Run:

```bash
./fixture.exe
```

Expected output:

```
Hello, World
```


## Two-Step Mode

This mode separates encryption from code generation.

### Step 1: Encrypt

```bash
python gen_fixture.py encrypt --seed 0xdeadbeef --rounds 1024 --message "Secret"
```

This outputs:
- A C-style byte array
- A hex string representing the encrypted data

### Step 2: Generate from encrypted data

```bash
python gen_fixture.py generate --seed 0xdeadbeef --rounds 1024 --encrypted-hex <hex_here> --out fixture.c
```

Compile and run as usual.


## Parameters

| Argument | Description |
|----------|------------|
| `--seed` | 32-bit seed used for key derivation |
| `--rounds` | Number of generated functions (1 to 65535) |
| `--message` | Plaintext string to embed |
| `--encrypted-hex` | Pre-encrypted byte string (hex) |
| `--const-mode` | `rand` (default) or `seq` |
| `--const-seed` | Seed for deterministic random constants |
| `--no-volatile-constants` | Allow compiler to fold constants into immediates |
| `--symbol-len` | Approximate base length of generated symbol names |
| `--symbol-pad` | Additional padding added to symbol names |
| `--symbol-prefix` | Custom prefix for symbol names |
| `--out` | Output C file name |

## Symbol Configuration

Symbol names are generated dynamically and can be controlled with:

- `--symbol-len`: Controls the base length of the generated prefix
- `--symbol-pad`: Adds additional repeated padding to increase size
- `--symbol-prefix`: Allows a fully custom prefix

These options allow you to test how tools handle very large or repetitive symbol names.

Example 
```
python gen_fixture.py generate --seed 0xdeadbeef --rounds 1024 --symbol-len 512 --symbol-pad 128 --message "Hello, World" --out fixture.c
```


## Constant Generation Modes

- `rand` (default): Uses deterministic random constants based on `--const-seed`
- `seq`: Uses a predictable incremental pattern (`0x9E3779B9 + i`)

The `rand` mode is recommended for avoiding obvious patterns in disassembly.

## Notes

- The encryption scheme is XOR-based and not cryptographically secure.
- Large values for `--rounds` significantly increase compile time and binary size.
- Debug flags (`-g3 -gdwarf-5`) preserve symbol names for tools like IDA and Ghidra.
- All parameters must match between encryption and generation for correct output.

