# Stressing LLMs

Generate C binaries with long, configurable symbol names and a seed-based XOR decryption routine.

This repo is for static-analysis testing, reverse-engineering practice, and evaluating how LLM-assisted workflows degrade under code-complexity and tokenization pressure.

Introductory blog post:

<https://hooked-on-mnemonics.blogspot.com/2026/05/stressing-llms-triage-stage.html>

Local Model Results 
<https://alexander-hanel.github.io/StressingLLMs/>

OpenCode Model Results 
<https://alexander-hanel.github.io/StressingLLMs/opencode.html>

## Overview

`gen_fixture.py` generates a C program that:

- creates a large number of uniquely named functions
- uses per-round constants, either sequential or deterministic-random
- derives a keystream from a seed and those functions
- embeds an encrypted string into the binary
- decrypts and prints the original string at runtime

The Python implementation mirrors the generated C logic, so encryption and decryption stay consistent between the generator and the emitted C.

## Quick Start

Generate a C file from a plaintext message:

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef \
  --rounds 1024 \
  --message "Hello, World" \
  --out fixture.c
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
|----------|-------------|
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

Example:

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

## Stage 2 Workflow

The current stage-2 workflow uses:

- LibreChat as the frontend
- Ollama for local models
- `pyghidra-mcp` in Docker
- Ghidra bundled inside that container

You do not need Ghidra installed on the host for the primary path.

Detailed runbook:

- [STAGE2.md](/home/axel/repos/StressingLLMs/STAGE2.md:1)

### Repo-Root Workspace

The stage-2 workflow uses repo-root directories:

```text
fixtures/
ghidra-projects/
prompts/
runs/
reports/
```

Create them if needed:

```bash
mkdir -p fixtures/src fixtures/bin fixtures/manifests ghidra-projects prompts runs reports
```

### Baseline Fixture

Generate one small baseline fixture:

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef \
  --rounds 5 \
  --symbol-len 16 \
  --symbol-pad 0 \
  --message "Hello, World" \
  --out fixtures/src/fx_r0005_sl0016_sp0000.c
```

Compile it:

```bash
gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline -std=c11 \
  fixtures/src/fx_r0005_sl0016_sp0000.c \
  -o fixtures/bin/fx_r0005_sl0016_sp0000_dwarf.exe
```

### Dockerized Ghidra MCP

The stock `pyghidra-mcp` CLI path is not sufficient for this LibreChat setup because the upstream image enables localhost-only host-header protection at import time.

Use the working container topology instead:

1. put `pyghidra-root` on the `librechat_default` Docker network
2. point LibreChat at `http://pyghidra-root:8000/mcp`
3. start `pyghidra-mcp` programmatically with transport security disabled for this local-only environment

Start `pyghidra-root` from the repo root:

```bash
docker rm -f pyghidra-root 2>/dev/null || true

docker run -d \
  --name pyghidra-root \
  --network librechat_default \
  -p 8000:8000 \
  -v "$PWD/fixtures/bin:/binaries" \
  -v "$PWD/ghidra-projects:/projects" \
  --entrypoint /app/.venv/bin/python \
  ghcr.io/clearbluejar/pyghidra-mcp \
  -c 'import pyghidra_mcp.server as s; from mcp.server.transport_security import TransportSecuritySettings; s.mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False); s.main.main(args=["-t","streamable-http","-o","0.0.0.0","-p","8000","--project-path","/projects","--project-name","stressing-llms-root","/binaries"], standalone_mode=False)'
```

Important:

- use `/binaries`, not `/binaries/*`
- the first run imports binaries from the mounted directory
- project state persists in `ghidra-projects/`
- this approach avoids the upstream Host-header rejection that breaks LibreChat connectivity

To restart the same project later, use the same command. The existing project in `ghidra-projects/` will be reopened automatically.

### LibreChat MCP Target

LibreChat should point its MCP server at:

```text
http://pyghidra-root:8000/mcp
```

The active LibreChat config in this environment is:

- [librechat.yaml](/home/axel/LibreChat/librechat.yaml:1)

## Adding Campaign Results to the Documentation Dashboard

Use `scripts/append_campaign_to_dashboard.py` to append a completed campaign to the existing dashboard in `docs/index.html`. Run it from the repository root with the campaign's generated `progress.json` file:

```bash
.venv/bin/python scripts/append_campaign_to_dashboard.py \
  reports/bench/campaign_<id>/progress.json \
  docs/index.html
```

The campaign directory can be passed instead of the file:

```bash
.venv/bin/python scripts/append_campaign_to_dashboard.py \
  reports/bench/campaign_<id> \
  docs/index.html
```

Preview and validate the update without changing `docs/index.html`:

```bash
.venv/bin/python scripts/append_campaign_to_dashboard.py \
  reports/bench/campaign_<id>/progress.json \
  docs/index.html \
  --dry-run
```

The script reads campaign IDs from invisible metadata in the dashboard and reconstructs their results from sibling `campaign_<id>/progress.json` directories. For a legacy dashboard without this metadata, it safely infers the source campaigns by exact matching of every embedded attempt record. Campaign IDs are not added to the visible page title or header. If those reports live somewhere other than the new campaign's reports root, specify their common parent:

```bash
.venv/bin/python scripts/append_campaign_to_dashboard.py \
  /path/to/new-campaign/progress.json \
  docs/index.html \
  --campaign-root /path/to/reports/bench
```

Before writing, the updater regenerates all existing dashboard fields and tables, verifies that no prior attempt was removed or changed, verifies that the new campaign attempts are present, and then replaces the page atomically. Adding a campaign already present in the dashboard is an idempotent no-op.

## OpenCode Campaign Explorer

Open `docs/opencode.html` directly in a browser to explore stored adaptive OpenCode
campaigns. Smoke tests and paused trial campaigns are omitted. The standalone file includes campaign/model filters, an interactive
round map, runtime and OpenCode-recorded cost plots, searchable attempts, submissions, sandbox output, and
JSON/CSV exports. It works offline and can be shared as a single file.

Regenerate the snapshot after a campaign changes:

```bash
python3 scripts/build_opencode_explorer.py
```

Use `--campaign-root /path/to/runs/bench` and `--output /path/to/explorer.html`
for other locations. The builder reads campaign SQLite databases without changing
them. Archived retries remain inspectable but are excluded from current totals;
provider errors and interrupted reservations are excluded from graded pass rates.
Costs retain each campaign's recorded estimates rather than representing actual
billing. This explorer is separate from `docs/index.html`.

## Sequential Free OpenCode Evaluations

Check free-model access and an actual file-read tool call first:

```bash
PATH="$HOME/.opencode/bin:$PWD/.venv/bin:$PATH" .venv/bin/python \
  scripts/check_opencode_free_models.py \
  --output reports/bench/opencode-free-availability.json
```

Run the verified models sequentially, creating a separate adaptive campaign for
each model:

```bash
PATH="$HOME/.opencode/bin:$PWD/.venv/bin:$PATH" .venv/bin/python \
  scripts/run_opencode_free_campaigns.py \
  --availability reports/bench/opencode-free-availability.json \
  --state reports/bench/opencode-free-queue.json \
  --log reports/bench/opencode-free-queue.log
```

The configuration is `configs/benchmark.opencode-zen-free-adaptive.yaml`: one
fixture at a time, 90 minutes per attempt, two consecutive graded failures before
bisection, and zero configured model prices. Provider errors stop the affected
campaign before they become adaptive failure observations; the queue moves on
to the next model. The HTML explorer refreshes as results are recorded.

The state file records campaign IDs and queue status. Rerunning the same command
resumes unfinished campaigns and skips finished or blocked entries. Use a new
state file to start a new evaluation batch. Availability reports retain check
history; the queue uses the latest check for each model. The API-listed free
DeepSeek model is also probed, but it is not in the six-model queue configuration
while its server requests fail.

## Current Local Model Suggestions

On stronger local hardware, such as a DGX Spark-class box, a reasonable starting set is:

```bash
ollama pull qwen3-coder:30b
ollama pull qwen3.6:35b
ollama pull glm-4.7-flash
ollama pull gemma4:26b
```

Treat model selection as part of the experiment, not a fixed constant.
