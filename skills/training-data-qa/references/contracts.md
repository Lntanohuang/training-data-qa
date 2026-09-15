# 数据契约

## 输入目录

- `sources.jsonl`：每行 `source_id, group_id, text, evidence, label, provenance, licensed, deidentified`。`group_id` 必须是关系连通后的隔离组；`evidence` 是来源中的原文。来源记录业务实体关系时，接入层先合并共享实体的组。
- `template.json`：`task_id, prompt, seed, split_ratios, target_labels, distribution_tolerance, review_per_stratum, max_synthetic_ratio, near_duplicate_limit`。示例采用证据抽取，标签来自治理数据，不让模型猜标签。
- `rules.json`：`version, forbidden_terms`。真实任务另附业务规则、优先级、例外、拒答条件、事实核验标准及验收门槛；禁止词仅是规则适配器示例。
- `golden.jsonl`：样本格式，`kind=golden`，专家批准后才加入；空文件表示尚无黄金，不代表已验证。黄金若参与开发只能属于训练/验证用途，不能再次作为独立评测题。
- `model_outputs.jsonl`：可选样本格式的候选扩增结果；缺省为空。所有合成记录需要 `parent_id` 和生成记录。只允许从训练父样本导入扩增。

## 样本格式

`sample.schema.json` 定义通用结构。`split` 为 `train / validation / test / evaluation`；validation 用于调参，test 用于冻结后测试，evaluation 用于独立验收与持续评测。

`evidence` 原文包含检查只证明来源中有该文字。推理题需逐个事实/论证链核对；开放回答需拆解主张，并记录支持、反驳或未找到证据。

本示例 `answer` 必须等于 evidence，且 prompt 中必须包含当前来源文本。真实接入应保存结构化消息、输出 Schema、证据定位页码/行号以及主张映射。

生成记录 `generator` 包含 `model_version, prompt_hash, seed, transform`；真实业务补充运行ID、参数和工具链版本。来源 `provenance` 应使用稳定文档版本URI，不能用会变化的首页。

## 输出目录

- `dataset.jsonl`、`train.jsonl`、`validation.jsonl`、`test.jsonl`、`evaluation.jsonl`：候选总集及分集。
- `issues.jsonl`：错误码、严重度、样本ID和说明；坏行按行号定位。
- `report.json`：计数、分布、检查覆盖和未覆盖项、数据/输入指纹。
- `annotation_tasks.jsonl`：按集合/标签/kind分层随机抽样，加全部合成和黄金样本；只给问题与来源，候选答案在评审记录中单独核对。
- `reviews.json`：专家填写 `{ "sample_id": {"decision":"approve|reject", "reviewer":"专家标识", "notes":"证据与规则依据"} }`。两人独立盲审及裁决按业务风险执行，生产环境接入有身份鉴别的标注系统；此文件仅是演示接口，无法验证签名真实性。
- `releases/<version>/`：不可覆盖的四类数据、报告、评审任务、评审记录、Schema、脚本和全部输入；`manifest.json` 保存逐文件 SHA-256。
