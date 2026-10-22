"""Export comment summaries as tables and figures."""

from datetime import datetime, timezone

from .common import project_path, read_json, write_json


GROUP_FIELDS = ("condition", "source_prompt_version", "source_model", "filter_version")
COLORS = {"A0": "#3973AC", "A1": "#27836D", "A2": "#CB8735"}


def flatten_summary(summary, summary_id):
    rows = []
    for group in summary["groups"]:
        overall = {key: value for key, value in group.items() if key not in (*GROUP_FIELDS, "cohorts")}
        for cohort, metrics in {"all": overall, **group["cohorts"]}.items():
            values = dict(metrics)
            score_counts = values.pop("helpfulness_score_counts")
            rows.append({
                "summary_id": summary_id,
                **{field: group.get(field) for field in GROUP_FIELDS},
                "privacy_judge_models": ", ".join(summary["judge_models"]["privacy"]),
                "helpfulness_judge_models": ", ".join(summary["judge_models"]["helpfulness"]),
                "privacy_judge_versions": ", ".join(summary["judge_versions"]["privacy"]),
                "helpfulness_judge_versions": ", ".join(summary["judge_versions"]["helpfulness"]),
                "cohort": cohort,
                **values,
                **{f"helpfulness_score_{score}_count": count for score, count in enumerate(score_counts)},
                **{
                    f"{stage}_coverage": metrics[numerator] / metrics[denominator] if metrics[denominator] else None
                    for stage, numerator, denominator in (
                        ("generation", "valid_generation_count", "source_count"),
                        ("privacy", "privacy_assessed_count", "source_count"),
                        ("helpfulness", "helpfulness_assessed_count", "source_count"),
                    )
                },
            })
    return rows


def draw_metrics(rows, panels, title, output_path):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import PercentFormatter

    fig, axes = plt.subplots(
        1, len(panels), figsize=(5.2 * len(panels), max(3.6, 1.0 * len(rows) + 2.0)),
        sharey=True, squeeze=False,
    )
    labels = [
        f"{row['summary_id']} / {row['condition']} / {row['source_prompt_version']}\n"
        f"filter={row['filter_version'] if row['filter_version'] is not None else 'null'}\n"
        f"{row['source_model']} / {row['cohort']} (n={row['source_count']})"
        for row in rows
    ]
    for axis, (metric, subtitle, numerator, denominator, upper) in zip(axes[0], panels):
        for index, row in enumerate(rows):
            value = row[metric]
            color = COLORS.get(row["condition"], "#7562A5")
            if value is None:
                axis.text(0.02 * upper, index, "N/A", va="center", color="#777777")
                continue
            axis.barh(index, value, height=0.5, color=color, alpha=0.85)
            # 每个比例同时展示分子与分母，均分展示有效评分数量。
            text = (
                f"{value:.0%}  ({row[numerator]}/{row[denominator]})"
                if numerator else f"{value:.2f}  (n={row[denominator]})"
            )
            axis.text(value + 0.02 * upper, index, text, va="center", fontsize=9)
        axis.set_title(subtitle, fontsize=11, pad=14)
        axis.set_xlim(0, upper * 1.5)
        axis.set_xticks([0, upper / 2, upper])
        if upper == 1:
            axis.xaxis.set_major_formatter(PercentFormatter(1))
        axis.set_yticks(range(len(rows)), labels, fontsize=8)
        axis.set_axisbelow(True)
        axis.grid(axis="x", color="#E5E8EB", linewidth=0.7)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.tick_params(axis="y", length=0, pad=8)
        if not rows:
            axis.text(0.5, 0.5, "No sensitive cases", transform=axis.transAxes, ha="center")
    axes[0, 0].set_ylim(max(len(rows), 1) - 0.5, -0.5)
    fig.suptitle(title, fontsize=15)
    fig.text(0.5, 0.015, "n counts generated outputs; repeated case IDs are repeated observations. N/A = zero denominator.", ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 0.94))
    fig.savefig(output_path.with_suffix(".png"), dpi=200, bbox_inches="tight")
    plt.close(fig)


def run(args):
    import matplotlib

    matplotlib.use("Agg")
    output_dir = project_path(args.output_dir or f"artifacts/stats/{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}")
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    sources = []
    for index, path in enumerate(args.input, 1):
        summary = read_json(project_path(path))
        summary_id = f"S{index}"
        sources.append({
            "summary_id": summary_id,
            "summary_path": project_path(path).as_posix(),
            "schema_version": summary["schema_version"],
            "judge_models": summary["judge_models"],
            "judge_versions": summary["judge_versions"],
        })
        # 每份汇总保留各自的版本、模型和分母，独立展示。
        rows.extend(flatten_summary(summary, summary_id))
    write_json(output_dir / "config.json", {"sources": sources})
    write_json(output_dir / "statistics.json", rows)

    cohorts = [row for row in rows if row["cohort"] != "all" and row["source_count"]]
    sensitive = [row for row in cohorts if row["cohort"] == "sensitive"]
    draw_metrics(sensitive, [
        ("leakage_rate", "Case leakage", "leaked_count", "sensitive_case_assessed_count", 1),
        ("adjusted_leakage_rate", "Leakage among helpful actions", "adjusted_leaked_count", "sensitive_helpful_paired_count", 1),
        ("sensitive_item_leakage_rate", "Sensitive fact leakage", "leaked_sensitive_item_count", "assessed_sensitive_item_count", 1),
    ], "Privacy | sensitive cases", output_dir / "privacy")
    draw_metrics(cohorts, [
        ("mean_helpfulness", "Mean helpfulness (0-3)", None, "helpfulness_assessed_count", 3),
        ("helpfulness_success_rate", "Helpfulness >= 2", "helpfulness_success_count", "helpfulness_assessed_count", 1),
        ("refusal_rate", "Refusal among valid outputs", "refusal_count", "valid_generation_count", 1),
    ], "Task completion | separate cohorts", output_dir / "helpfulness")
    draw_metrics(cohorts, [
        ("generation_coverage", "Valid generations", "valid_generation_count", "source_count", 1),
        ("privacy_coverage", "Privacy assessments", "privacy_assessed_count", "source_count", 1),
        ("helpfulness_coverage", "Helpfulness assessments", "helpfulness_assessed_count", "source_count", 1),
        ("sensitive_item_assessment_coverage", "Sensitive facts assessed", "assessed_sensitive_item_count", "total_sensitive_item_count", 1),
    ], "Coverage | all selected outputs", output_dir / "coverage")
    print(f"Saved {len(rows)} statistics rows and 3 PNG figures to {output_dir}")
    return output_dir
