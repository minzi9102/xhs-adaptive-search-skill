# XHS Adaptive Search Prompt Templates

## Round 1 Prompt
- 目标：最大化召回，覆盖用户目标相关主题。
- 输入：`goal + constraints`
- 输出：1-6 个查询词。
- 建议句式：
  - 从目标中提取核心词。
  - 增加相邻概念词。
  - 避免重复词和过长短语。

## Round 2 Prompt
- 目标：聚焦 round1 中高频、可交付主题。
- 输入：`round1 top items + errors + goal`
- 输出：1-6 个改写后的查询词。
- 建议句式：
  - 保留高相关词。
  - 替换低质量词。
  - 提升主题聚焦度。

## Round 3 Prompt
- 目标：收敛到高赞且稳定的候选集合。
- 输入：`round2 top items + goal`
- 输出：1-6 个最终查询词。
- 建议句式：
  - 选择重复出现且高赞主题。
  - 删除噪声主题。
  - 面向最终结果交付。

## Stop Decision Prompt
- 满足以下任一条件可停止：
  - 当前结果已满足目标。
  - 已达到第 3 轮。
- 否则继续下一轮并说明改写方向。

## Trace Writing Prompt
- 每轮记录：
  - `round_id`
  - `intent_summary`
  - `queries_tried`
  - `observations`
  - `tool_raw_result`
  - `decision_reason`
  - `next_plan`
  - `backend_used`
