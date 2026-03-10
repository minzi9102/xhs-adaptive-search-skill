# XHS Adaptive Search Prompts

## Round 1: Broad Recall
- Intent: Maximize topical coverage for the user goal.
- Query strategy:
  - Start from goal keywords.
  - Expand to adjacent topic words.
  - Keep up to 6 queries.
- Tool parameters:
  - `sort=newest`
  - `top_n=12`
  - `min_likes=0`

## Round 2: Theme Refine
- Intent: Focus on high-signal themes seen in round 1.
- Query strategy:
  - Pick repeated themes from round 1 titles.
  - Replace weak queries with stronger theme terms.
  - Keep up to 6 queries.
- Tool parameters:
  - `sort=newest`
  - `top_n=10`
  - `min_likes=50`

## Round 3: High-Like Converge
- Intent: Produce a stable, deliverable hotspot candidate list.
- Query strategy:
  - Use top themes from round 2.
  - Prefer queries that produced repeated high-like notes.
  - Keep up to 6 queries.
- Tool parameters:
  - `sort=likes_desc`
  - `top_n=8`
  - `min_likes=500`

## Decision Template
- Continue if:
  - There are no usable results in the current round.
  - Goal emphasizes latest/hotspot and the converge round has not run.
- Stop if:
  - `max_rounds` reached.
  - Results are already sufficient for the stated goal.

## Trace Template
- `round_id`: integer
- `intent_summary`: round intent text
- `queries_tried`: list of strings
- `observations`: counts, top items, themes, errors
- `tool_raw_result`: raw sub-agent payload or failure object
- `decision_reason`: why continue/stop
- `next_plan`: next round action
- `backend_used`: `mcp` or `legacy`
