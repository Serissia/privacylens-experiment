# 最终动作提示

提示用于根据已有工具轨迹生成拟执行的最终动作。

## 模板与版本

- `base_system.txt`：公共系统提示，指定任务、JSON 输出结构与拒绝表示。
- `privacy_addition.txt`：A1 使用的情境隐私要求，围绕信息主体、来源、接收者与任务目的判断信息传递是否适当。
- `case_template.txt`：两组共用的案例正文，填入用户信息、任务、工具包名称、目标工具说明、已有轨迹与目标动作类型。
- `final_action_specs.json`：当前 pilot 使用的三个最终工具，包含所属工具包、功能、全部参数与返回值说明。
- `privacy_judge.txt`：逐项判断事实或其一部分是否泄露，并给出证据与简短理由。
- `helpfulness_judge.txt`：基于明确的 0–3 分标准评价功能性任务完成。
- `archive/privacy_addition_v1.txt`：A1 v1 的隐私段落归档。

| 条件 | 系统消息 | 用户消息 | 提示版本 |
| --- | --- | --- | --- |
| A0 | 公共系统提示 | 案例正文 | `a0_v1` |
| A1 | 公共系统提示 + 隐私增强段落 | 同一案例正文 | `a1_v2` |

生成提示版本位于 `experiment/build_prompts.py`，裁判版本位于 `experiment/run_comment.py`。公共提示、案例模板或工具说明更新时，同时更新两组版本；仅修改隐私增强段落时更新 A1 版本。

A1 v2 强调访问与分享授权的区别、事实和关系的语义披露、最少必要内容与原定受众。裁判版本为 `privacy_judge_v1` 与 `helpfulness_judge_v1`；裁判规则修改时更新对应版本。

## 输入与输出

生成输入取自 `data/pilot/inputs.json` 的明确任务字段。轨迹中的原始上下文完整进入案例正文；`case_id` 用于预览记录中的案例关联。

候选动作使用 `{"action": "工具名", "action_input": {工具参数}}`。拒绝使用 `{"action": "REFUSE", "action_input": {"reason": "原因"}}`，供后续人工评价记录拒绝和任务完成情况。

`artifacts/prompts/pilot_v2.jsonl` 每行保存一条请求预览，包括案例 ID、条件、提示版本、消息正文字符总数与完整 `messages`。每条请求包含一条系统消息和一条用户消息。`prompt_char_count` 按 Python `len` 累加消息正文字符数，供比较提示长度。

## 来源、改写与许可

方法与接口参考 [SALT-NLP/PrivacyLens](https://github.com/SALT-NLP/PrivacyLens)：

- `evaluation/get_final_action.py`：基于已有轨迹指定最终动作的提示构造方法。
- `data_construction/toolemu/prompts/agent/shared.py`：基础角色与隐私增强角色的对照思路。
- `data_construction/toolemu/tools/core_virtual_tools.py`：三个最终工具的名称、功能、参数及返回值说明；JSON 另加 `toolkit` 字段标明所属工具包。
- `evaluation/evaluate_final_action.py`：逐项泄露判断、案例 OR 聚合及独立 helpfulness 评价方法。

本项目自行编写公共模板与隐私增强段落，将任务组织为系统消息和用户消息，提供当前目标工具的接口说明，并使用直接输出 JSON 与 `REFUSE` 的格式。A1 将情境隐私原则展开为通用的信息传递要求。

裁判使用独立会话，批量判断一个动作对应的敏感事实，helpfulness 提示将官方等级展开为任务完成锚点，具体定义见 [评价协议](../docs/evaluation.md)。

工具接口内容沿用上游 MIT License，版权归 2024 Stanford Social and Language Technologies (SALT) lab，许可全文见 [LICENSE-PrivacyLens](LICENSE-PrivacyLens)。本项目原创内容遵循仓库根目录的 MIT License。
