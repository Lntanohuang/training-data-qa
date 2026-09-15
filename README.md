# 训练样本构造与标注质检 Skill

面向黄金样例、扩增样本和大规模训练/验证/测试/独立评测集构造，提供数据契约、生成约束、六维质检、专家抽检与版本封存流程。

## 使用

将 `skills/training-data-qa` 复制到 `~/.codex/skills/`，在 Codex 中调用 `$training-data-qa`。

```bash
python3 -m pip install -r requirements.txt
cd skills/training-data-qa
python3 scripts/dataset_qa.py build --input assets/example --out /tmp/training-data-demo
python3 scripts/dataset_qa.py review --input assets/example --out /tmp/training-data-demo
```

专家完成 `/tmp/training-data-demo/reviews.json` 后：

```bash
python3 scripts/dataset_qa.py seal --input assets/example --out /tmp/training-data-demo --version v1
```

- [Skill入口](skills/training-data-qa/SKILL.md)
- [完整输入请求](skills/training-data-qa/assets/example/request.md)
- [治理数据示例](skills/training-data-qa/assets/example/sources.jsonl)
- [任务模板](skills/training-data-qa/assets/example/template.json)
- [数据契约](skills/training-data-qa/references/contracts.md)
- [检查与验收](skills/training-data-qa/references/quality.md)

示例数据纯属虚构。脚本是内存型证据抽取适配器；不自动调用模型，也不自动批准黄金样例。语义事实、外部污染和真实身份脱敏需要任务专用工具/专家。规模超过近似扫描上限时明确阻断，生产接入需要磁盘索引和检索式近似去重。报告始终列出未检查项。

运行行为测试：`python3 -m unittest discover -s tests -v`。
