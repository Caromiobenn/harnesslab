# 终端 Agent 的交付可靠性评测

项目研究三件事：环境准备的成本如何影响 Agent 的实现选择，审计模型需要什么证据来判断提交的来源，以及复查什么时候值得花 token。

- [实验结果](RESULTS.md) 汇总两轮本地实验和历史 TB2.1 审计。
- [第二轮协议](phase2/PROTOCOL.md) 定义四道任务、实验矩阵、评分和三种交付策略。
- [第一轮审计](audit/README.md) 和 [第二轮审计](phase2/audit/README.md) 说明历史证据口径。

终端任务是参照 Terminal-Bench 2.1 构造的四条件研究任务。历史审计使用此前保存的 TB2.1 候选证据。复跑终端任务只需要 Linux 或 WSL、Python 3.12、Docker，以及支持工具调用的阿里云百炼账号。

从 HarnessLab 仓库根目录开始。

```sh
cd studies/tb21_integrity
docker build --target scorer -t tb21-integrity-scorer:pilot1 tasks
docker build --target actor -t tb21-integrity-actor:pilot1 tasks
python3 phase2/tasks/check_controls.py --out artifacts/fixture-controls.json
```

凭据文件使用 `DASHSCOPE_API_KEY`（兼容旧配置的 `DEEPSEEK_API_KEY`），可选 `LANGSMITH_API_KEY` 和 `LANGSMITH_PROJECT`。控制器向阿里云北京的兼容接口发起模型请求。任务和评分在独立、断网的容器内执行。

```sh
sh phase2/run.sh calibration /absolute/path/.env artifacts/calibration
sh phase2/run.sh matrix /absolute/path/.env artifacts/matrix
python3 phase2/analysis/analyze.py --calibration artifacts/calibration \
  --run artifacts/matrix --out artifacts/matrix-summary
```

正式矩阵执行 48 次模型轨迹。校准、正式和审计各自写入新的输出目录。运行设计、模型请求记录、每次产物变化的快照、评分和用量写入本地输出目录。已提交的汇总便于查看结果。运行产物、凭据和历史原始档案放在本地，由 Git 忽略。复跑历史审计需要按对应说明提供已归档的输入文件。

如果正式矩阵发生模型请求断线，可在同一镜像和代码版本下重跑这些单元。原批次和重跑各自保留，选择记录注明每个替换的原因和用量。

```sh
python3 phase2/recover.py retry artifacts/matrix /absolute/path/.env artifacts/retry
python3 phase2/recover.py select artifacts/matrix artifacts/retry artifacts/accepted
python3 phase2/analysis/analyze.py --run artifacts/accepted --out artifacts/accepted-summary
```
