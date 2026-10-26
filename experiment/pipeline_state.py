"""Durable task attempts, cumulative budget and pipeline progress."""

import hashlib
import json
import os
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import distributions

from .common import ROOT, read_json

SUCCESS = {"ok", "refused"}


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def atomic_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def environment_signature():
    files = [ROOT / "run.py", *sorted((ROOT / "experiment").glob("*.py")),
             *sorted((ROOT / "prompts").glob("*.txt")), ROOT / "prompts/final_action_specs.json",
             ROOT / "requirements.txt", ROOT / "requirements-lock.txt"]
    files.extend(sorted(path for path in (ROOT / "models").rglob("*") if path.is_file()))
    return {"files": {p.relative_to(ROOT).as_posix(): digest(p) for p in files},
            "packages": dict(sorted((d.metadata["Name"], d.version) for d in distributions()))}


@contextmanager
def exclusive_run(directory):
    import msvcrt
    with (directory / "resume.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise SystemExit("This pipeline is already running") from None
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def read_attempts(directory):
    return [read_json(path) for path in sorted((directory / "attempts").glob("*.json"))]


class PipelineState:
    def __init__(self, directory, config):
        self.directory = directory
        self.config = config
        self.attempts = read_attempts(directory)
        self.successes = {r["task_id"]: r for r in self.attempts if r["status"] in SUCCESS}

    def save_config(self):
        atomic_json(self.directory / "config.json", self.config)

    def progress(self):
        latest = {r["task_id"]: r for r in self.attempts}
        stages = {}
        for stage, count in self.config["planned_tasks"].items():
            attempted = {key: r for key, r in latest.items() if r["pipeline_stage"] == stage}
            completed = sum(key in self.successes for key in attempted)
            stages[stage] = {"planned": count, "successful": completed,
                             "failed_pending": len(attempted) - completed,
                             "not_started": count - len(attempted)}
        api = [r for r in self.attempts if r["pipeline_stage"] in ("input", "comment")]
        progress = {"planned_tasks": stages, "api_attempts": len(api),
                    "api_attempt_status_counts": dict(Counter(r["status"] for r in api)),
                    "max_requests": self.config["max_requests"],
                    "remaining_budget": self.config["max_requests"] - len(api),
                    "minimum_required_budget": self.minimum_required_budget(),
                    "stat_complete": self.config.get("stat_complete", False)}
        atomic_json(self.directory / "progress.json", progress)
        return progress

    def minimum_required_budget(self):
        used = sum(r["pipeline_stage"] in ("input", "comment") for r in self.attempts)
        done = sum(r["pipeline_stage"] in ("input", "comment") for r in self.successes.values())
        return used + self.config["planned_requests"] - done

    def execute(self, task_id, stage, metadata, callback):
        if task_id in self.successes:
            return self.successes[task_id]
        is_api = stage in ("input", "comment")
        used = sum(r["pipeline_stage"] in ("input", "comment") for r in self.attempts)
        if is_api and used >= self.config["max_requests"]:
            raise SystemExit("Cumulative request budget exhausted; resume with a larger --max-requests")
        attempt = 1 + sum(r["task_id"] == task_id for r in self.attempts)
        record = {**metadata, "task_id": task_id, "pipeline_stage": stage, "attempt": attempt,
                  "started_at": datetime.now(timezone.utc).isoformat(),
                  "status": "interrupted_unknown" if is_api else "filter_error",
                  "response_source": "api" if is_api else "local_derivation",
                  "response_model": None, "usage": None, "elapsed_seconds": None,
                  "error": {"type": "IncompleteAttempt", "message": "No final result saved"}}
        path = self.directory / "attempts" / f"{task_id}__{attempt:04d}.json"
        atomic_json(path, record)
        self.attempts.append(record)
        self.progress()
        try:
            result = callback(attempt)
        except Exception as error:
            record["error"] = {"type": type(error).__name__, "message": "Execution interrupted; inspect stage logs"}
            atomic_json(path, record)
            raise
        record.update(result, task_id=task_id, pipeline_stage=stage, attempt=attempt)
        atomic_json(path, record)
        if record["status"] in SUCCESS:
            self.successes[task_id] = record
        self.progress()
        if record["status"] not in SUCCESS:
            raise SystemExit(f"{task_id} failed ({record['status']}); resume this pipeline to retry")
        return record

    def materialize(self, stage, task_ids):
        directory = self.directory_for(stage)
        atomic_text(directory / "results.jsonl", "".join(
            json.dumps(self.successes[task_id], ensure_ascii=False) + "\n" for task_id in task_ids))
        self.config.setdefault("result_hashes", {})[stage] = digest(directory / "results.jsonl")
        self.save_config()
        return directory

    def directory_for(self, stage):
        from pathlib import Path
        return Path(self.config["stage_directories"][stage])
