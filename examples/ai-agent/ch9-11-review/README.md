# 第 9～11 篇定点修订：离线教学资源

第 11 篇是《六周系统学习路线与主动复习》，不是第 11 章。示例只依赖 Python 标准库，建议 Python 3.11～3.13；从仓库根目录运行：

```bash
python examples/ai-agent/ch9-11-review/audio_state.py
python examples/ai-agent/ch9-11-review/translation_contracts.py
python examples/ai-agent/ch9-11-review/controlled_plan.py
python -m unittest discover -s examples/ai-agent/ch9-11-review -p "test_*.py" -v
```

- `audio_state.py`：固定 16kHz、10ms、int16 单声道契约；列表/数组/小端字节/显式归一化浮点表示等价。RMS 高能量触发不确认人声。取消事件和播放器停止 ACK 分开，ACK 由测试构造，没有真实音频设备。内存状态不具备跨进程原子性、持久化去重或认证能力。
- `translation_contracts.py`：两个合成短章节、token→词元的窄词面统计和一次返修，过期 Hash/预算不足时拒绝。三个比率的分母是有跟踪概念的章节，空覆盖为 null；不是语义评分，不完整解析 Markdown，也不实际调用 Manager/模型。
- `controlled_plan.py`：固定 DemoLLM/Synthetic Dataset 的计划、合成批准、幂等和 SLO 字段判定。所有执行都是内存协议输入，`simulated=true`，不会连接 Endpoint 或实际压测。真实权限、用户身份与持久化事务要由业务服务提供。

各脚本把结果写到标准输出，不写业务文件。源码放在 `docs/` 外，不作为网站在线执行资源。真实模型、设备、付费调用和上游历史结果应与这些教学测试分开记录。
