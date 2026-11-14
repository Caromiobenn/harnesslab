# 三题环境验收与正式评测排队记录

2026-11-14，PyTorch CLI、文档处理和 pMARS 三题均完成联网、禁网下的空提交与参考解对照。
12 项对照全部通过验收，所有实例已核实回收；这些对照没有调用模型。

| 任务 | 联网：空提交 / 参考解 | 禁网：空提交 / 参考解 | 参考解通过官方断言数（每种网络） |
| --- | --- | --- | ---: |
| `pytorch-model-cli` | 0 / 1 | 0 / 1 | 6 / 6 |
| `financial-document-processor` | 0 / 1 | 0 / 1 | 7 / 7 |
| `build-pmars` | 0 / 1 | 0 / 1 | 4 / 4 |

三个实现阶段分别提交：

- `9dc6308`：PyTorch CPU wheel、编译依赖，以及仅在评分阶段提供的 MNIST 数据缓存。
- `06267bf`：PEP 723 声明的 Python 运行时和依赖缓存；用不同脚本路径验证禁网安装。
- `64b8e6d`：Debian 源码包索引和 pMARS 公共源码缓存；编译仍由执行任务的一方完成。

这三个阶段的 GitHub Actions 均已通过。最新代码检查为 289 项测试通过、覆盖率 86.93%，
格式检查、静态检查和 smoke 运行均通过。具体准备方式见
[PyTorch](coding-pytorch-cli-prerequisites.md)、[文档处理](coding-financial-document-prerequisites.md)
和 [pMARS](coding-pmars-source-cache.md)。

正式评测沿用固定 TB2.1 revision `12b7565679ce5006230b820666353673a133db93`，
HIGH、每个实验单元独立运行 1 次。三题 × 五组 × 两种网络，共新增 30 个模型实验单元，
已提交到 CPU 控制作业 `1209289`，等待前一队列 `1209096` 结束后启动，总并发保持 2。
这里的参考解评分是环境验收结果；新增 30 个单元的模型成绩尚未产生。

全量计划仍为 890 个单元：保留 60 个六题单元，预留此前 710 个单元，本批新增 30 个，
另有 9 题、90 个单元待完成环境准备。此前已有模型尝试的单元不会重跑。
工具调用、token、输出长度、耗时、轨迹和提交文件继续由现有评测记录收集，Deep Agents 四组继续接入 LangSmith。

同目录 `coding-prerequisite-acceptance-20261114.evidence.json` 保存每项对照的评分、断言数、
回收状态、依赖与配置哈希、来源提交，以及本批排队信息，便于复核。
