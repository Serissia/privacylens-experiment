Data are moved from PrivacyLens/data to this repository's data/ directory. The original PrivacyLens repository is referenced for versioning and source tracking, but this project does not depend on the full PrivacyLens environment.

`benign_v1/` contains five original synthetic development scenarios for permitted information sharing. See [its data card](benign_v1/README.md) for details.

`final_test/` contains the final 100 cases in source order (main394–main493): `inputs.json`, `labels.json`, `prompts.jsonl`, and `categories.json`. The 100 cases contain 306 sensitive facts and 200 paired generation prompts. Nine primary categories were assigned by Codex from the sensitive facts and scenario context; these are model annotations. Some source types and facts differ in meaning, so category-level results require cautious interpretation. The source data remain in `main_data.json`; the original [PrivacyLens licence](LICENSE-PrivacyLens) applies.

Run from the project root:

```powershell
.\.venv\Scripts\python.exe run.py pipeline --input data/final_test/prompts.jsonl --context data/final_test/inputs.json --labels data/final_test/labels.json --all
```
