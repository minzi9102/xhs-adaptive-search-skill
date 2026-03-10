---
name: xhs-adaptive-search
description: Guide Codex to run multi-round Xiaohongshu search by directly using xiaohongshu-automation commands, without any dedicated orchestration scripts. Use when you need manual 1-3 round strategy control, backend fallback (mcp then legacy), and reproducible trace artifacts.
---

# XHS Adaptive Search

本技能是无脚本指导技能，不提供可执行脚本。
目标是指导 Codex 直接调用 `xiaohongshu-automation` 进行最多 3 轮检索，并整理可复盘产物。

## Zero-Script Rule
- 不调用 `xhs-adaptive-search/scripts` 下任何脚本。
- 仅调用：
  - `.\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py doctor`
  - `.\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py search`
- 由 Codex 在会话中负责：
  - 轮次策略制定
  - 停止判断
  - 结果汇总与追踪记录

## Backend Decision
先探测后端：

```powershell
uv run --python .\.venv\Scripts\python.exe .\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py doctor --backend mcp
```

- 若成功，后续 `search` 用 `--backend mcp`
- 若失败，记录失败原因并降级：

```powershell
uv run --python .\.venv\Scripts\python.exe .\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py doctor --backend legacy
```

- 若 `legacy` 成功，后续全部用 `--backend legacy`
- 若两者都失败，停止并输出失败说明

## Three-Round Search Template
所有轮次都通过 `xhs.py search` 执行。

`round1`（广召回）
- 推荐参数：`sort=newest`, `top_n=12`, `min_likes=0`
- 推荐查询：目标词 + 相邻词，最多 6 个

```powershell
uv run --python .\.venv\Scripts\python.exe .\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py search --backend <mcp|legacy> -- `
  --query "AI" --query "AIGC" --query "AI工具" --query "AI编程" --query "AI Agent" --query "AI副业" `
  --sort newest --top-n 12 --min-likes 0 --open-first `
  --state-file output\playwright\xiaohongshu-state.json `
  --output-json output\playwright\xhs-adaptive-search\round1-search.json `
  --screenshot output\playwright\xhs-adaptive-search\round1-opened.png
```

`round2`（主题聚焦）
- 依据 round1 高频主题改写查询
- 推荐参数：`sort=newest`, `top_n=10`, `min_likes=50`

`round3`（高赞收敛）
- 依据 round2 结果收敛
- 推荐参数：`sort=likes_desc`, `top_n=8`, `min_likes=500`

## Stop Rule
- 最多 3 轮
- 任一轮满足需求可提前停止
- 单轮失败先重试 1 次；仍失败则进入下一轮改写策略

## Required Deliverables
最终要产出并保存：
- `final_results.json`
- `round_trace.json`

`round_trace.json` 每轮固定字段：
- `round_id`
- `intent_summary`
- `queries_tried`
- `observations`
- `tool_raw_result`
- `decision_reason`
- `next_plan`
- `backend_used`

## References
- 轮次提示词模板：`references/prompts.md`
