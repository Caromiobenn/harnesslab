# MobileSAM 依赖与权重固定

`sam-cell-seg` 的官方参考解生成分割脚本，评分器再用独立图像和预训练 MobileSAM 权重执行脚本。
环境准备沿用官方 CPU、内存和时间预算，固定参考解列出的 CPU PyTorch、Torchvision、pandas、timm 与 OpenCV 版本。

模型阶段提供公共安装包及完整 MobileSAM Git 仓库缓存，保留原来的 pip 安装和 git clone 调用。
源码使用官方指定 commit `34bbbfdface3c18e5221aa7de6032d7220c6c6a1`；Git 缓存也包含其公开权重，
可用于模型自行测试，但不包含测试输入、预计算分割结果或答案。

评分阶段的 curl 权重下载映射到独立缓存。下载来自固定 commit，并核对 Git blob
`7ef2d090979fd9853adf17b7a99c8b94a1c5a6a7`，大小 40,728,226 字节，再保存 SHA-256。
2026-11-14 核对 master 的权重 blob 与固定 commit 相同，因此原评分 URL 与固定 URL 指向相同字节。
原始测试脚本、断言和分割脚本的调用保持不变。

服务器直连 raw 权重 URL 的首次准备发生读取超时。后续通过已验收的固定 Git 缓存提取权重，
同时核对 commit、文件路径和 blob ID，再生成相同的评分下载映射。失败回执保留，系统依赖缓存继续复用。

第一次并行准备还暴露了回收标识冲突：Git 准备结束后，回收流程发现同 run、同 task 的
Python 依赖实例并一并回收，导致后者的命令流中断。回收标识现包含准备阶段
（system、wheels、r、git 或 hub），同题并行准备互不匹配。已通过的 Git 与系统缓存继续复用。

准备过程验证 Python 依赖的禁网安装与导入，以及固定版本 Git 仓库的禁网克隆。
正式评测需进一步通过联网、禁网下的空提交与参考解四项对照。

来源：[官方指定的 MobileSAM 源码](https://github.com/ChaoningZhang/MobileSAM/tree/34bbbfdface3c18e5221aa7de6032d7220c6c6a1)。
