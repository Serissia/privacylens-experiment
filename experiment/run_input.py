"""Generate candidate actions from prepared task messages."""

from tqdm import tqdm

from .build_prompts import DEFAULT_OUTPUT
from .common import (
    INPUT_PARAMETERS,
    append_jsonl,
    call_json,
    check_budget,
    load_settings,
    project_path,
    read_jsonl,
    select_records,
    set_parse_error,
    start_run,
)


DEFAULT_INPUT = DEFAULT_OUTPUT


def select_inputs(args):
    return select_records(read_jsonl(project_path(args.input)), args.case_id, args.all, args.limit)


def build_plans(previews, settings):
    return [
        {
            "metadata": {
                "case_id": preview["case_id"],
                "condition": preview["condition"],
                "prompt_version": preview["prompt_version"],
                "prompt_char_count": preview["prompt_char_count"],
                "kind": "input",
            },
            "payload": {**INPUT_PARAMETERS, "model": settings["base_model"], "messages": preview["messages"]},
        }
        for preview in previews
    ]


def parse_action(result):
    result["final_action"] = None
    if result["status"] == "ok":
        try:
            action = result["model_output"]
            result["final_action"] = {"action": action["action"], "action_input": action["action_input"]}
            result["status"] = "refused" if action["action"] == "REFUSE" else "ok"
        except (KeyError, TypeError) as error:
            set_parse_error(result, error)


def run(args, previews=None, usage_records=None):
    previews = select_inputs(args) if previews is None else previews
    max_requests = check_budget(len(previews), args.max_requests)
    settings = load_settings(args.dry_run)
    plans = build_plans(previews, settings)
    run_dir, config = start_run(
        "input", plans, settings, max_requests, args.dry_run,
        {"input_path": project_path(args.input).as_posix()},
    )
    if args.dry_run:
        return run_dir

    with tqdm(total=len(plans), desc="Input A0/A1", unit="request", dynamic_ncols=True) as progress:
        for plan in plans:
            result = call_json(plan, config, run_dir, settings["api_key"])
            if usage_records is not None:
                usage_records.append(result)
            parse_action(result)
            append_jsonl(run_dir / "results.jsonl", result)
            progress.set_postfix(case=result["case_id"], condition=result["condition"], status=result["status"], refresh=False)
            progress.update()
            if result["status"] not in ("ok", "refused"):
                raise SystemExit(1)
    return run_dir
