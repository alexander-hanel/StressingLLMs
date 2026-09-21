# Tokenization examples

Run the tokenization article's experiments and compare how ASCII and Unicode inputs affect
token counts. No model API or account is required.

## Install

Requires Python 3.10+, pip, Python virtual-environment support, and Bash. Install GCC to compile
the generated C fixtures and run the complete test suite.

Download or clone the repository, then run these commands from its root directory:

```bash
cd tokenization-repro
bash bootstrap.sh
```

The setup script creates `.venv/` and installs the dependency from `requirements.txt` using pip.
An internet connection is required for installation.

## Run

```bash
.venv/bin/python measure_tokens.py
.venv/bin/python compare_names.py
.venv/bin/python compare_vocabularies.py
bash verify_bundle.sh
```

Follow [MANUAL.md](MANUAL.md) for the complete commands and expected results. Verification uses
a temporary directory for generated files and checks exact fixture sizes and token counts.

## Contents

- `gen_fixture.py`: generates deterministic C fixtures with configurable identifiers.
- Root-level Python scripts: tokenizer measurements and fixture inspection.
- `tokenizer_paths.py`: shared tokenizer loading and exact encode/decode checks.
- `tests/`: generator regression tests.
- `experiments/tokenize_backend.py`: historical fallback used by `--no-real`; not for published counts.
- `tokenizer-data/`: the two vocabularies needed to reproduce the measurements (about 23 MB).
- `requirements.txt`, setup/verification scripts, and this manual.

The vocabulary files retain their upstream licenses; review those terms before redistribution.
They can be replaced with other Hugging Face tokenizer files, but the expected counts will differ.
