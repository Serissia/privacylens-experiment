"""Export batch comparisons, resource use, category breakdowns and figures."""

import csv
from datetime import datetime, timezone

from .common import project_path, write_json
from .statistics_data import load_batch, group_key


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



def display(value, percent=False):
    if value is None:
        return "N/A"
    return f"{value:.1%}" if percent else f"{value:,.2f}"


def fraction(numerator, denominator):
    return f"{numerator}/{denominator} ({numerator / denominator:.1%})" if denominator else "N/A (0/0)"


def render_report(report):
    lines = ["# 实验比较", "", "每个 S 编号是一份独立评价批次；同案例重复运行属于重复观测。隐私与任务指标来自所记录的模型裁判。", "",
             "| 批次 / 方法 | 案例 / 输出 | 案例泄露率 | 事实泄露率 | 任务完成率 | 显式拒绝率 | 平均处理秒 | 平均生成 token |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for row in report["comparison"]:
        lines.append(f"| {row['batch']} / {row['condition']} | {row['case_count']} / {row['output_count']} | "
                     f"{fraction(row['leaked_count'], row['sensitive_case_assessed_count'])} | "
                     f"{fraction(row['leaked_sensitive_item_count'], row['assessed_sensitive_item_count'])} | "
                     f"{fraction(row['helpfulness_success_count'], row['helpfulness_assessed_count'])} | "
                     f"{fraction(row['refusal_count'], row['valid_generation_count'])} | "
                     f"{display(row['mean_processing_seconds'])} | {display(row['mean_generation_tokens'])} |")
    lines.extend(["", "A2 处理时间包含源 A0 生成和本地过滤。token 是每次生成的已报告用量均值；金额未核算。处理时间不含模型初始化、裁判和绘图。", "",
                  "## 指标范围", "",
                  "| 批次 / 方法 | 隐私保护 recall | 隐私保护 precision | 正常任务完成率 | 误拒绝率 |",
                  "| --- | ---: | --- | ---: | --- |"])
    for row in report["comparison"]:
        lines.append(f"| {row['batch']} / {row['condition']} | {display(row['privacy_recall'], True)} | 未评价 | {display(row['benign_task_completion'], True)} | 未评价 |")
    lines.extend(["", "保护 recall = 未披露的敏感事实项 / 已评价敏感事实项；它不是裁判的检测召回率。precision 需要必需且允许分享事实的逐项评价；误拒绝需要拒绝合理性标注。N/A 表示有效分母为零。"])
    if report["categories"]:
        lines.extend(["", "## 按隐私类别比较", "",
                      "类别来自显式分类文件或评价标签中的显式类别标注，分类单位为案例。来源与映射快照见 report.json。", "",
                      "| 批次 / 方法 | 类别 | 案例 / 输出 | 案例泄露率 | 任务完成率 |",
                      "| --- | --- | ---: | ---: | ---: |"])
        for row in report["categories"]:
            category = str(row["category"]).replace("|", "&#124;").replace("\n", " ")
            lines.append(f"| {row['batch']} / {row['condition']} | {category} | {row['unique_case_count']} / {row['source_count']} | "
                         f"{fraction(row['leaked_count'], row['sensitive_case_assessed_count'])} | "
                         f"{fraction(row['helpfulness_success_count'], row['helpfulness_assessed_count'])} |")
    lines.extend(["", "## 有效覆盖与配置", "",
                  "| 批次 / 方法 | 有效生成 / 输出 | 隐私评价 / 输出 | 任务评价 / 输出 | token / 时间已报告数 | 生成提示 / 模型 / 过滤版本 |",
                  "| --- | ---: | ---: | ---: | ---: | --- |"])
    for row in report["comparison"]:
        lines.append(f"| {row['batch']} / {row['condition']} | {row['valid_generation_count']}/{row['output_count']} | "
                     f"{row['privacy_assessed_count']}/{row['output_count']} | {row['helpfulness_assessed_count']}/{row['output_count']} | "
                     f"{row['token_usage_reported_count']} / {row['processing_time_reported_count']} | {row['source_prompt_version']} / {row['source_model']} / {row['filter_version']} |")
    lines.extend(["", "## 本批实验开销与来源", "", "每个批次内真实请求去重；A2 复用 A0。多个批次可能引用同一请求，因此不对批次费用直接求和。裁判费用属于评估开销。", ""])
    for batch in report["batches"]:
        summary = batch["summary"]
        lines.extend([f"### {batch['id']}", "", f"来源：`{batch['summary_path']}`", "",
                      f"裁判模型：{summary['judge_models']}；裁判提示：{summary['judge_versions']}。", "",
                      "| 角色 | 模型 | 请求 | 已报告总 token | 用量覆盖 | 请求耗时和（秒） |",
                      "| --- | --- | ---: | ---: | ---: | ---: |"])
        for cost in batch["actual_costs"]["by_role_model"]:
            lines.append(f"| {cost['role']} | {cost['model']} | {cost['request_count']} | {display(cost['total_tokens'])} | "
                         f"{cost['usage_reported_counts']['total_tokens']}/{cost['request_count']} | {display(cost['latency']['sum_seconds'])} |")
    for batch in report["batches"]:
        progress = batch.get("pipeline_progress")
        if progress:
            lines.extend(["", f"## {batch['id']} 原计划完成情况", "",
                          "| 阶段 | 计划任务 | 已成功 | 失败待补 | 未执行 |",
                          "| --- | ---: | ---: | ---: | ---: |"])
            for stage, counts in progress["planned_tasks"].items():
                lines.append(f"| {stage} | {counts['planned']} | {counts['successful']} | {counts['failed_pending']} | {counts['not_started']} |")
            lines.extend(["", f"累计 API 尝试：{progress['api_attempts']} / {progress['max_requests']}；尝试状态：{progress['api_attempt_status_counts']}。", "",
                          "未保存最终结果的 interrupted_unknown 尝试已计入预算，用量未知。以上为原计划任务数；失败后的成功补跑仍属于同一任务。", ""])
    lines.extend(["", "详细计数、标签快照、版本与费用记录见 report.json；comparison.csv 可用于后续制表；启用类别分析时另有 categories.csv。", ""])
    return "\n".join(lines)

def run(args):
    import matplotlib

    matplotlib.use("Agg")
    output_dir = project_path(args.output_dir or f"artifacts/stats/{datetime.now(timezone.utc):%Y%m%dT%H%M%S_%fZ}")
    output_dir.mkdir(parents=True, exist_ok=True)
    batches = [load_batch(path, f"S{index}", getattr(args, "categories", None)) for index, path in enumerate(args.input, 1)]
    rows = [row for batch in batches for row in flatten_summary(batch["summary"], batch["id"])]
    comparison = []
    categories = []
    for batch in batches:
        costs = {group_key(row): row for row in batch["deployment"]}
        for group in batch["summary"]["groups"]:
            cost = costs[group_key(group)]
            facts = group["assessed_sensitive_item_count"]
            comparison.append({
                "batch": batch["id"], **{key: group.get(key) for key in GROUP_FIELDS},
                "case_count": group["unique_case_count"], "output_count": group["source_count"],
                "leakage_rate": group["leakage_rate"],
                "sensitive_item_leakage_rate": group["sensitive_item_leakage_rate"],
                "privacy_recall": 1 - group["sensitive_item_leakage_rate"] if facts else None,
                "privacy_precision": None, "false_refusal_rate": None,
                "helpfulness_success_rate": group["helpfulness_success_rate"],
                "benign_task_completion": group["cohorts"]["non_sensitive"]["helpfulness_success_rate"],
                "refusal_rate": group["refusal_rate"],
                "mean_processing_seconds": cost["mean_processing_seconds"],
                "mean_generation_tokens": cost["mean_generation_tokens"],
                "valid_generation_count": group["valid_generation_count"],
                "privacy_assessed_count": group["privacy_assessed_count"],
                "helpfulness_assessed_count": group["helpfulness_assessed_count"],
                "leaked_count": group["leaked_count"],
                "sensitive_case_assessed_count": group["sensitive_case_assessed_count"],
                "leaked_sensitive_item_count": group["leaked_sensitive_item_count"],
                "assessed_sensitive_item_count": facts,
                "helpfulness_success_count": group["helpfulness_success_count"],
                "refusal_count": group["refusal_count"],
                "token_usage_reported_count": cost["generation"]["usage_reported_counts"]["total_tokens"],
                "processing_time_reported_count": cost["processing"]["reported_count"],
            })
        categories.extend({"batch": batch["id"], **{key: value for key, value in row.items() if key != "cohorts"}}
                          for row in batch["categories"])
    report = {"schema_version": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
              "batches": batches, "comparison": comparison, "categories": categories}
    write_json(output_dir / "config.json", {"sources": [{"id": b["id"], "summary_path": b["summary_path"], "label_source": b["label_source"], "category_source": b["category_source"]} for b in batches]})
    write_json(output_dir / "statistics.json", rows)
    write_json(output_dir / "report.json", report)
    for name, table in (("comparison", comparison), ("categories", categories)):
        if name == "categories" and not table:
            (output_dir / "categories.csv").unlink(missing_ok=True)
            continue
        with (output_dir / f"{name}.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            if table:
                writer = csv.DictWriter(stream, fieldnames=list(table[0]))
                writer.writeheader()
                writer.writerows(table)
    (output_dir / "report.md").write_text(render_report(report), encoding="utf-8", newline="\n")

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
    print(f"Saved comparison CSVs, report, {len(rows)} statistics rows and 3 PNG figures to {output_dir}")
    return output_dir
