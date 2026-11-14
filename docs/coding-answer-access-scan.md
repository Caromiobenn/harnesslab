# 从已保存轨迹定位答案访问候选

`scan_coding_answer_access.py` 读取固定的全量报告和已评分试次的原生工具轨迹，生成可供复核的候选。
它只读取文件，不调用模型、不执行轨迹中的命令，也不改变官方分数。

```bash
python scripts/scan_coding_answer_access.py \
  --report /absolute/campaign-snapshot/report.json \
  --report-sha256 <report-sha256> \
  --output artifacts/coding-reports/answer-access-scan-v2
```

随着正式评测继续完成，在新快照上复用上次扫描：

```bash
python scripts/scan_coding_answer_access.py \
  --report /absolute/new-campaign-snapshot/report.json \
  --report-sha256 <new-report-sha256> \
  --resume /absolute/previous-scan/candidates.json \
  --resume-sha256 <previous-scan-sha256> \
  --output artifacts/coding-reports/answer-access-scan-v2-next
```

新输出目录保存 `candidates.json`。其中包含扫描规则、来源哈希、每条轨迹的哈希、工具事件位置、
候选输入及返回片段，以及已检查、缺失、复用和命中的数量。首次扫描读取全部已评分轨迹；
后续扫描先核对实际文件哈希，相同规则下复用未变化的结果，新增或变化的轨迹重新解析。
缺失轨迹保留为 `missing`，不能记作无命中。未评分尝试仍留在原始全量报告中，不进入这里的扫描分母。

当前规则包括 benchmark 名称、公开 oracle 数据集名称、参考解路径、根目录 `/tests` 下的测试文件
和评分日志路径。`/app/pyknotid/tests/test_knot.py`、`/tmp/tests/test_regex.py` 属于不同路径，
不会被根目录测试路径规则匹配。生成日历中出现 `Terminal-Bench` 仍可能形成候选，需要结合上下文判断。

Deep Agents 工具返回按 `run_id` 关联。mini 的同一 assistant 消息可能包含多个动作，因此保留这一轮
后续工具返回的窗口，并标记 `assistant_turn_window`；逐项复核时再确认具体动作与返回之间的关系。
超过 16,000 字符的返回保留片段、原长度和完整文本哈希，实际内容仍可从原始轨迹读取。

扫描命中不等于访问成功。确认案例需要继续核对实际下载或读取结果、具体任务内容、提交来源和官方
评分，例如 [图片参考解访问案例](case-image-oracle-access.md)。没有关键词命中，也不能证明轨迹中
不存在其他形式的参考材料访问。

[138 条轨迹的历史复核](coding-answer-access-review.md)使用较宽的旧规则；其 34 条候选和人工分类
保留原有口径。本脚本输出为 schema v2，增加公开 oracle 数据集名称识别，并收紧测试路径边界，
后续数量按新快照及实际规则单独报告。
