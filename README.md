# 内容任务规划 Agent · 题号 2

面向运营人员的 Python 3.11 CLI。输入主题、预算、截止时间和请求 ID，输出活动步骤、报价、可编辑脚本、约束缺口和实际保存状态。模拟费用以整数单位计，时间以分钟计。所有素材均为合成数据。

## 快速运行（PowerShell，从仓库根目录）

```powershell
uv venv --python 3.11
uv pip install -e '.[test]'
.\.venv\Scripts\Activate.ps1
$env:PYTHONUTF8='1'
python -m content_planner run --input examples/normal/input.json --mode mock
python -m pytest -q
python examples/reproduce.py
```

已有 Python 3.11 时也可以用 `python -m venv .venv`，激活后执行 `python -m pip install -e '.[test]'`。重复执行相同 CLI 命令会返回同一 plan_id。默认数据库为当前目录下的 planner.db。状态 completed 返回退出码 0，其余业务状态返回 2。

## 真实模型

在当前进程配置 LLM_BASE_URL（含供应商要求的 /v1 等前缀）、LLM_MODEL 及服务所需的 LLM_API_KEY。程序从环境读取，.env.example 为变量清单。所选模型需支持 tools、tool_choice=required、tool_calls 和工具结果回传。

```powershell
python -m content_planner run --input examples/normal/input.json --mode live --db live.db
python examples/reproduce.py --mode live
```

复现实验分别使用独立的临时数据库与固定业务时钟，只改变标准素材价格。脚本会更新 examples 下相应模式的实际记录。两组 live 实验均已用 gpt-4.1-mini 完成，均直接选择经济素材并保存费用 8 的方案。Mock 为确定性策略。HTTP 测试使用本地替身。

## 评审顺序

先看 [评估与实际记录](docs/03-evaluation.md)，再看 [设计](docs/02-solution.md)。其余文档涵盖 [需求](docs/01-requirements.md)、[AI 使用](docs/04-ai-usage.md) 和 [复盘](docs/05-retrospective.md)。查看提交号用 `git rev-parse HEAD`。

