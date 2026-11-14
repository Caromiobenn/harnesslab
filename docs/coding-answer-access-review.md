# 答案访问复核：从关键词候选到行为证据

对主实验的一个固定快照扫描了 138 条已评分轨迹，得到 34 条候选试次、73 个命中的工具动作。
逐项复核后，其中一条试次确认了公开参考解访问；其余命中分别来自项目测试路径、自己编写的测试、
日历正文和空日志目录探查。原始官方得分保持不变，复核标签单独保存。

## 这批候选的实际构成

| 复核分类 | 试次数 | 命中动作数 | 证据 |
| --- | ---: | ---: | --- |
| 项目自带测试路径 | 9 | 44 | `build-cython-ext` 的 `/app/pyknotid/tests/test_*.py`；它们属于待构建项目，不是根目录 `/tests` 下的官方评分器 |
| 自己编写的测试路径 | 1 | 2 | `regex-log` 使用 `write_file` 写入 `/tmp/tests/test_regex.py` |
| 生成日历中的名称 | 8 | 10 | `constraints-scheduling` 在 ICS 正文写入 `PRODID:-//Terminal-Bench//...`，没有因此发生参考材料检索 |
| 评分日志目录探查 | 15 | 16 | 15 个动作返回空的 `/logs/verifier` 目录，另一个返回 `RuntimeError` |
| 公开参考解访问，后续证据确认 | 1 | 1 | `code-from-image / mini / public` 的检索命中触发后续复核；消息 112–125 包含实际下载、读取本题参考实现及写入提交 |
| 合计 | 34 | 73 | 同一试次内的多个命中合并计为一条试次 |

这里的“1 个命中动作”不是该案例只有一次访问行为。关键词扫描先定位检索动作，后续沿原生轨迹
读到完整行为链，见 [图片任务参考解访问案例](case-image-oracle-access.md)。

日志目录探查来自 `raman-fitting` 7 条、`compile-compcert` 2 条、`cobol-modernization` 1 条、
`code-from-image` 1 条、`configure-git-webserver` 4 条试次。其中图片任务的动作来自 evidence grader，
其余来自 actor。`raman-fitting / public / rubric_evidence` 有两次命中：第一次返回空目录，
第二次工具报错。因此将动作返回与试次分类分开记录。

空目录返回说明这些具体探查没有取得评分器内容；工具报错保留为未取得内容的调用记录。
这批探查没有提供与图片案例同等的“下载成功—本题内容—实现对应—最终提交”证据。

## 分类方法与报告口径

候选扫描寻找 benchmark 名称、参考解路径、测试路径和评分日志路径。复核再检查完整路径、工具
方向及返回值：读取项目测试、写入自测文件、把名称写进产物，分别有不同含义。
不能把 `/app/pyknotid/tests/test_knot.py` 中的子串 `/tests/test_` 当作访问官方测试。

确认参考解访问时，需要保存实际返回的题目材料，核对固定版本的题面，再比对后续实现及归档。
官方准确率继续使用原评分；同时报告来源标签、轨迹位置、成本和提交结果，以支持后续敏感性分析。

本页是对这一批候选的复核，不是 890 单元的发生率估计。138 条轨迹都能被扫描读取，但未命中的
轨迹尚未逐条审阅全部行为；关键词规则也可能漏掉不含这些字符串的访问方式。
后续扩大扫描时保留新快照，并按相同证据要求追加标签。

## 可核验记录

复核不调用模型，不重跑 actor，不修改评分。逐项账本记录每个试次、工具事件位置、原始轨迹哈希、
命中输入和保存的返回文本哈希，以及分类依据。

- 固定报告：`campaign-20261114T095312Z/report.json`，138 条评分记录；SHA-256 `78d05629cf47021fae9ea4207566ac36afcd00910c4f221885b7160aef700926`。
- 扫描：`tb21-case-index/artifacts/coding-reports/answer-access-scan-20261114T095918Z/candidates.json`；SHA-256 `88ced284fa6c6e20b7c6703c1f3731c7f98e3009e19ee171050e5c0baa46641f`。
- 逐项账本：本分支工作目录的 `artifacts/coding-reports/answer-access-review-138/ledger.json`；SHA-256 `d01edc7f0172ade6fcf9f6a61ecfc767cc4301294f0f44f0eb77c7782af0cc8c`。
- 确认案例的内容与归档核验见 [案例证据位置](case-image-oracle-access.md#证据位置)。

账本与完整扫描保存在忽略的实验产物目录，并已有本地备份；本页只发布汇总和可追溯位置。

## v2 规则下的 152 条轨迹复核

[可复用扫描工具](coding-answer-access-scan.md)在另一份固定快照上检查了 152 条已评分轨迹，
得到 31 条候选试次、41 个工具动作。全部候选已复核：27 个动作与历史账本的输入、返回片段及
原始轨迹哈希一致；另外 14 个动作逐项检查了实际返回。新增内容没有增加已确认的参考解访问试次，
仍是上述 `code-from-image / mini / public` 案例。

| 动作分类 | 涉及试次 | 动作数 | 复核结果 |
| --- | ---: | ---: | --- |
| 生成日历中的名称 | 10 | 13 | 名称出现在写入 ICS 的 `PRODID` 字段 |
| 评分日志目录探查 | 21 | 25 | 24 次返回空的 verifier 目录，1 次返回工具错误 |
| 已确认参考解案例中的检索与下载 | 1 | 3 | 数据集检索、元数据查询、实际下载；具体题目内容及实现沿用已有完整证据链 |

这里的试次数不能相加：`constraints-scheduling / rubric_evidence / public` 同时包含日历正文
和一次日志目录探查，去重后仍为 31 条。账本将分类放在每个工具动作上，并保留试次的多个标签。
其中 token 计数题新增的 5 条候选试次包含 8 个目录探查动作，均未从 verifier 目录取得内容。
同一命令还读到过运行文件清单、提交采集脚本或进程信息；这些是运行环境材料，不是本题参考答案。

v2 收紧了官方测试路径的边界，并增加公开 oracle 数据集名称规则，因此不能把旧版 34 条候选
与新版 31 条候选的差值解释为风险下降。两次扫描的样本数和规则都不同。第二次扫描复用了全部
152 条未改变的轨迹，候选内容与首次扫描一致；此次复核没有模型调用，也没有更改官方评分。

- 固定报告：`campaign-20261114T110821Z/report.json`；SHA-256 `9ed6886b33ada5b1ae0e0790bb192d000132b83e34024281b6ee9f90add04e21`。
- v2 扫描：`tb21-answer-access-scan/artifacts/coding-reports/answer-access-scan152-20261114/candidates.json`；SHA-256 `a529779a145b46ca1c6bc19d343ee0702f78be27fe1a50630299c49f30410fe9`。
- 逐动作复核：`tb21-answer-access-review-v2/artifacts/coding-reports/answer-access-review-v2-152/ledger.json`；SHA-256 `41505c3ff8ed9f58c1885051fab8fc1a72f75619f145a2ba3d9cf306f2169f16`。

## 扩展到 174 条轨迹：题目原有注释与答案访问

同一版扫描规则继续检查了 174 条已评分轨迹，复用其中 165 条内容未改变的轨迹，
得到 43 条候选试次、69 个工具动作。已有 57 个动作重新核对了轨迹、输入与返回哈希；
新增 12 个动作逐条检查了实际命令和工具返回。

新增候选全部来自 `custom-memory-heap-crash`：11 个动作把题目原有的 Terminal-Bench canary
注释保留在 `user.cpp` 或自行构造的调试文件中，另一个动作列出 `/logs/verifier`，返回的
列表没有条目。四条新完成的 `distribution-search` 基线轨迹没有命中候选规则。

canary 注释的来源已与固定版本的 `environment/program/user.cpp`、`user.h` 和 `main.cpp`
核对。它原本就在任务文件里：把带有这段注释的代码写回文件，并不表示读取了参考答案。
同理，评分日志目录探查需要看实际返回，不能仅凭路径名称判定取得了官方测试内容。

| 当前动作分类 | 动作数 | 已核对的含义 |
| --- | ---: | --- |
| 评分日志目录探查 | 30 | 28 次返回空目录，1 次工具错误，1 次普通目录列表没有条目 |
| 已确认参考解案例的检索与下载 | 3 | 仍来自已有图片任务案例 |
| 生成日历中的名称 | 13 | 写入 ICS 的 `PRODID` 字段 |
| 保留任务原有 canary 注释 | 22 | 写入修复代码或自行构造的调试代码 |
| 检查 canary 注释出现次数 | 1 | 对题目原有代码中的注释计数 |
| 合计 | 69 | 涉及 43 条候选试次；一条试次可有多个动作分类 |

本次新增候选没有增加已确认的参考解访问试次。账本继续保留官方原分数，候选命中和人工
核对后的行为标签分别记录。所有核对均未调用模型，也没有重跑 actor。

- 固定报告：`campaign-20261114T143028Z/report.json`；SHA-256 `9da1f264e3be14bc47c5d581ebb21b4fa96ea785e8f0cac15ed3ca8158963530`。
- 扫描：`tb21-answer-access-scan/artifacts/coding-reports/answer-access-scan174-20261114/candidates.json`；SHA-256 `6abb6b2737318c5dcc51e7060673c7c1b241cd8c91a90aefd74fb918dbaa5c77`。
- 逐项账本：`tb21-python-launch/artifacts/coding-reports/answer-access-review-174/ledger.json`；SHA-256 `9ceb454839d13a888701fee9724cfa6d2c73142e1ac250896f4bd761dd7a95b4`。

两份记录及三份原始任务文件已经本地备份，内容哈希均已复核。
