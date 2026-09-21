#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$BUNDLE_DIR/.venv/bin/python}"
export PYTHONDONTWRITEBYTECODE=1
VERIFY_DIR="$(mktemp -d /tmp/tokenization-repro-check.XXXXXX)"
cd "$VERIFY_DIR"

"$PYTHON_BIN" "$BUNDLE_DIR/check_setup.py" --require-model-b
"$PYTHON_BIN" "$BUNDLE_DIR/tests/test_gen_fixture.py"
for SCRIPT_NAME in measure_tokens compare_names byte_examples compare_vocabularies; do
    "$PYTHON_BIN" "$BUNDLE_DIR/$SCRIPT_NAME.py"
done
"$PYTHON_BIN" "$BUNDLE_DIR/stress_tokenizer.py" --quick --outdir "$VERIFY_DIR/hostile_out"
"$PYTHON_BIN" "$BUNDLE_DIR/benchmark_tokenizer_time.py" --sizes 160,640 --repeats 1

for FIXTURE_MODE in rep div hardest; do
    MODE_ARGS=()
    if [[ "$FIXTURE_MODE" == div ]]; then MODE_ARGS+=(--symbol-diverse-body); fi
    if [[ "$FIXTURE_MODE" == hardest ]]; then MODE_ARGS+=(--symbol-unicode-body); fi
    "$PYTHON_BIN" "$BUNDLE_DIR/gen_fixture.py" generate \
        --seed 0xdeadbeef --rounds 8 --symbol-len 512 \
        --message HARDEST_FIXTURE_OK "${MODE_ARGS[@]}" --out "$FIXTURE_MODE.c"
    gcc -O0 -g3 -gdwarf-5 -fno-omit-frame-pointer -fno-inline -std=c11 \
        "$FIXTURE_MODE.c" -o "$FIXTURE_MODE.exe"
    test "$(./"$FIXTURE_MODE.exe")" = "HARDEST_FIXTURE_OK"
done

"$PYTHON_BIN" "$BUNDLE_DIR/inspect_unicode_fixture.py" hardest.c
"$PYTHON_BIN" "$BUNDLE_DIR/tokenize_file.py" hardest.c
"$PYTHON_BIN" "$BUNDLE_DIR/where_do_the_tokens_go.py" hardest.c
"$PYTHON_BIN" "$BUNDLE_DIR/compare_modes.py"

"$PYTHON_BIN" - "$BUNDLE_DIR" <<'PY'
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from tokenizer_paths import encode_verified, load_tokenizer, resolve_tokenizer

models = [load_tokenizer(resolve_tokenizer(None, slot=slot)) for slot in ('a', 'b')]
expected = {
    'rep.c': (19786, 19786, 6879, 6724),
    'div.c': (19759, 19759, 9498, 9424),
    'hardest.c': (19794, 61266, 57674, 57701),
}
for filename, counts in expected.items():
    source = Path(filename).read_text(encoding='utf-8')
    actual = (len(source), len(source.encode('utf-8')),
              *(len(encode_verified(model, source).ids) for model in models))
    assert actual == counts, (filename, actual, counts)
print('PASS: exact character, byte, and token counts for all three fixtures and both vocabularies.')
PY

printf '\nVerification passed. Generated files are outside the bundle: %s\n' "$VERIFY_DIR"
