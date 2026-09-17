# 服务器实验复现手册

本文记录 HarnessLab 首个自托管真实模型矩阵的部署边界、固定参数和复现命令。它不包含 SSH 地址、私钥或任何凭据。

## 1. 冻结的实验条件

| 项目 | 值 |
|---|---|
| OS | Ubuntu 22.04.5 LTS，Linux 5.15 |
| GPU | 2 × NVIDIA GeForce RTX 4090，单卡 24GB |
| 驱动 | 550.142 |
| Python | 3.12.8 |
| PyTorch / CUDA build | 2.5.1+cu124 |
| vLLM | 0.7.3 |
| 模型 | `Qwen/Qwen2.5-14B-Instruct-AWQ` |
| 参数与量化 | 14.7B，AWQ 4-bit；权重索引声明 9.295GiB |
| 服务显卡 | GPU 0；GPU 1 保留不用 |
| 上下文 | 16,384 tokens |
| 显存利用上限 | 0.90 |
| Tool parser | `hermes`，必须通过下述 smoke 才可进入矩阵 |
| Harness | minimal、planning、Deep Agents default bundle |
| 重复 | 每个 task × harness 3 次，temperature 0 |

模型来自 ModelScope 的 `Qwen/Qwen2.5-14B-Instruct-AWQ` 仓库。下载完成后应保留 `.msc`、`.mv`，并对 `config.json`、权重索引和三个权重分片生成 SHA-256；这些哈希比 `master` 标签更能证明实际字节版本。

当前实验是 3 个任务的工程/探索性矩阵，不满足项目协议中 15 个逻辑任务的正式行为结论门槛。结果可以证明真实模型链路、外部验证、workspace 工具和 treatment 对比可运行，但不能泛化成“某种 harness 总体更好”。

## 2. 存储布局

```text
/mnt/harnesslab-data/
  bin/uv
  cache/{modelscope,uv}/
  models/Qwen2.5-14B-Instruct-AWQ/
  harnesslab/.venv/
  artifacts/server/
  logs/
  runtime/
```

项目、模型、缓存和 artifacts 全部放在数据盘。不要把模型下载到系统盘，也不要覆盖 `/data` 中已有的 1.5B 模型。

本次机器的 `/dev/vdb` 在操作前是无分区、无文件系统签名、未挂载的裸盘。只有在再次验证目标设备后才可执行一次初始化：

```bash
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINTS
sudo wipefs -n /dev/vdb
sudo mkfs.ext4 -L harnesslab-data /dev/vdb
sudo install -d -m 755 -o ubuntu -g ubuntu /mnt/harnesslab-data
sudo mount /dev/vdb /mnt/harnesslab-data
sudo chown ubuntu:ubuntu /mnt/harnesslab-data
```

`mkfs` 会破坏目标盘既有数据，不应把这组命令复制到未确认的设备上。本次 `/dev/vdc` 保持未使用。

## 3. 模型与项目安装

服务器无法直连 Hugging Face，但 ModelScope 可达：

```bash
export MODELSCOPE_CACHE=/mnt/harnesslab-data/cache/modelscope
/home/ubuntu/miniforge3/bin/modelscope download \
  --model Qwen/Qwen2.5-14B-Instruct-AWQ \
  --local_dir /mnt/harnesslab-data/models/Qwen2.5-14B-Instruct-AWQ \
  --max-workers 4
```

项目目录准备完成后，用锁文件建立隔离环境：

```bash
cd /mnt/harnesslab-data/harnesslab
export UV_CACHE_DIR=/mnt/harnesslab-data/cache/uv
/mnt/harnesslab-data/bin/uv sync \
  --frozen --no-dev \
  --python /home/ubuntu/miniforge3/bin/python
```

`--frozen` 禁止在服务器上隐式改写锁文件，`--no-dev` 避免下载只在本地质量门使用的测试工具。

## 4. 启动服务并做兼容性 smoke

先停止由本项目启动的旧 1.5B smoke 服务，再启动正式模型：

```bash
kill "$(cat /home/ubuntu/harnesslab-runtime/vllm-smoke.pid)"
cd /mnt/harnesslab-data/harnesslab
nohup scripts/server/serve-qwen2.5-14b-awq.sh \
  > /mnt/harnesslab-data/logs/vllm-qwen2.5-14b.log 2>&1 < /dev/null &
echo $! > /mnt/harnesslab-data/runtime/vllm-qwen2.5-14b.pid
```

等待 `/health` 后，至少检查模型名与一次自动工具调用：

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/v1/models
```

这里的关键不是 HTTP 200，而是响应中出现结构化 `tool_calls`。若模型只输出 `<tool_call>` 文本，不能进入正式矩阵，应先修正 parser/template 兼容性。

## 5. 验证、warm-up 与正式矩阵

```bash
cd /mnt/harnesslab-data/harnesslab
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost

.venv/bin/python -m harnesslab verify-benchmark benchmarks/catalog-v0.2.yaml
scripts/server/run-qwen2.5-matrix.sh
```

脚本顺序执行三个固定配置：

1. `server-qwen2.5-14b-baseline.yaml`；
2. `server-qwen2.5-14b-planning.yaml`；
3. `server-qwen2.5-14b-deepagents.yaml`。

每次运行产生独立目录；最后用 `summarize-benchmark` 从原始 `runs.jsonl` 重建 `comparison-*.json`。汇总器不读取模型自评，也不删除失败或异常运行。

## 6. 完整性核验

```bash
find /mnt/harnesslab-data/models/Qwen2.5-14B-Instruct-AWQ \
  -maxdepth 1 -type f \
  \( -name 'config.json' -o -name 'model.safetensors.index.json' \
     -o -name 'model-*.safetensors' \) \
  -print0 | sort -z | xargs -0 sha256sum \
  > /mnt/harnesslab-data/artifacts/server/model-sha256.txt

find /mnt/harnesslab-data/artifacts/server -name summary.json -print -exec cat {} \;
```

一次可审计的交付至少包括：

- 模型文件 SHA-256；
- vLLM 启动命令和日志；
- 三个配置的 manifest、events、runs、summary；
- 由 raw runs 重建的 comparison JSON；
- 执行环境版本和 GPU 信息；
- 对 execution error、validation failure 和 false completion 的区分说明。

## 7. 结果解释边界

- `completed` 只表示 agent graph 正常结束；`success` 必须由私有 deterministic validators 决定。
- baseline 与 planning 的唯一预期机制差异是 `TodoListMiddleware`，才可做有限的增量解释。
- Deep Agents 条件是默认 bundle；结果不能单独归因于 delegation、filesystem 或某一个 middleware。
- 3 个 task × 3 repeats 的矩阵样本过小，报告原始分子/分母和任务级结果，不做总体优越性宣称。
- tool parser 错误、预算耗尽和 agent 超时是被测系统结果，不能事后排除；服务启动前失败才可标为基础设施无效。
