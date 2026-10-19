"""Prepare the first five PrivacyLens cases for development."""

import json
from pathlib import Path


def main():
    project_dir = Path(__file__).resolve().parent
    source_path = project_dir / "data/main_data.json"
    cases = json.loads(source_path.read_text(encoding="utf-8"))[:5]

    inputs = []
    labels = []
    for case in cases:
        trajectory = case["trajectory"]
        inputs.append({
            "case_id": case["name"],
            "user_name": trajectory["user_name"],
            "user_email": trajectory["user_email"],
            "user_instruction": trajectory["user_instruction"],
            "toolkits": trajectory["toolkits"],
            "executable_trajectory": trajectory["executable_trajectory"],
            "final_action": trajectory["final_action"],
        })
        labels.append({
            "case_id": case["name"],
            "seed": case["seed"],
            "vignette": case["vignette"],
            "sensitive_info_items": trajectory["sensitive_info_items"],
        })

    manifest = {
        "source_path": source_path.relative_to(project_dir).as_posix(),
        "selection": "first 5 records, preserving original order",
        "sample_count": len(cases),
        "case_ids": [case["name"] for case in cases],
        "purpose": "development/pilot",
    }

    output_dir = project_dir / "data/pilot"
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in (
        ("inputs.json", inputs),
        ("labels.json", labels),
        ("manifest.json", manifest),
    ):
        with (output_dir / filename).open("w", encoding="utf-8", newline="\n") as f:
            json.dump(content, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"Wrote data/pilot/{filename}")

    print(f"Prepared {len(cases)} development/pilot cases.")


if __name__ == "__main__":
    main()
