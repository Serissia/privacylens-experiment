"""Prepare generation inputs and evaluation labels from PrivacyLens cases."""

from hashlib import sha256

from .common import project_path, read_json, write_json


def run(args):
    source_path = project_path(args.source)
    if args.limit < 1:
        raise ValueError("limit must be positive")
    data = read_json(source_path)
    cases = data[-args.limit:] if args.tail else data[:args.limit]
    categories = read_json(project_path(args.categories)) if args.categories else {}

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
            "privacy_category": categories[case["name"]] if args.categories else None,
            "category_source": args.categories or None,
            "seed": case["seed"],
            "vignette": case["vignette"],
            "sensitive_info_items": trajectory["sensitive_info_items"],
        })

    manifest = {
        "source_path": args.source,
        "selection": f"{'last' if args.tail else 'first'} {args.limit} records, preserving original order",
        "sample_count": len(cases),
        "case_ids": [case["name"] for case in cases],
        "purpose": args.purpose,
        "source_sha256": sha256(source_path.read_bytes()).hexdigest(),
        "category_source": args.categories or None,
    }

    output_dir = project_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in (
        ("inputs.json", inputs),
        ("labels.json", labels),
        ("manifest.json", manifest),
    ):
        write_json(output_dir / filename, content)
        print(f"Wrote {args.output_dir}/{filename}")

    print(f"Prepared {len(cases)} cases.")
