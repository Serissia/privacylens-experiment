"""Run generation, paired filtering, joint assessment and statistics in order."""

from argparse import Namespace
from datetime import datetime, timezone

from . import run_comment, run_input, run_stat
from .common import ROOT, check_budget, project_path, read_json, write_json


def run(args, usage_records):
    previews = run_input.select_inputs(args)
    input_count = len(previews)
    filter_count = sum(preview["condition"] == "A0" for preview in previews)
    if not filter_count:
        raise SystemExit("Pipeline requires A0 requests to derive A2")
    comment_count = 2 * (input_count + filter_count)
    max_requests = check_budget(input_count + comment_count, args.max_requests)

    contexts, labels = run_comment.load_evaluation_data(args.context, args.labels)
    tool_specs = read_json(project_path("prompts/final_action_specs.json"))
    case_ids = list(dict.fromkeys(preview["case_id"] for preview in previews))
    for case_id in case_ids:
        labels[case_id]["sensitive_info_items"]
        tool_specs[contexts[case_id]["final_action"]]

    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%S_%fZ")
    root = "artifacts/previews/pipeline" if args.dry_run else "artifacts/pipelines"
    pipeline_dir = ROOT / root / run_id
    pipeline_dir.mkdir(parents=True)
    config = {
        "run_id": run_id, "stage": "pipeline", "started_at": started_at.isoformat(),
        "mode": "dry_run" if args.dry_run else "live",
        "input_path": project_path(args.input).as_posix(),
        "context_path": project_path(args.context).as_posix(),
        "labels_path": project_path(args.labels).as_posix(),
        "case_ids": case_ids,
        "planned_requests": input_count + comment_count,
        "max_requests": max_requests,
        "stages": [
            {"name": "input", "depends_on": [], "request_count": input_count, "output_count": input_count},
            {"name": "filter", "depends_on": ["input"], "request_count": 0, "output_count": filter_count},
            {"name": "comment", "depends_on": ["input", "filter"], "request_count": comment_count, "source_count": input_count + filter_count},
            {"name": "stat", "depends_on": ["comment"], "request_count": 0, "output_dir": args.output_dir},
        ],
        "stage_directories": {},
    }

    def record_stage(name, directory):
        config["stage_directories"][name] = directory.as_posix()
        write_json(pipeline_dir / "config.json", config)

    write_json(pipeline_dir / "config.json", config)
    print(f"Pipeline plan: {input_count} input + {filter_count} local A2 + {comment_count} judge requests")
    print("[1/4] input: generate A0/A1")
    input_args = Namespace(**{**vars(args), "max_requests": input_count})
    input_dir = run_input.run(input_args, previews, usage_records)
    record_stage("input", input_dir)
    if args.dry_run:
        print(f"Saved four-stage pipeline plan to {pipeline_dir.relative_to(ROOT).as_posix()}")
        return pipeline_dir

    from . import run_filter

    # 后续阶段完整接收本轮选定输出，包含同案例的全部条件与重复观测。
    selected = {**vars(args), "all": True, "case_id": None, "limit": None}
    print("[2/4] filter: derive A2 from the same A0 actions")
    filter_args = Namespace(**{**selected, "input": str(input_dir / "results.jsonl")})
    filter_dir = run_filter.run(filter_args)
    record_stage("filter", filter_dir)

    print("[3/4] comment: assess A0/A1/A2")
    comment_args = Namespace(**{
        **selected,
        "input": [str(input_dir / "results.jsonl"), str(filter_dir / "results.jsonl")],
        "max_requests": max_requests - input_count,
    })
    comment_dir = run_comment.run(comment_args, usage_records)
    record_stage("comment", comment_dir)

    print("[4/4] stat: export statistics and figures")
    stat_args = Namespace(input=[str(comment_dir / "summary.json")], output_dir=args.output_dir)
    stat_dir = run_stat.run(stat_args)
    record_stage("stat", stat_dir)
    print(f"Pipeline completed: {pipeline_dir.relative_to(ROOT).as_posix()}")
    return pipeline_dir
