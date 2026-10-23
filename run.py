"""Command-line entry point for the PrivacyLens experiment."""

import argparse

from experiment import build_prompts, prepare_data, run_comment, run_input, run_stat
from experiment.common import check_budget, print_token_usage, project_path, read_json


def add_selection(parser, *, model_stage=True):
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case-id", nargs="+", help="select case IDs")
    selection.add_argument("--all", action="store_true", help="select every case in the input")
    parser.add_argument("--limit", type=int, help="maximum number of selected cases")
    if model_stage:
        parser.add_argument("--max-requests", type=int, help="request attempt limit (default: selected request plan size)")
        parser.add_argument("--dry-run", action="store_true", help="save a plan using .env.example")


def add_evaluation_paths(parser):
    parser.add_argument("--context", default="data/pilot/inputs.json", help="generation task contexts")
    parser.add_argument("--labels", default="data/pilot/labels.json", help="evaluation labels")


def run_pipeline(args, usage_records):
    previews = run_input.select_inputs(args)
    # 每条生成请求随后对应一次隐私判断和一次任务完成度判断。
    max_requests = check_budget(3 * len(previews), args.max_requests)
    contexts, labels = run_comment.load_evaluation_data(args.context, args.labels)
    tool_specs = read_json(project_path("prompts/final_action_specs.json"))
    for case_id in dict.fromkeys(preview["case_id"] for preview in previews):
        labels[case_id]["sensitive_info_items"]
        tool_specs[contexts[case_id]["final_action"]]
    input_args = argparse.Namespace(**{**vars(args), "max_requests": len(previews)})
    run_dir = run_input.run(input_args, previews, usage_records)
    if args.dry_run:
        print(f"Pipeline plan: {len(previews)} input requests + up to {2 * len(previews)} judge requests")
        return
    comment_args = argparse.Namespace(**{
        **vars(args),
        "input": [str(run_dir / "results.jsonl")],
        "all": True,
        "case_id": None,
        "limit": None,
        "max_requests": max_requests - len(previews),
    })
    run_comment.run(comment_args, usage_records)


def run_models(args):
    usage_records = []
    try:
        if args.command == "input":
            run_input.run(args, usage_records=usage_records)
        elif args.command == "comment":
            run_comment.run(args, usage_records=usage_records)
        else:
            run_pipeline(args, usage_records)
    finally:
        # 汇总本次调用内已记录的响应用量，包括中断前的请求。
        print_token_usage(usage_records)


def main():
    parser = argparse.ArgumentParser(description="Prepare, generate, and assess PrivacyLens actions.")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("setup-filter", help="download pinned English GLiNER weights and tokenizer")

    prepare = commands.add_parser("prepare", help="prepare development cases")
    prepare.add_argument("--source", default="data/main_data.json")
    prepare.add_argument("--output-dir", default="data/pilot")
    prepare.add_argument("--limit", type=int, default=5)

    prompts = commands.add_parser("prompts", help="build paired A0/A1 messages")
    prompts.add_argument("--input", default="data/pilot/inputs.json")
    prompts.add_argument("--output", default=build_prompts.DEFAULT_OUTPUT)

    task_input = commands.add_parser("input", help="generate A0/A1 candidate actions")
    task_input.add_argument("--input", default=run_input.DEFAULT_INPUT, help="prepared messages JSONL")
    add_selection(task_input)

    task_filter = commands.add_parser("filter", help="derive A2 with local GLiNER/Presidio detection and consistent replacements")
    task_filter.add_argument("--input", required=True, help="one existing generation results JSONL file")
    task_filter.add_argument("--context", default="data/pilot/inputs.json", help="task contexts for keep/protect labels")
    add_selection(task_filter, model_stage=False)

    comment = commands.add_parser("comment", help="assess saved candidate actions")
    comment.add_argument("--input", nargs="+", required=True, help="one or more generation results JSONL files")
    add_evaluation_paths(comment)
    add_selection(comment)

    pipeline = commands.add_parser("pipeline", help="generate and assess A0/A1 actions (input + comment)")
    pipeline.add_argument("--input", default=run_input.DEFAULT_INPUT, help="prepared messages JSONL")
    add_evaluation_paths(pipeline)
    add_selection(pipeline)

    stat = commands.add_parser("stat", help="export summary statistics and figures offline")
    stat.add_argument("--input", nargs="+", required=True, help="one or more summary.json files")
    stat.add_argument("--output-dir", help="statistics directory (default: artifacts/stats/<timestamp>)")

    args = parser.parse_args()
    if args.command == "prepare":
        prepare_data.run(args)
    elif args.command == "prompts":
        build_prompts.run(args)
    elif args.command == "stat":
        run_stat.run(args)
    elif args.command == "filter":
        from experiment import run_filter
        run_filter.run(args)
    elif args.command == "setup-filter":
        from experiment import setup_filter
        setup_filter.run()
    else:
        run_models(args)


if __name__ == "__main__":
    main()
