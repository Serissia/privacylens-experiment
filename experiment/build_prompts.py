"""Build paired A0/A1 request previews from the pilot inputs."""

import json

from .common import ROOT, project_path, read_json


DEFAULT_OUTPUT = "artifacts/prompts/pilot_v2.jsonl"
PROMPT_VERSIONS = {"A0": "a0_v1", "A1": "a1_v2"}


def run(args):
    prompt_dir = ROOT / "prompts"
    cases = read_json(project_path(args.input))
    tool_specs = read_json(prompt_dir / "final_action_specs.json")
    base_system = (prompt_dir / "base_system.txt").read_text(encoding="utf-8").strip()
    privacy_addition = (prompt_dir / "privacy_addition.txt").read_text(encoding="utf-8").strip()
    case_template = (prompt_dir / "case_template.txt").read_text(encoding="utf-8").strip()
    # A0 使用公共系统提示；A1 在其末尾用空行接上隐私增强段落。
    system_prompts = {
        "A0": base_system,
        "A1": f"{base_system}\n\n{privacy_addition}",
    }

    previews = []
    for case in cases:
        # 将案例字段填入正文模板，并按目标动作名称选取工具接口说明。
        user_prompt = case_template.format(
            user_name=case["user_name"],
            user_email=case["user_email"],
            user_instruction=case["user_instruction"],
            toolkits=json.dumps(case["toolkits"], ensure_ascii=False),
            final_action_specification=json.dumps(
                tool_specs[case["final_action"]], ensure_ascii=False, indent=2
            ),
            executable_trajectory=case["executable_trajectory"],
            final_action=case["final_action"],
        )
        for condition, system_prompt in system_prompts.items():
            # 两组复用同一份案例正文，分别组成 system 和 user 两条消息。
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            previews.append({
                "case_id": case["case_id"],
                "condition": condition,
                "prompt_version": PROMPT_VERSIONS[condition],
                "prompt_char_count": sum(len(message["content"]) for message in messages),
                "messages": messages,
            })

    output_path = project_path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # JSONL 每行保存一组消息，以及对应的案例、条件、版本和正文字符数。
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for preview in previews:
            f.write(json.dumps(preview, ensure_ascii=False) + "\n")

    print(f"Wrote {args.output}")
    print(f"Prepared {len(previews)} request previews from {len(cases)} pilot cases.")
