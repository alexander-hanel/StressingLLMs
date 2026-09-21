# Reproduce the tokenization walkthrough

Follow these steps to run the tokenization experiments and compare your output with the
article's measurements. No model API or account is required.

The exact token counts depend on the vocabulary. The published values used the Nemotron
vocabulary as model A and the DeepSeek vocabulary as model B. Other Hugging Face
`tokenizer.json` files work, but their results will differ.

## 0. Setup

Install Python 3.10+, pip, Python virtual-environment support, Bash, and GCC. Download or clone
the repository, then open a terminal in its root directory:

```bash
cd tokenization-repro
```

Create a Python virtual environment and install the dependency from `requirements.txt`.
This step requires an internet connection:

```bash
bash bootstrap.sh
```

The included `tokenizer-data/model-a.json` and `tokenizer-data/model-b.json` files reproduce
the published measurements. No additional tokenizer setup is needed.

Optional: to test different vocabularies, replace the placeholder paths below with your own
Hugging Face tokenizer files:

```bash
mkdir -p tokenizer-data
cp /path/to/nemotron/tokenizer.json tokenizer-data/model-a.json
cp /path/to/deepseek/tokenizer.json tokenizer-data/model-b.json
```

Alternatively, set environment variables to those files:

```bash
export TOKENIZER_A=/path/to/nemotron/tokenizer.json
export TOKENIZER_B=/path/to/deepseek/tokenizer.json
```

Check the installation and both vocabularies:

```bash
.venv/bin/python check_setup.py --require-model-b
```

To run the automated end-to-end verification before following the individual experiments:

```bash
bash verify_bundle.sh
```

Key files after setup (not a complete directory listing):

```text
tokenization-repro/
├── .venv/
├── gen_fixture.py
├── requirements.txt
├── measure_tokens.py
├── compare_names.py
├── stress_tokenizer.py
├── tokenize_file.py
├── where_do_the_tokens_go.py
└── tokenizer-data/
    ├── model-a.json
    └── model-b.json
```

Model B is only required by the two-vocabulary examples. GCC is only required when compiling C
fixtures.

## 1. Count tokens for sample strings

```bash
.venv/bin/python measure_tokens.py
```

Expected with the published model A vocabulary:

```text
  2 tokens /  13 chars = 0.154 tpc
 19 tokens /  73 chars = 0.260 tpc
 40 tokens /  10 chars = 4.000 tpc
 10 tokens /  10 chars = 1.000 tpc
```

An explicit path can replace the configured model A file:

```bash
.venv/bin/python measure_tokens.py --tokenizer /path/to/tokenizer.json
```

## 2. Compare repetitive and diverse identifiers

```bash
.venv/bin/python compare_names.py
```

Expected with the published model A vocabulary:

```text
repetitive   73 tokens / 256 chars = 0.285 tpc
diverse     119 tokens / 256 chars = 0.465 tpc
```

Both identifiers have the same length. Only their internal structure changes.

## 3. Search candidate constructions

```bash
.venv/bin/python stress_tokenizer.py --quick
```

The script reads every configured tokenizer and reports token density, timing, and the winning
candidate. With the published vocabularies, `highplane_oov` wins for both models at approximately
four tokens per character.

To provide vocabularies directly:

```bash
.venv/bin/python stress_tokenizer.py --quick \
  --tokenizer nemotron=/path/to/nemotron/tokenizer.json \
  --tokenizer deepseek=/path/to/deepseek/tokenizer.json
```

The `--no-real` fallback exists for historical comparison but is not suitable for reproducing the
published measurements.

## 4. Generate, compile, and run a diverse fixture

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef --rounds 3 \
  --symbol-diverse-body --symbol-len 256 \
  --message DIVERSE_OK --out div.c

gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline \
  -std=c11 div.c -o div.exe

./div.exe
```

Expected:

```text
DIVERSE_OK
```

The printed message verifies that generation, compilation, and runtime decryption agree.

## 5. Generate the high-plane Unicode fixture

Use the exact filename below. The generator records it in a header comment, so changing the name
slightly changes the whole-file character and token counts.

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef --rounds 8 \
  --symbol-len 512 --symbol-unicode-body \
  --message HARDEST_FIXTURE_OK --out hardest.c

gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline \
  -std=c11 hardest.c -o hardest.exe

./hardest.exe
```

Expected:

```text
HARDEST_FIXTURE_OK
```

Inspect the generated identifier:

```bash
python3 inspect_unicode_fixture.py hardest.c
```

The final two lines should be:

```text
all in range: True
each is 4 bytes: True
```

## 6. Tokenize the generated source

```bash
.venv/bin/python tokenize_file.py hardest.c
```

Expected with the published model A vocabulary:

```text
19,794 chars -> 57,674 tokens
2.9137 tokens per character
0.941 tokens per byte
```

Measure the long identifier's share of the file:

```bash
.venv/bin/python where_do_the_tokens_go.py hardest.c
```

Expected:

```text
name: 567 chars / 2103 bytes -> 2045 tokens
name appears 11 times
tokens spent on the name: ~22,495
share of all tokens: 39.0%
```

## 7. Compare all three fixture modes

Generate matching repetitive and diverse fixtures. Keep all three files in this directory.

```bash
python3 gen_fixture.py generate \
  --seed 0xdeadbeef --rounds 8 --symbol-len 512 \
  --message HARDEST_FIXTURE_OK --out rep.c

python3 gen_fixture.py generate \
  --seed 0xdeadbeef --rounds 8 --symbol-len 512 \
  --symbol-diverse-body --message HARDEST_FIXTURE_OK --out div.c

.venv/bin/python compare_modes.py
```

Expected with the published model A vocabulary:

```text
repetitive   chars=19,786  bytes=19,786  tokens=6,879  tpc=0.348
diverse      chars=19,759  bytes=19,759  tokens=9,498  tpc=0.481
unicode OOV  chars=19,794  bytes=61,266  tokens=57,674  tpc=2.914
```

## 8. Inspect bytes and vocabulary differences

Print the bytes and token density for each sample string:

```bash
.venv/bin/python byte_examples.py
```

Compare emoji and high-plane Unicode under both vocabularies:

```bash
.venv/bin/python compare_vocabularies.py
```

Expected with the published vocabularies:

```text
emoji x100 model A=400  model B=200
oov x100   model A=400  model B=400
```

## 9. Check C language compatibility

The Unicode identifier requires a modern C mode:

```bash
gcc -std=c89 -fsyntax-only hardest.c
```

C89 reports many errors, including raw UTF-8 bytes in the identifier. C11 accepts the file:

```bash
gcc -std=c11 -fsyntax-only hardest.c
```

The successful C11 command prints nothing.

## 10. Measure tokenization time

```bash
.venv/bin/python benchmark_tokenizer_time.py
```

Timing varies by machine. The relevant result is the scaling pattern: increasing input length
produces approximately proportional runtime rather than quadratic growth.

## 11. Run generator regression tests

```bash
.venv/bin/python tests/test_gen_fixture.py
```

The suite generates temporary fixtures, compiles them when GCC is available, and verifies exact
decryption output.

## Troubleshooting

### No tokenizer file was found

Use one of these methods:

```bash
cp /path/to/tokenizer.json tokenizer-data/model-a.json
export TOKENIZER_A=/path/to/tokenizer.json
.venv/bin/python measure_tokens.py --tokenizer /path/to/tokenizer.json
```

### `ModuleNotFoundError: tokenizers`

Use `.venv/bin/python` for tokenization scripts and confirm installation:

```bash
.venv/bin/python -c "import tokenizers; print(tokenizers.__version__)"
```

### Counts differ from this manual

Token counts are vocabulary-specific. Confirm that the same tokenizer file and output filenames
were used. The scripts print valid measurements for other vocabularies, but they will not match
the published values.

### GCC is unavailable

The pure tokenization examples still work. Fixture compilation and runtime verification require a
C11 compiler.
