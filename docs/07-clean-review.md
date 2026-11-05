# 独立评审式复现记录

2026-11-05 在 Windows PowerShell 中，从公开 GitHub 地址全新克隆到独立目录，创建新的 Python 3.11.15 虚拟环境。验证提交为 051b1f62b8da83a484c75e0440ddc9e220f97903。

严格执行 README 的 uv venv、uv pip install、Activate.ps1、PYTHONUTF8 配置及运行命令，均成功。依赖安装自 pyproject.toml，未使用开发目录的虚拟环境。

- 正常 CLI 返回 completed。
- 第二个独立进程重复执行返回同一个 plan_id，reused=true；直接查询 SQLite，只有一份方案。
- pytest 输出 33 passed in 1.59s。
- examples/reproduce.py 六场景结果分别为 completed、completed、needs_input、incomplete、incomplete、incomplete，均符合场景预期。超预算路径观察到报价 12 后改选报价 8。
- examples/stability.py --mode mock --suite full --repeat 3，15/15 通过，退出码 0。

本轮只验证离线评审入口和本地 HTTP 替身测试；真实模型记录见 03-evaluation.md。本轮不含付费 API 请求，也未覆盖 Linux 环境。

发现并修正文档说明：每个任务最多 12 次请求，一轮真实对照包含两个任务，最多 24 次请求。批次硬上限请使用 stability.py 的 --max-requests 参数。
