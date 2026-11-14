# 165 单元阶段快照

冻结时间为 2026-11-14 13:03:29 UTC。HIGH、每个条件独立一次的完整计划仍为
89 题 × 5 组 × 2 种网络，共 890 个单元。本快照有 165 个已评分单元、127 个通过，
累计保存 175 条结束记录。未评分的 725 个单元包括仍在运行和尚未启动的部分。

| 组别 | 禁网通过 / 已评分 | 联网通过 / 已评分 |
| --- | ---: | ---: |
| mini | 14 / 17 | 15 / 17 |
| Deep Agents 默认 | 12 / 17 | 12 / 17 |
| 普通自我复查 | 13 / 17 | 11 / 16 |
| transcript rubric | 12 / 16 | 13 / 16 |
| evidence rubric | 12 / 16 | 13 / 16 |

这是进度表。各组完成题目尚不完全相同，效果和成本比较使用同题配对报告。
13 个单元沿用已保存提交的零模型复评得分，原始无分数记录与消耗保留。

## 轨迹、指标和监控核验

165 条已评分记录均通过轨迹存在性、提交哈希、官方测试、调用和 token 指标、输出长度、
耗时及实例回收检查，没有发现缺项或不一致。提交形态为 125 份归档、31 份单文件，
另有 9 条记录明确保存了“目标文件未生成”的事实。

用量完整性分为 102 条完整、29 条存在未完整返回的请求、34 条 mini 未报告请求启动计数。
后者仍有已收到响应的 token 指标；三类均保存已观测消耗，不把缺失部分填成零。
131 条 Deep Agents 记录已在 LangSmith 远端读回，结束状态和反馈指标全部一致。

## 公开答案访问候选的增量复核

扫描覆盖 165 条轨迹，复用 152 条哈希未变的扫描结果。共得到 38 条候选试次、57 个工具动作，
已有 41 个动作的输入、返回片段和轨迹哈希与上一账本一致；新增 16 个动作逐项复核：

- 4 次查看评分日志目录，返回为空。
- 11 次保留任务原始 C++ 文件中的 benchmark canary 注释；已对照环境自带的三个源文件。
- 1 次统计两个公开源文件中的 canary 注释出现次数。

新增候选没有增加已确认的参考解访问试次。累计确认案例仍为
[图片任务的联网 mini](case-image-oracle-access.md)。关键词候选、实际取得参考内容、官方得分
分别记录；扫描候选数不作为 reward hacking 发生率。

## 冻结证据

以下路径均位于服务器 `harnesslab/artifacts/worktrees` 下，已有本地备份：

| 材料 | 路径 | SHA-256 |
| --- | --- | --- |
| 完整报告 | `tb21-campaign-report/artifacts/coding-reports/campaign-20261114T130329Z/report.json` | `56ea4453c34b198099993fad67185b06ff3e52be3efdbaf1f09604fe295da438` |
| 产物核验 | `tb21-campaign-report/artifacts/coding-reports/artifact-audit-20261114T130456Z/audit.json` | `1204892c0447e1de84bedf2efdfe43f229ae3beb81930c6e615e3dbb2d57eb05` |
| LangSmith 核验 | `tb21-campaign-report/artifacts/coding-reports/langsmith-audit-20261114T130500Z/audit.json` | `fc55b9d99b93baa8c01d3b6de89acc9b3c4be6391fe6e76ece64fae8a141915e` |
| 答案访问扫描 | `tb21-answer-access-scan/artifacts/coding-reports/answer-access-scan165-20261114/candidates.json` | `dd639283bda309f81a5d98ad7c2ca368aa433be10747bb3fa2fbae66249a5a36` |
| 逐动作复核 | `tb21-crack-case/artifacts/coding-reports/answer-access-review-165/ledger.json` | `db1517cee762cfc6c670f978f34496251632a27a423b2008f9f718a9f28443dc` |

这次汇总与核验没有新增模型调用。后续 Python 工具修复只应用于未启动单元，
运行版本会在[续跑报告](coding-python-runtime-continuation.md)中分开统计。
