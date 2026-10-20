"""Command-line entry point for the PrivacyLens experiment."""

import argparse

from experiment import build_prompts, prepare_data, run_comment, run_input
from experiment.common import check_budget, project_path, read_json


def add_selection(parser, max_requests):
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--case-id", nargs="+", help="select case IDs")
    selection.add_argument("--all", action="store_true", help="select every case in the input")
    parser.add_argument("--limit", type=int, help="maximum number of selected cases")
    parser.add_argument("--max-requests", type=int, default=max_requests, help=f"request attempt limit (default: {max_requests})")
    parser.add_argument("--dry-run", action="store_true", help="save a plan using .env.example")


def add_evaluation_paths(parser):
    parser.add_argument("--context", default="data/pilot/inputs.json", help="generation task contexts")
    parser.add_argument("--labels", default="data/pilot/labels.json", help="evaluation labels")


def main():
    parser = argparse.ArgumentParser(description="Prepare, generate, and assess PrivacyLens actions.")
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare", help="prepare development cases")
    prepare.add_argument("--source", default="data/main_data.json")
    prepare.add_argument("--output-dir", default="data/pilot")
    prepare.add_argument("--limit", type=int, default=5)

    prompts = commands.add_parser("prompts", help="build paired A0/A1 messages")
    prompts.add_argument("--input", default="data/pilot/inputs.json")
    prompts.add_argument("--output", default=build_prompts.DEFAULT_OUTPUT)

    task_input = commands.add_parser("input", help="generate candidate actions")
    task_input.add_argument("--input", default=run_input.DEFAULT_INPUT, help="prepared messages JSONL")
    add_selection(task_input, 2)

    comment = commands.add_parser("comment", help="assess saved candidate actions")
    comment.add_argument("--input", nargs="+", required=True, help="one or more generation results JSONL files")
    add_evaluation_paths(comment)
    add_selection(comment, 4)

    pipeline = commands.add_parser("pipeline", help="generate actions, then assess their results")
    pipeline.add_argument("--input", default=run_input.DEFAULT_INPUT, help="prepared messages JSONL")
    add_evaluation_paths(pipeline)
    add_selection(pipeline, 6)

    args = parser.parse_args()
    if args.command == "prepare":
        prepare_data.run(args)
    elif args.command == "prompts":
        build_prompts.run(args)
    elif args.command == "input":
        run_input.run(args)
    elif args.command == "comment":
        run_comment.run(args)
    else:
        previews = run_input.select_inputs(args)
        # 每条生成请求随后对应一次隐私判断和一次任务完成度判断。
        check_budget(3 * len(previews), args.max_requests)
        contexts, labels = run_comment.load_evaluation_data(args.context, args.labels)
        tool_specs = read_json(project_path("prompts/final_action_specs.json"))
        for case_id in dict.fromkeys(preview["case_id"] for preview in previews):
            labels[case_id]["sensitive_info_items"]
            tool_specs[contexts[case_id]["final_action"]]
        input_args = argparse.Namespace(**{**vars(args), "max_requests": len(previews)})
        run_dir = run_input.run(input_args, previews)
        if args.dry_run:
            print(f"Pipeline plan: {len(previews)} input requests + up to {2 * len(previews)} judge requests")
            return
        comment_args = argparse.Namespace(**{
            **vars(args),
            "input": [str(run_dir / "results.jsonl")],
            "all": True,
            "case_id": None,
            "limit": None,
            "max_requests": args.max_requests - len(previews),
        })
        run_comment.run(comment_args)


if __name__ == "__main__":
    main()
