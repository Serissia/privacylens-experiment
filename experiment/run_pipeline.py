"""Run or resume a fixed generation, filtering and evaluation plan."""

from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

from . import run_comment, run_input, run_stat
from .common import (ROOT, call_json, check_budget, load_settings, project_path,
                     read_json, read_jsonl, select_records, set_parse_error)
from .pipeline_state import (PipelineState, atomic_json, digest, environment_signature,
                             exclusive_run)


def api_config(state, stage, plans, **details):
    directory = state.directory_for(stage)
    path = directory / "config.json"
    if path.exists():
        return read_json(path)
    config = {"run_id": state.config["run_id"], "stage": stage,
              "started_at": state.config["started_at"], "mode": state.config["mode"],
              **state.config["settings"], "timeout_seconds": [10, 60],
              "request_count": len(plans), "planned_requests": plans,
              "pipeline_path": state.directory.as_posix(), **details}
    atomic_json(path, config)
    state.config.setdefault("stage_config_hashes", {})[stage] = digest(path)
    state.save_config()
    return config


def create_run(args, settings):
    source = project_path(args.input)
    previews = select_records([
        {**row, "input_line": line, "task_id": f"input-{line:08d}"}
        for line, row in enumerate(read_jsonl(source), 1)
    ], args.case_id, args.all, args.limit)
    contexts, labels = run_comment.load_evaluation_data(args.context, args.labels)
    case_ids = list(dict.fromkeys(row["case_id"] for row in previews))
    specs = read_json(ROOT / "prompts/final_action_specs.json")
    for case_id in case_ids:
        specs[contexts[case_id]["final_action"]]
        labels[case_id]["sensitive_info_items"]
    filter_ids = [row["task_id"].replace("input-", "filter-") for row in previews if row["condition"] == "A0"]
    if not filter_ids:
        raise SystemExit("Pipeline requires A0 requests to derive A2")
    if any(row["condition"] not in ("A0", "A1") for row in previews):
        raise SystemExit("Pipeline generation input must contain only A0/A1")
    input_ids = [row["task_id"] for row in previews]
    comment_ids = [f"comment-{task_id}-{kind}" for task_id in input_ids + filter_ids
                   for kind in run_comment.JUDGE_VERSIONS]
    planned = len(input_ids) + len(comment_ids)
    maximum = check_budget(planned, args.max_requests)
    now = datetime.now(timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S_%fZ")
    directory = ROOT / ("artifacts/previews/pipeline" if args.dry_run else "artifacts/pipelines") / run_id
    directory.mkdir(parents=True)
    dirs = {stage: (ROOT / "artifacts" / folder / run_id).as_posix()
            for stage, folder in (("input", "runs"), ("filter", "filters"), ("comment", "comments"), ("stat", "stats"))}
    if args.dry_run:
        dirs = {stage: (directory / stage).as_posix() for stage in dirs}
    elif args.output_dir:
        dirs["stat"] = project_path(args.output_dir).resolve().as_posix()
    for path in dirs.values():
        Path(path).mkdir(parents=True, exist_ok=True)
    snapshots = {"contexts.json": [contexts[key] for key in case_ids],
                 "labels.json": [labels[key] for key in case_ids], "previews.json": previews}
    for name, value in snapshots.items():
        atomic_json(directory / name, value)
    config = {"schema_version": 2, "run_id": run_id, "started_at": now.isoformat(),
              "mode": "dry_run" if args.dry_run else "live", "status": "prepared",
              "case_ids": case_ids, "input_path": source.as_posix(),
              "context_path": project_path(args.context).as_posix(), "labels_path": project_path(args.labels).as_posix(),
              "stage_directories": dirs, "planned_requests": planned, "max_requests": maximum,
              "task_ids": {"input": input_ids, "filter": filter_ids, "comment": comment_ids},
              "planned_tasks": {"input": len(input_ids), "filter": len(filter_ids), "comment": len(comment_ids)},
              "settings": {key: value for key, value in settings.items() if key != "api_key"},
              "snapshot_hashes": {name: digest(directory / name) for name in snapshots},
              "environment": environment_signature() if not args.dry_run else None}
    state = PipelineState(directory, config)
    state.save_config()
    plans = run_input.build_plans(previews, settings)
    for plan, preview in zip(plans, previews):
        plan["metadata"].update(task_id=preview["task_id"], input_line=preview["input_line"])
    api_config(state, "input", plans, input_path=source.as_posix())
    state.progress()
    print(f"Pipeline: {directory.relative_to(ROOT).as_posix()}")
    print(f"Plan: {len(input_ids)} input + {len(filter_ids)} local A2 + {len(comment_ids)} judge requests")
    return state


def load_resume(args):
    directory = project_path(args.resume).resolve()
    config = read_json(directory / "config.json")
    if config.get("schema_version") != 2 or config.get("mode") != "live":
        raise SystemExit("Resume requires a live pipeline created by the resumable runner")
    if config["environment"] != environment_signature():
        raise SystemExit("Code, prompts, local models or package versions changed; start a new experiment")
    for name, expected in config["snapshot_hashes"].items():
        if digest(directory / name) != expected:
            raise SystemExit(f"Pipeline snapshot changed: {name}")
    for stage, expected in config.get("stage_config_hashes", {}).items():
        if digest(Path(config["stage_directories"][stage]) / "config.json") != expected:
            raise SystemExit(f"Saved stage configuration changed: {stage}")
    for stage, expected in config.get("result_hashes", {}).items():
        if digest(Path(config["stage_directories"][stage]) / "results.jsonl") != expected:
            raise SystemExit(f"Saved completed stage results changed: {stage}")
    state = PipelineState(directory, config)
    if args.max_requests is not None:
        if args.max_requests < config["max_requests"]:
            raise SystemExit("--max-requests may only increase the cumulative limit")
        config["max_requests"] = args.max_requests
    required = state.minimum_required_budget()
    if not args.dry_run and config["max_requests"] < required:
        raise SystemExit(f"At least {required} total attempts are needed; resume with --max-requests {required}")
    if not args.dry_run:
        state.save_config()
    return state


def execute_api_stage(state, stage, config, key, usage_records):
    plans = config["planned_requests"]
    ids = state.config["task_ids"][stage]
    with tqdm(total=len(plans), initial=sum(t in state.successes for t in ids), desc=stage, unit="request") as progress:
        for plan in plans:
            task_id = plan["metadata"]["task_id"]
            if task_id in state.successes:
                continue
            def invoke(attempt):
                result = call_json({**plan, "attempt": attempt}, config, state.directory_for(stage), key)
                usage_records.append(result)
                if stage == "input":
                    run_input.parse_action(result)
                else:
                    result.update(leak_info=None, secret_judgment=None, helpfulness_score=None)
                    if result["status"] == "ok":
                        try:
                            run_comment.parse_assessment(result, plan)
                        except (KeyError, IndexError, TypeError) as error:
                            set_parse_error(result, error)
                return result
            state.execute(task_id, stage, {**plan["metadata"], "run_id": config["run_id"],
                          "requested_model": plan["payload"]["model"], "kind": plan["metadata"]["kind"]}, invoke)
            progress.update()
    return state.materialize(stage, ids)


def execute_filter(state):
    ids = state.config["task_ids"]["filter"]
    if all(task_id in state.successes for task_id in ids):
        return state.materialize("filter", ids)
    from .run_filter import PiiFilter, build_config
    input_path = state.directory_for("input") / "results.jsonl"
    sources = [{"case_id": row["case_id"], "line": line, "record": row}
               for line, row in enumerate(read_jsonl(input_path), 1) if row["condition"] == "A0"]
    contexts = {r["case_id"]: {k: r[k] for k in ("user_name", "user_instruction")}
                for r in read_json(state.directory / "contexts.json")}
    engine = PiiFilter()
    path = state.directory_for("filter") / "config.json"
    if not path.exists():
        config = build_config(engine, sources, input_path.as_posix(), (state.directory / "contexts.json").as_posix(),
                              {"case_ids": state.config["case_ids"], "all": True, "limit": None},
                              state.config["run_id"], datetime.fromisoformat(state.config["started_at"]))
        config["pipeline_path"] = state.directory.as_posix()
        atomic_json(path, config)
        state.config.setdefault("stage_config_hashes", {})["filter"] = digest(path)
        state.save_config()
    with tqdm(total=len(ids), initial=sum(t in state.successes for t in ids), desc="filter", unit="action") as progress:
        for task_id, source in zip(ids, sources):
            if task_id in state.successes:
                continue
            state.execute(task_id, "filter", {"case_id": source["case_id"], "condition": "A2", "kind": "filter"},
                          lambda attempt: engine.derive(source["record"], input_path.as_posix(), source["line"],
                                                        state.config["run_id"], contexts[source["case_id"]]))
            progress.update()
    return state.materialize("filter", ids)


def execute(state, settings, usage_records):
    input_config = read_json(state.directory_for("input") / "config.json")
    execute_api_stage(state, "input", input_config, settings["api_key"], usage_records)
    execute_filter(state)
    paths = [(state.directory_for(s) / "results.jsonl").as_posix() for s in ("input", "filter")]
    sources = [{**row, "source_path": path, "source_line": line}
               for path in paths for line, row in enumerate(read_jsonl(Path(path)), 1)]
    contexts = {r["case_id"]: r for r in read_json(state.directory / "contexts.json")}
    labels = {r["case_id"]: r for r in read_json(state.directory / "labels.json")}
    plans = run_comment.build_plans(sources, contexts, labels, state.config["settings"])
    for plan, task_id in zip(plans, state.config["task_ids"]["comment"]):
        plan["metadata"]["task_id"] = task_id
    config = api_config(state, "comment", plans, input_paths=paths,
                        context_path=(state.directory / "contexts.json").as_posix(),
                        labels_path=(state.directory / "labels.json").as_posix(),
                        selected_sources=[run_comment.source_metadata(row) for row in sources])
    atomic_json(state.directory_for("comment") / "labels.json", list(labels.values()))
    directory = execute_api_stage(state, "comment", config, settings["api_key"], usage_records)
    judge_attempts = [row for row in state.attempts if row["pipeline_stage"] == "comment"]
    summary = run_comment.summarize(sources, judge_attempts, len(plans), labels)
    atomic_json(directory / "summary.json", summary)
    run_stat.run(Namespace(input=[str(directory / "summary.json")], output_dir=str(state.directory_for("stat")), categories=None))
    state.config.update(status="complete", stat_complete=True)
    state.save_config()
    state.progress()
    print(f"Pipeline completed: {state.directory}")


def run(args, usage_records):
    if getattr(args, "resume", None):
        directory = project_path(args.resume).resolve()
        with exclusive_run(directory):
            state = load_resume(args)
            if args.dry_run:
                print(state.progress())
                return directory
            api_pending = any(task_id not in state.successes for stage in ("input", "comment")
                              for task_id in state.config["task_ids"][stage])
            settings = {**state.config["settings"], "api_key": load_settings(False)["api_key"] if api_pending else ""}
            try:
                execute(state, settings, usage_records)
            finally:
                state.progress()
        return directory
    args.input = args.input or run_input.DEFAULT_INPUT
    args.context = args.context or "data/pilot/inputs.json"
    args.labels = args.labels or "data/pilot/labels.json"
    settings = load_settings(args.dry_run)
    state = create_run(args, settings)
    if args.dry_run:
        print("Dry run saved; no API requests made")
        return state.directory
    with exclusive_run(state.directory):
        try:
            execute(state, settings, usage_records)
        finally:
            state.progress()
    return state.directory
