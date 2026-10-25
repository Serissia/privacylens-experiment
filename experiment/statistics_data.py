"""Read one evaluation batch and calculate comparable resource use."""

from collections import Counter, defaultdict
from statistics import mean, median

from .common import project_path, read_json, read_jsonl
from .run_comment import VALID_GENERATION_STATUSES, source_key, summarize


TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


def request_key(row):
    # 请求时间与尝试编号区分真实重跑，同一请求的存档副本只累计一次。
    return tuple(row[key] for key in ("run_id", "started_at", "case_id", "condition", "kind", "attempt"))


def unique_requests(rows):
    return list({request_key(row): row for row in rows if row["response_source"] == "api"}.values())


def timing(values):
    recorded = [value for value in values if value is not None]
    return {
        "record_count": len(values), "reported_count": len(recorded),
        "sum_seconds": sum(recorded) if recorded or not values else None,
        "mean_seconds": mean(recorded) if recorded else None,
        "median_seconds": median(recorded) if recorded else None,
    }


def api_metrics(rows):
    result = {
        "request_count": len(rows),
        "valid_response_count": sum(row["status"] in VALID_GENERATION_STATUSES for row in rows),
        "status_counts": dict(Counter(row["status"] for row in rows)),
        "usage_reported_counts": {},
        "latency": timing([row.get("elapsed_seconds") for row in rows]),
    }
    for field in TOKEN_FIELDS:
        values = [row["usage"][field] for row in rows if row["usage"] is not None and row["usage"].get(field) is not None]
        result[field] = sum(values) if values or not rows else None
        result["usage_reported_counts"][field] = len(values)
    cached = [row["usage"]["prompt_tokens_details"]["cached_tokens"] for row in rows
              if row["usage"] is not None and "cached_tokens" in row["usage"].get("prompt_tokens_details", {})]
    result["cached_prompt_tokens"] = sum(cached) if cached else None
    result["cached_usage_reported_count"] = len(cached)
    return result


def actual_costs(rows):
    rows = unique_requests(rows)
    groups = defaultdict(list)
    for row in rows:
        role = "generation" if row["kind"] == "input" else f"judge_{row['kind']}"
        groups[(role, row["response_model"] or row["requested_model"])].append(row)
    return {
        "total": api_metrics(rows),
        "by_role_model": [{"role": role, "model": model, **api_metrics(group)}
                          for (role, model), group in sorted(groups.items())],
    }


def load_sources(paths):
    return {
        (project_path(path).resolve().as_posix(), line): {
            **row, "source_path": project_path(path).resolve().as_posix(), "source_line": line,
        }
        for path in paths
        for line, row in enumerate(read_jsonl(project_path(path)), 1)
    }


def load_judges(paths):
    rows = [
        {**row, "source_path": project_path(row["source_path"]).resolve().as_posix()}
        for path in paths for row in read_jsonl(project_path(path))
    ]
    keys = [(*source_key(row), row["kind"]) for row in rows if row["status"] == "ok"]
    if len(keys) != len(set(keys)):
        raise ValueError("Separate repeated successful judgments into different report cohorts")
    return rows


def deployment_costs(sources):
    groups = defaultdict(list)
    for row in sources.values():
        groups[(row["condition"], row["prompt_version"], row["requested_model"], row.get("filter_version"))].append(row)
    rows = []
    for (condition, prompt, model, filter_version), group in sorted(groups.items()):
        generated = []
        for row in group:
            if condition == "A2":
                source = row["source_a0"]
                path = project_path(source["path"]).resolve().as_posix()
                a0 = sources[(path, source["line"])] if (path, source["line"]) in sources else read_jsonl(project_path(path))[source["line"] - 1]
                assert a0["condition"] == "A0" and a0["case_id"] == row["case_id"] and a0["run_id"] == source["run_id"]
                generated.append(a0)
            else:
                generated.append(row)
        generation = api_metrics(generated)
        filtering = timing([row["filter_elapsed_seconds"] for row in group]) if condition == "A2" else timing([])
        times = (generation["latency"]["sum_seconds"], filtering["sum_seconds"])
        processing = timing([
            source["elapsed_seconds"] + (row["filter_elapsed_seconds"] if condition == "A2" else 0)
            if source.get("elapsed_seconds") is not None and (condition != "A2" or row.get("filter_elapsed_seconds") is not None)
            else None
            for source, row in zip(generated, group)
        ])
        rows.append({
            "condition": condition, "prompt_version": prompt, "model": model, "filter_version": filter_version,
            "output_count": len(group), "generation": generation, "filtering": filtering, "processing": processing,
            "online_seconds_sum": sum(times) if None not in times else None,
            "additional_generation_requests": 0 if condition == "A2" else generation["request_count"],
        })
    return rows



def group_key(row):
    return tuple(row.get(key) for key in ("condition", "source_prompt_version", "source_model", "filter_version"))


def load_batch(path, batch_id, categories_path=None):
    summary_path = project_path(path)
    config_path = summary_path.parent / "config.json"
    config = read_json(config_path)
    all_sources = load_sources(config["input_paths"])
    # Selection includes invalid outputs and is independent of successful judgments.
    sources = {
        (project_path(row["source_path"]).resolve().as_posix(), row["source_line"]):
        all_sources[(project_path(row["source_path"]).resolve().as_posix(), row["source_line"])]
        for row in config["selected_sources"]
    }
    judges = load_judges([summary_path.parent / "results.jsonl"])
    assert all(source_key(row) in sources for row in judges)
    label_path = summary_path.parent / "labels.json"
    if not label_path.exists():
        label_path = project_path(config["labels_path"])
    labels = {row["case_id"]: row for row in read_json(label_path)}
    summary = summarize(list(sources.values()), judges, config["request_count"], labels)
    if summary != read_json(summary_path):
        raise ValueError("Recomputed summary differs from saved summary; check source records and labels")
    case_ids = sorted({row["case_id"] for row in sources.values()})
    if categories_path:
        supplied = read_json(project_path(categories_path))
        category_mapping = {case_id: supplied[case_id] for case_id in case_ids}
        category_source = project_path(categories_path).as_posix()
    elif categories_path == "":
        category_mapping = {}
        category_source = None
    else:
        category_mapping = {
            case_id: labels[case_id]["privacy_category"] for case_id in case_ids
            if labels[case_id].get("category_source") not in (None, "", "seed.data_type")
            and labels[case_id].get("privacy_category")
        }
        category_source = "evaluation label snapshot" if category_mapping else None
    if category_mapping and (set(category_mapping) != set(case_ids) or not all(category_mapping.values())):
        raise ValueError("Category mapping must contain a nonempty category for every selected case")
    categories = []
    grouped = defaultdict(list)
    if category_mapping:
        for row in sources.values():
            if labels[row["case_id"]]["sensitive_info_items"]:
                grouped[category_mapping[row["case_id"]]].append(row)
    for category, group in sorted(grouped.items()):
        keys = {source_key(row) for row in group}
        assessments = [row for row in judges if source_key(row) in keys]
        category_summary = summarize(group, assessments, 2 * len(group), labels)
        categories.extend({"category": category, **row} for row in category_summary["groups"])
    deployments = deployment_costs(sources)
    for row in deployments:
        row["source_prompt_version"] = row.pop("prompt_version")
        row["source_model"] = row.pop("model")
        row["mean_processing_seconds"] = row["processing"]["mean_seconds"]
        row["mean_generation_tokens"] = ratio(row["generation"]["total_tokens"], row["generation"]["usage_reported_counts"]["total_tokens"])
    api_rows = [*sources.values(), *judges]
    for row in sources.values():
        if row["condition"] == "A2":
            origin = row["source_a0"]
            api_rows.append(read_jsonl(project_path(origin["path"]))[origin["line"] - 1])
    return {
        "id": batch_id, "summary_path": summary_path.as_posix(),
        "summary": summary, "deployment": deployments,
        "categories": categories, "actual_costs": actual_costs(api_rows),
        "label_source": label_path.as_posix(),
        "category_source": category_source,
        "category_mapping": category_mapping,
        "labels": [labels[key] for key in sorted({row["case_id"] for row in sources.values()})],
        "optional_metrics": {"privacy_precision": None, "false_refusal_rate": None},
        "optional_metric_status": {
            "privacy_precision": "not_evaluated: required allowed facts need output-level assessment",
            "false_refusal_rate": "not_evaluated: refusal appropriateness needs output-level assessment",
        },
    }
