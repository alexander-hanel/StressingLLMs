# Recorded tokenizer vocabularies

`model-a.json` and `model-b.json` contain the tokenizer vocabularies used for the article's
measurements. The examples load these files by default; no model weights are needed.

- Model A: Nemotron, BPE vocabulary size 131,072.
- Model B: DeepSeek, BPE vocabulary size 128,000.

The files retain their upstream licenses; copying them here does not grant redistribution rights.
Review the upstream terms before publishing this data.

To use other files, set `TOKENIZER_A` and `TOKENIZER_B` or pass the scripts' tokenizer path options.
Different vocabularies may produce different counts.
