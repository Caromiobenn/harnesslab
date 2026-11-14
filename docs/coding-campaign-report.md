# 汇总全量实验的所有批次

`scripts/report_coding_campaign.py` 从最新冻结的 `study.json` 追溯前置批次、六题试验批次和两次运行适配调整保留的批次，统一生成 `report.json`、`trials.csv`、`groups.csv`、`campaign.json`。

```bash
python scripts/report_coding_campaign.py \
  --study /absolute/runtime/artifacts/expansions/run/study.json \
  --study-sha256 <frozen-study-sha256> \
  --regrades /absolute/unchanged-submission-regrades/results.json \
  --output artifacts/coding-reports/campaign-snapshot
```

同一前置批次可能被多个后续批次引用，只读入一次。报告也读取已退役批次的结束记录，保留零模型调用的环境失败和无分数尝试的已观测成本。一个实验单元出现两个官方分数时直接报错，沿用既有报告的单次采样口径。原始运行错误、固定提交的重新评分、运行适配版本和不完整 token 用量继续分别展示。

`campaign.json` 记录整个任务矩阵的应有单元数、已结束单元数、已评分单元数及每个输入结果文件的 SHA-256。`unscored_cells` 包括尚未结束和已结束但缺少分数的单元，不表示它们都在运行或都失败。报告只读取已有实验材料，不启动模型、评测环境或重新评分。

每个快照使用新的输出目录。后续批次发布后，改为最新 study 的路径和哈希即可纳入新批次；保留旧快照以供核对。

已冻结的[165 单元阶段快照](coding-progress-165.md)包含成绩覆盖、产物核验、LangSmith 读回和答案访问候选复核。
