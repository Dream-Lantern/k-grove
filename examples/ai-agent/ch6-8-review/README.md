# 第 6～8 章：非站点教学示例

仅使用 Python 标准库，建议 Python 3.11～3.13。从仓库根目录运行：

```bash
python examples/ai-agent/ch6-8-review/evaluation_demo.py
python examples/ai-agent/ch6-8-review/copy_audit.py
python examples/ai-agent/ch6-8-review/structured_evidence_demo.py
python -m unittest discover -s examples/ai-agent/ch6-8-review -p "test_*.py" -v
```

- `evaluation_demo.py`：12 个计划运行单元、已知结果分母、完整配对、有限样本 Pass@k 与合成时间线。
- `copy_audit.py`：原始字节、仅预测 strip、Unicode 和 JSON 分层审计。相等时 `raw_first_diff_byte` 为 `null`，这是本地约定，与上游函数相等时返回长度的约定不同。
- `structured_evidence_demo.py`：程序单独提供模拟可信适配器记录，仅比对结构化字段，输出 PASS/FAIL/UNKNOWN；记录互相冲突时保守 UNKNOWN。

所有数据为教学合成数据。示例不读真实业务数据，不联网、不训练、不调用模型、不部署。不替换上游 `consistency_checker.py` 或旧 `revised_contracts.py`，不建立真实来源信任或业务证明。目录位于 `docs/` 外，不作为网站公开执行资源。

测试覆盖不同分母、缺失配对、单 Token 的 TPOT 未定义、预测与目标不同的处理规则、合法 null 与缺失值，以及时间/调用身份/证据来源的区别。测试通过仅表明这些有限案例符合教学契约。
