"""Shared file handling and one-attempt JSON API requests."""

import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

import requests
from dotenv import dotenv_values, load_dotenv

from .reproducibility import RANDOM_SEED


ROOT = Path(__file__).resolve().parents[1]
INPUT_PARAMETERS = {
    "seed": RANDOM_SEED,
    "temperature": 0,
    "max_tokens": 1024,
    "enable_thinking": False,
    "stream": False,
    "response_format": {"type": "json_object"},
}
COMMENT_PARAMETERS = {**INPUT_PARAMETERS, "max_tokens": 2048}


def project_path(path):
    return ROOT / path


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def write_json(path, content):
    with path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
        f.write("\n")


def append_jsonl(path, record):
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def select_records(records, case_ids, all_cases, limit):
    available = list(dict.fromkeys(record["case_id"] for record in records))
    if case_ids:
        chosen = list(dict.fromkeys(case_ids))
    elif all_cases or limit is not None:
        chosen = available
    else:
        chosen = available[:1]
    missing = set(chosen) - set(available)
    if missing:
        raise SystemExit(f"Case IDs not found: {', '.join(sorted(missing))}")
    if limit is not None:
        if limit <= 0:
            raise SystemExit("--limit must be a positive number of cases")
        chosen = chosen[:limit]
    if not chosen:
        raise SystemExit("No cases selected")
    return [record for record in records if record["case_id"] in chosen]


def check_budget(request_count, max_requests):
    max_requests = request_count if max_requests is None else max_requests
    if not 0 <= request_count <= max_requests:
        raise SystemExit(f"Planned {request_count} requests; --max-requests is {max_requests}")
    return max_requests


def print_token_usage(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["response_model"] or record["requested_model"]].append(record)

    print("\nToken usage by model (current invocation):")
    if not grouped:
        print("  No recorded API usage.")
    for model, group in grouped.items():
        parts = []
        for field, label in (("prompt_tokens", "input"), ("completion_tokens", "output"), ("total_tokens", "total")):
            values = [
                record["usage"][field] for record in group
                if record["usage"] is not None and record["usage"].get(field) is not None
            ]
            value = f"{sum(values):,}" if values else "N/A"
            if len(values) < len(group):
                value += f" (reported {len(values)}/{len(group)})"
            parts.append(f"{label}={value}")
        print(f"  {model}: requests={len(group)}, {', '.join(parts)}")


def load_settings(dry_run):
    if dry_run:
        values = dotenv_values(ROOT / ".env.example")
    else:
        load_dotenv(ROOT / ".env")
        values = os.environ
    return {
        "api_key": values["DASHSCOPE_API_KEY"],
        "endpoint": f"{values['QWEN_BASE_URL'].rstrip('/')}/chat/completions",
        "base_model": values["BASE_MODEL"],
        "ref_model": values["REF_MODEL"],
        "source": ".env.example" if dry_run else "environment/.env",
    }


def start_run(stage, plans, settings, max_requests, dry_run, details):
    started_at = datetime.now(timezone.utc)
    run_id = started_at.strftime("%Y%m%dT%H%M%S_%fZ")
    output_root = ROOT / "artifacts"
    output_root /= f"previews/{stage}" if dry_run else {"input": "runs", "comment": "comments"}[stage]
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True)
    config = {
        "run_id": run_id,
        "stage": stage,
        "started_at": started_at.isoformat(),
        "mode": "dry_run" if dry_run else "live",
        "settings_source": settings["source"],
        "endpoint": settings["endpoint"],
        "base_model": settings["base_model"],
        "ref_model": settings["ref_model"],
        "request_count": len(plans),
        "max_requests": max_requests,
        "attempts_per_request": 1,
        "timeout_seconds": [10, 60],
        "planned_requests": plans,
        **details,
    }
    write_json(run_dir / "config.json", config)
    print(f"Saved {len(plans)} {stage} requests to {run_dir.relative_to(ROOT).as_posix()}")
    return run_dir, config


def set_parse_error(result, error):
    result.update(status="parse_error", error={"type": type(error).__name__, "message": str(error)})


def call_json(planned_request, config, run_dir, api_key):
    payload = planned_request["payload"]
    metadata = {
        "run_id": config["run_id"],
        **planned_request["metadata"],
        "attempt": planned_request.get("attempt", 1),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_model": payload["model"],
        "generation_parameters": {key: value for key, value in payload.items() if key not in ("model", "messages")},
        "response_source": "api",
    }
    raw = {**metadata, "http_status": None, "response_body": None, "error": None}
    start = perf_counter()
    try:
        response = requests.post(
            config["endpoint"],
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=tuple(config["timeout_seconds"]),
            allow_redirects=False,
        )
        raw.update(http_status=response.status_code, response_body=response.text.replace(api_key, "[REDACTED]"))
    except requests.RequestException as error:
        raw["error"] = {"type": type(error).__name__, "message": str(error).replace(api_key, "[REDACTED]")}
    raw["elapsed_seconds"] = round(perf_counter() - start, 6)

    # 原始响应先落盘，再读取其中的模型 JSON；凭据按原值脱敏。
    append_jsonl(run_dir / "raw_responses.jsonl", raw)
    result = {
        **metadata,
        "http_status": raw["http_status"],
        "elapsed_seconds": raw["elapsed_seconds"],
        "response_id": None,
        "response_model": None,
        "system_fingerprint": None,
        "finish_reason": None,
        "usage": None,
        "model_output": None,
        "status": "network_error",
        "error": raw["error"],
    }
    if raw["error"] is not None:
        return result
    if raw["http_status"] != 200:
        result.update(status="api_error", error={"type": "HTTPError", "message": f"HTTP {raw['http_status']}"})
        return result

    try:
        data = json.loads(raw["response_body"])
        choice = data["choices"][0]
        result.update(
            response_id=data.get("id"),
            response_model=data.get("model"),
            system_fingerprint=data.get("system_fingerprint"),
            finish_reason=choice["finish_reason"],
            usage=data.get("usage"),
        )
        model_text = choice["message"]["content"]
        if result["finish_reason"] == "length":
            result["status"] = "truncated"
        elif result["finish_reason"] == "content_filter":
            result["status"] = "filtered"
        elif not model_text:
            result["status"] = "empty_output"
        else:
            result.update(status="ok", model_output=json.loads(model_text))
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        set_parse_error(result, error)
    return result
