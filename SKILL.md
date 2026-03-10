---
name: xhs-adaptive-search
description: Orchestrate Xiaohongshu adaptive multi-round search without modifying xiaohongshu-automation. Use when you need a reproducible 1-3 round loop (broad recall, theme refine, high-like converge), backend auto fallback (mcp then legacy), and full per-round trace output for review.
---

# XHS Adaptive Search

使用新技能编排器执行最多 3 轮检索，不改动 `xiaohongshu-automation` 本体。

统一入口：
`uv run --python .\.venv\Scripts\python.exe .\skills\xhs-adaptive-search\scripts\orchestrate_search.py --goal "<目标>" --constraints "<约束>"`

## Workflow
- 主 Agent（本技能脚本）：
  - 解析 `goal/constraints`
  - 生成每轮检索策略
  - 判定继续或停止
  - 输出 `final_results.json` 和 `round_trace.json`
- 子 Agent（黑盒工具）：
  - 仅调用 `.\skills\xiaohongshu-automation\scripts\entrypoints\xhs.py search`
  - 不做解释与重写，只返回检索产物

## Round Policy
- `round1`：广召回（`sort=newest`, `top_n=12`, `min_likes=0`）
- `round2`：主题聚焦（`sort=newest`, `top_n=10`, `min_likes=50`）
- `round3`：高赞收敛（`sort=likes_desc`, `top_n=8`, `min_likes=500`）
- `max_rounds` 上限为 3。

## Backend Policy
- 默认：`--backend-policy auto`
- 自动策略：
  - 先执行 `doctor --backend mcp`
  - 失败后自动降级 `doctor --backend legacy`
  - 在 `round_trace` 记录降级原因与最终后端
- 可显式指定：`mcp` 或 `legacy`

## Failure Handling
- 每轮子调用失败先同轮重试 1 次（可由参数调整）。
- 同轮仍失败：进入下一轮并改写查询策略。
- 达到最大轮次后输出“最佳可得结果 + 失败记录”。

## Output Contract
- `final_results.json`：跨轮去重后的最终候选与元信息。
- `round_trace.json`：每轮必含字段：
  - `round_id`
  - `intent_summary`
  - `queries_tried`
  - `observations`
  - `tool_raw_result`
  - `decision_reason`
  - `next_plan`
  - `backend_used`

## References
- 策略模板：`references/prompts.md`
