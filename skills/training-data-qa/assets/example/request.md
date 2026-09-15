# 可直接使用的输入请求

使用 $training-data-qa 处理本目录的输入包。任务为业务规则原文抽取，标签为“时限”和“资格”。先构造种子与训练/验证/测试/独立评测候选集，执行质检并输出专家抽检任务。专家尚未审批，请保持候选状态。

- 治理数据：`sources.jsonl`，16条纯虚构政策，8个来源组；许可和脱敏标记仅用于演示。
- 任务模板：`template.json`，四集合目标比例50%/20%/15%/15%，标签各50%。小样本按组哈希不保证比例，示例用于跑通流程，不用于评估模型效果。
- 黄金样例：`golden.jsonl`，初始为空，待专家把正确种子确认为黄金；同一条应替换kind而不是重复追加。
- 标注规则与业务约束：`rules.json`，完整抽取原文，不补充不存在的信息，禁止输出所列敏感字段。
- 模型输出：`model_outputs.jsonl`，初始为空。可加入训练父样本的改写/难例候选，必须符合 `../sample.schema.json` 并带生成记录。
- 规模：第一轮16条；如需扩增至1000条，先评估来源多样性与每父样本上限，提出缺口，不声称当前16条足以覆盖真实分布。

单条治理输入示例：

```json
{"source_id":"policy-001-0","group_id":"policy-001","text":"退款申请须在签收后七日内提交。","evidence":"退款申请须在签收后七日内提交。","label":"时限","provenance":"synthetic://policies/v1/policy-001/0","licensed":true,"deidentified":true}
```

扩增请求示例：“仅改写 train 样本的问题表达，保留来源正文、答案和集合；每个父样本最多2条，生成类型为 augmented。另生成边界难例候选，若超出抽取型契约，先扩展 Schema 和事实规则再导入。”

专家输出示例（真实使用须由实际专家填写，不能复制示例作为批准）：

```json
{"seed-policy-001-0":{"decision":"approve","reviewer":"expert-id","notes":"依据文档v1核对原文和时限标签，无额外推断。"}}
```

完整模型输出示例（可作为 model_outputs.jsonl 中一行；生成信息为演示占位，真实使用必须记录实际值）：

```json
{"id": "seed-policy-002-0-aug-1", "task_id": "policy-evidence-extraction", "source_id": "policy-002-0", "group_id": "policy-002", "split": "train", "prompt": "请找出材料明确规定的要求。依据以下资料提取完整规则原文：退款申请须在签收后七日内提交。", "answer": "退款申请须在签收后七日内提交。", "evidence": "退款申请须在签收后七日内提交。", "label": "时限", "kind": "augmented", "parent_id": "seed-policy-002-0", "generator": {"model_version": "example-model-v1", "prompt_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "seed": 42, "transform": "question-paraphrase"}}
```
