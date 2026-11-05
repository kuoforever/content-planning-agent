# 重规划稳定性评估

从仓库根目录运行。先按 README 安装项目。真实调用需要进程环境中的 LLM_BASE_URL、LLM_MODEL 和服务要求的 LLM_API_KEY。

## 直接运行

离线全场景演练，无需 API：

```powershell
.\.venv\Scripts\python.exe examples/stability.py --mode mock --suite full --repeat 3
```

真实低成本对照，报价 9 和 12 各重复 3 次，批次上限 40 次请求：

```powershell
.\.venv\Scripts\python.exe examples/stability.py --mode live --suite core --repeat 3 --max-requests 40
```

真实扩展评估，五场景各重复 3 次，最多 90 次请求：

```powershell
.\.venv\Scripts\python.exe examples/stability.py --mode live --suite full --repeat 3 --max-requests 90
```

每次模型输出上限为 180 token，每次任务最多 12 步。调用上限包含失败请求。余额错误、鉴权错误、连接失败和无效模型响应会使批次停止。输入 token 仍产生费用，reported_tokens 是供应商返回的用量合计，实际费用查看供应商账单。缺少 usage 的调用单独计数。程序不自动重试。重新运行会建立新批次，旧记录保留。

## 预先固定的通过条件

- normal：先估算标准素材，保存报价 9 的方案，数据库确有一份方案。
- overbudget：先观察标准报价 12，再估算可行的 8，完成保存。中间允许多次检索或重复估算。
- impossible：预算 6，检查全部候选后确认不可行，无保存。
- late：仅剩 60 分钟，两种方案均无法按时完成，确认不可行，无保存。
- failure：脚本生成后注入保存故障，最终未完成，同时保留脚本且数据库无方案。

输入使用固定业务时钟，每次独立数据库避免命中重复提交缓存。core 两组输入一致，仅改变素材报价。全场景均明确先评估标准候选且允许素材替换。

## 报告与解释

输出到 examples/stability-runs/时间戳-唯一ID。manifest.json 保存模式、模型、源码摘要、提交号、dirty 状态、提示词、工具定义和预算。每次保存 input.json、catalog.json、result.json；attempts.json 保存分类和请求计数；summary.json 与 report.md 汇总结果。

模型通信错误和预算耗尽单独列出，全部尝试成功率将它们计为未通过；可评估成功率只在排除这两类后计算，分母为零时返回 null。未运行用例显式计数。批次只有全部计划用例运行且通过才返回 0，否则返回 2。

3 次重复属于小样本冒烟评估。全部通过说明本批样例通过，不支持广泛稳定性结论；新版与旧版结果不可混用。提前停止、跳过候选、错误保存和一般任务失败均单独分类。Mock 只用于验证评估工具。

## 已执行验证

2026-11-05 全场景 Mock 15/15 通过，见 [离线报告](../examples/stability-runs/20261105T073033Z-409d29ab/report.md)。自动化测试 33 项通过，包含评分器判定、请求预算精确截断和通信失败后停止批次。本次未运行付费评估。

初次离线演练暴露了 Windows 上 SQLite 连接未关闭导致临时目录清理失败，现已修复并重跑。初次批次保留为 interrupted，不能计为通过。
