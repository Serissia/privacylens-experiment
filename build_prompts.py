"""Build paired A0/A1 request previews from the pilot inputs."""

import json
from pathlib import Path


def main():
    project_dir = Path(__file__).resolve().parent
    prompt_dir = project_dir / "prompts"
    cases = json.loads((project_dir / "data/pilot/inputs.json").read_text(encoding="utf-8"))
    tool_specs = json.loads((prompt_dir / "final_action_specs.json").read_text(encoding="utf-8"))
    base_system = (prompt_dir / "base_system.txt").read_text(encoding="utf-8").strip()
    privacy_addition = (prompt_dir / "privacy_addition.txt").read_text(encoding="utf-8").strip()
    case_template = (prompt_dir / "case_template.txt").read_text(encoding="utf-8").strip()
    # A0 使用公共系统提示；A1 在其末尾用空行接上隐私增强段落。
    system_prompts = {
        "A0": base_system,
        "A1": f"{base_system}\n\n{privacy_addition}",
    }
    prompt_versions = {"A0": "a0_v1", "A1": "a1_v1"}

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
                "prompt_version": prompt_versions[condition],
                "prompt_char_count": sum(len(message["content"]) for message in messages),
                "messages": messages,
            })

    output_path = project_dir / "artifacts/prompt_preview.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # JSONL 每行保存一组消息，以及对应的案例、条件、版本和正文字符数。
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for preview in previews:
            f.write(json.dumps(preview, ensure_ascii=False) + "\n")

    print(f"Wrote {output_path.relative_to(project_dir).as_posix()}")
    print(f"Prepared {len(previews)} request previews from {len(cases)} pilot cases.")


if __name__ == "__main__":
    main()
