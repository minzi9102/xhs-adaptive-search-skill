from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence


SCRIPT_PATH = Path(__file__).resolve()
SKILL_DIR = SCRIPT_PATH.parent.parent
PROJECT_ROOT = SKILL_DIR.parent.parent
DEFAULT_XHS_ENTRYPOINT = (
    PROJECT_ROOT
    / "skills"
    / "xiaohongshu-automation"
    / "scripts"
    / "entrypoints"
    / "xhs.py"
)
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output" / "playwright" / "xhs-adaptive-search"
DEFAULT_STATE_FILE = PROJECT_ROOT / "output" / "playwright" / "xiaohongshu-state.json"
DEFAULT_AI_QUERY_PACK = ["AI", "AIGC", "AI工具", "AI编程", "AI Agent", "AI副业"]
THEME_PRIORITY = [
    "OpenClaw",
    "Claude Code",
    "Vibe Coding",
    "AI Agent",
    "AI变现",
    "AI副业",
    "AI工具",
    "AI编程",
    "AIGC查重",
    "AIGC",
    "DeepSeek",
    "Cursor",
    "MCP",
]


@dataclass
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


Runner = Callable[[Sequence[str], Path, int], CommandResult]


def default_runner(command: Sequence[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    try:
        proc = subprocess.run(
            list(command),
            cwd=str(cwd),
            text=True,
            capture_output=True,
            timeout=max(timeout_seconds, 1),
            encoding="utf-8",
            errors="replace",
        )
        return CommandResult(
            returncode=proc.returncode,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
        )
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            returncode=124,
            stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
            stderr=f"timeout after {timeout_seconds}s",
        )


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso(now_fn: Callable[[], datetime]) -> str:
    return now_fn().isoformat()


def _run_tag(now_fn: Callable[[], datetime]) -> str:
    return now_fn().strftime("%Y%m%d-%H%M%S")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _dedupe_keep_order(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = str(raw or "").strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _safe_slug(value: str) -> str:
    compact = re.sub(r"\s+", "-", str(value or "").strip())
    compact = re.sub(r"[^0-9A-Za-z\-_]+", "-", compact)
    compact = compact.strip("-_")
    return compact or "run"


def _resolve_venv_python(project_root: Path, override: Path | None) -> Path:
    if override:
        return override if override.is_absolute() else (project_root / override)
    candidates = [
        project_root / ".venv" / "Scripts" / "python.exe",
        project_root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def _extract_seed_queries(goal: str, constraints: str, max_queries: int = 6) -> list[str]:
    content = f"{goal}\n{constraints}".strip()
    quoted = re.findall(r"[\"“'`](.+?)[\"”'`]", content)
    candidates: list[str] = []
    candidates.extend(quoted)
    lowered = content.lower()
    if "ai" in lowered or "aigc" in lowered or "agent" in lowered:
        candidates.extend(DEFAULT_AI_QUERY_PACK)
    segments = re.split(r"[，,；;。！？!?、/\n|]+", content)
    for segment in segments:
        text = segment.strip()
        text = re.sub(r"(调研|研究|关于|热点|最新|趋势|帮我|请|小红书|上)", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        if 1 < len(text) <= 20:
            candidates.append(text)
    deduped = _dedupe_keep_order(candidates)
    if not deduped:
        deduped = list(DEFAULT_AI_QUERY_PACK)
    return deduped[: max(max_queries, 1)]


def _extract_theme_terms(items: Sequence[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for item in items:
        title = str(item.get("title") or "")
        query = str(item.get("query") or "")
        bundle = f"{title} {query}".lower()
        for term in THEME_PRIORITY:
            if term.lower() in bundle:
                counts[term] = counts.get(term, 0) + 1
    ordered = sorted(
        counts.items(),
        key=lambda pair: (-pair[1], THEME_PRIORITY.index(pair[0])),
    )
    return [name for name, _ in ordered]


def _refine_queries(
    *,
    seed_queries: Sequence[str],
    previous_payload: dict[str, Any] | None,
    round_id: int,
    max_queries: int = 6,
) -> list[str]:
    items = []
    if previous_payload:
        raw_items = previous_payload.get("items")
        if isinstance(raw_items, list):
            items = [item for item in raw_items if isinstance(item, dict)]
    theme_terms = _extract_theme_terms(items)
    merged: list[str] = []
    if round_id == 2:
        merged.extend(theme_terms[:4])
    else:
        merged.extend(theme_terms[:5])
    merged.extend(seed_queries)
    deduped = _dedupe_keep_order(merged)
    return deduped[: max(max_queries, 1)] if deduped else list(seed_queries)[:max_queries]


def _round_intent_summary(round_id: int) -> str:
    if round_id == 1:
        return "广召回：先覆盖目标语义与相关子主题。"
    if round_id == 2:
        return "主题聚焦：根据上一轮高频主题收缩查询。"
    return "高赞收敛：聚焦高赞候选并输出可交付热点清单。"


def _build_round_strategy(
    *,
    round_id: int,
    goal: str,
    seed_queries: Sequence[str],
    previous_payload: dict[str, Any] | None,
    open_first: bool,
) -> dict[str, Any]:
    if round_id == 1:
        return {
            "round_id": round_id,
            "intent_summary": _round_intent_summary(round_id),
            "queries": list(seed_queries),
            "sort": "newest",
            "top_n": 12,
            "min_likes": 0,
            "open_first": open_first,
        }
    if round_id == 2:
        return {
            "round_id": round_id,
            "intent_summary": _round_intent_summary(round_id),
            "queries": _refine_queries(
                seed_queries=seed_queries,
                previous_payload=previous_payload,
                round_id=round_id,
            ),
            "sort": "newest",
            "top_n": 10,
            "min_likes": 50,
            "open_first": open_first,
        }
    return {
        "round_id": round_id,
        "intent_summary": _round_intent_summary(round_id),
        "queries": _refine_queries(
            seed_queries=seed_queries,
            previous_payload=previous_payload,
            round_id=round_id,
        ),
        "sort": "likes_desc",
        "top_n": 8,
        "min_likes": 500,
        "open_first": open_first,
    }


def _build_doctor_command(
    *,
    xhs_entrypoint: Path,
    venv_python: Path,
    backend: str,
    output_json: Path,
) -> list[str]:
    return [
        "uv",
        "run",
        "--python",
        str(venv_python),
        str(xhs_entrypoint),
        "doctor",
        "--backend",
        backend,
        "--output-json",
        str(output_json),
    ]


def _build_search_command(
    *,
    xhs_entrypoint: Path,
    venv_python: Path,
    backend: str,
    strategy: dict[str, Any],
    state_file: Path,
    output_json: Path,
    screenshot: Path,
) -> list[str]:
    command: list[str] = [
        "uv",
        "run",
        "--python",
        str(venv_python),
        str(xhs_entrypoint),
        "search",
        "--backend",
        backend,
        "--",
    ]
    for query in strategy.get("queries", []):
        command.extend(["--query", str(query)])
    command.extend(
        [
            "--sort",
            str(strategy["sort"]),
            "--top-n",
            str(strategy["top_n"]),
            "--min-likes",
            str(strategy["min_likes"]),
            "--state-file",
            str(state_file),
            "--output-json",
            str(output_json),
        ]
    )
    if strategy.get("open_first"):
        command.extend(["--open-first", "--screenshot", str(screenshot)])
    return command


def _probe_backend(
    *,
    backend: str,
    runner: Runner,
    project_root: Path,
    xhs_entrypoint: Path,
    venv_python: Path,
    output_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    output_json = output_dir / f"doctor-{backend}.json"
    if output_json.exists():
        output_json.unlink()
    command = _build_doctor_command(
        xhs_entrypoint=xhs_entrypoint,
        venv_python=venv_python,
        backend=backend,
        output_json=output_json,
    )
    result = runner(command, project_root, timeout_seconds)
    payload = _read_json(output_json)
    errors: list[dict[str, Any]] = []
    if payload and isinstance(payload.get("errors"), list):
        errors = [err for err in payload["errors"] if isinstance(err, dict)]
    ok = bool(payload) and not errors and result.returncode == 0
    first_error = ""
    if errors:
        first_error = str(errors[0].get("message") or "")
    if not first_error and result.returncode != 0:
        first_error = (result.stderr or result.stdout or "").strip()
    return {
        "backend": backend,
        "ok": ok,
        "error": first_error,
        "doctor_output": payload or {},
        "returncode": result.returncode,
    }


def _resolve_backend(
    *,
    policy: str,
    runner: Runner,
    project_root: Path,
    xhs_entrypoint: Path,
    venv_python: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if policy == "legacy":
        probe = _probe_backend(
            backend="legacy",
            runner=runner,
            project_root=project_root,
            xhs_entrypoint=xhs_entrypoint,
            venv_python=venv_python,
            output_dir=output_dir,
            timeout_seconds=60,
        )
        return {
            "policy": policy,
            "backend_used": "legacy",
            "fallback_reason": "" if probe["ok"] else probe["error"],
            "probes": [probe],
        }
    if policy == "mcp":
        probe = _probe_backend(
            backend="mcp",
            runner=runner,
            project_root=project_root,
            xhs_entrypoint=xhs_entrypoint,
            venv_python=venv_python,
            output_dir=output_dir,
            timeout_seconds=60,
        )
        return {
            "policy": policy,
            "backend_used": "mcp",
            "fallback_reason": "" if probe["ok"] else probe["error"],
            "probes": [probe],
        }

    mcp_probe = _probe_backend(
        backend="mcp",
        runner=runner,
        project_root=project_root,
        xhs_entrypoint=xhs_entrypoint,
        venv_python=venv_python,
        output_dir=output_dir,
        timeout_seconds=60,
    )
    if mcp_probe["ok"]:
        return {
            "policy": policy,
            "backend_used": "mcp",
            "fallback_reason": "",
            "probes": [mcp_probe],
        }

    legacy_probe = _probe_backend(
        backend="legacy",
        runner=runner,
        project_root=project_root,
        xhs_entrypoint=xhs_entrypoint,
        venv_python=venv_python,
        output_dir=output_dir,
        timeout_seconds=60,
    )
    if legacy_probe["ok"]:
        fallback_reason = mcp_probe.get("error", "") or "mcp doctor failed"
        return {
            "policy": policy,
            "backend_used": "legacy",
            "fallback_reason": fallback_reason,
            "probes": [mcp_probe, legacy_probe],
        }
    reason = "mcp and legacy doctor both failed"
    if mcp_probe.get("error") or legacy_probe.get("error"):
        reason = f"mcp failed: {mcp_probe.get('error', '')}; legacy failed: {legacy_probe.get('error', '')}"
    return {
        "policy": policy,
        "backend_used": "legacy",
        "fallback_reason": reason,
        "probes": [mcp_probe, legacy_probe],
    }


def _extract_url(item: dict[str, Any]) -> str:
    for key in ("report_url", "open_url", "url"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _summarize_observations(
    payload: dict[str, Any] | None,
    attempts: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    if not payload:
        return {
            "items_count": 0,
            "errors_count": 1,
            "top_items": [],
            "themes": [],
            "attempt_count": len(attempts),
            "attempts": list(attempts),
        }
    raw_items = payload.get("items")
    items = [item for item in raw_items if isinstance(item, dict)] if isinstance(raw_items, list) else []
    raw_errors = payload.get("errors")
    errors = [err for err in raw_errors if isinstance(err, dict)] if isinstance(raw_errors, list) else []
    sorted_items = sorted(
        items,
        key=lambda item: int(item.get("likes_value") or 0),
        reverse=True,
    )
    top_items = []
    for item in sorted_items[:5]:
        top_items.append(
            {
                "query": str(item.get("query") or ""),
                "title": str(item.get("title") or "").strip(),
                "likes_value": int(item.get("likes_value") or 0),
                "url": _extract_url(item),
            }
        )
    themes = _extract_theme_terms(items)[:6]
    return {
        "items_count": len(items),
        "errors_count": len(errors),
        "top_items": top_items,
        "themes": themes,
        "attempt_count": len(attempts),
        "attempts": list(attempts),
    }


def _should_continue(
    *,
    goal: str,
    round_id: int,
    max_rounds: int,
    observations: dict[str, Any],
) -> tuple[bool, str]:
    if round_id >= max_rounds:
        return False, "达到最大轮次，停止。"
    items_count = int(observations.get("items_count") or 0)
    if items_count == 0:
        return True, "当前轮未得到可用结果，进入下一轮改写策略。"
    if round_id == 1:
        return True, "完成广召回，进入主题聚焦轮。"
    goal_lower = goal.lower()
    if round_id == 2 and (
        "最新" in goal
        or "热点" in goal
        or "latest" in goal_lower
        or "trend" in goal_lower
        or "hot" in goal_lower
    ):
        return True, "目标强调热点/最新，执行高赞收敛轮。"
    if int(observations.get("errors_count") or 0) == 0 and items_count >= 6:
        return False, "结果已覆盖主要主题，主Agent判定满足需求。"
    return True, "继续下一轮以提高结果稳定性。"


def _merge_final_candidates(round_payloads: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for payload in round_payloads:
        round_id = int(payload.get("_round_id") or 0)
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            continue
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            url = _extract_url(item)
            if not url:
                continue
            likes_value = int(item.get("likes_value") or 0)
            if url not in merged:
                merged[url] = {
                    "title": str(item.get("title") or "").strip(),
                    "query": str(item.get("query") or "").strip(),
                    "likes_value": likes_value,
                    "url": url,
                    "source_rounds": [round_id] if round_id else [],
                }
                continue
            if likes_value > int(merged[url].get("likes_value") or 0):
                merged[url]["likes_value"] = likes_value
                if str(item.get("title") or "").strip():
                    merged[url]["title"] = str(item.get("title") or "").strip()
                if str(item.get("query") or "").strip():
                    merged[url]["query"] = str(item.get("query") or "").strip()
            existing_rounds = set(merged[url].get("source_rounds") or [])
            if round_id:
                existing_rounds.add(round_id)
            merged[url]["source_rounds"] = sorted(existing_rounds)
    return sorted(
        merged.values(),
        key=lambda item: int(item.get("likes_value") or 0),
        reverse=True,
    )


def _execute_round(
    *,
    round_id: int,
    strategy: dict[str, Any],
    backend: str,
    state_file: Path,
    output_dir: Path,
    xhs_entrypoint: Path,
    venv_python: Path,
    runner: Runner,
    project_root: Path,
    retry_count: int,
    timeout_seconds: int,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    attempts_meta: list[dict[str, Any]] = []
    output_json = output_dir / f"round{round_id}-search.json"
    screenshot = output_dir / f"round{round_id}-opened.png"
    total_attempts = max(retry_count, 0) + 1
    for attempt in range(1, total_attempts + 1):
        if output_json.exists():
            output_json.unlink()
        command = _build_search_command(
            xhs_entrypoint=xhs_entrypoint,
            venv_python=venv_python,
            backend=backend,
            strategy=strategy,
            state_file=state_file,
            output_json=output_json,
            screenshot=screenshot,
        )
        result = runner(command, project_root, timeout_seconds)
        payload = _read_json(output_json)
        parsed_ok = bool(payload) and (
            isinstance(payload.get("items"), list) or isinstance(payload.get("query_results"), list)
        )
        attempts_meta.append(
            {
                "attempt": attempt,
                "returncode": result.returncode,
                "parsed_ok": parsed_ok,
                "stdout_tail": (result.stdout or "")[-1000:],
                "stderr_tail": (result.stderr or "")[-1000:],
            }
        )
        if parsed_ok and payload:
            payload["_round_id"] = round_id
            return payload, attempts_meta
    return None, attempts_meta


def run_orchestration(
    *,
    goal: str,
    constraints: str,
    max_rounds: int,
    session_memory: str,
    backend_policy: str,
    output_root: Path,
    state_file: Path,
    round_retry_count: int,
    search_timeout_seconds: int,
    open_first: bool,
    xhs_entrypoint: Path,
    venv_python: Path,
    runner: Runner = default_runner,
    project_root: Path = PROJECT_ROOT,
    now_fn: Callable[[], datetime] = _now_utc,
) -> dict[str, Any]:
    bounded_max_rounds = min(max(max_rounds, 1), 3)
    run_dir = output_root / _run_tag(now_fn)
    run_dir.mkdir(parents=True, exist_ok=True)

    backend_meta = _resolve_backend(
        policy=backend_policy,
        runner=runner,
        project_root=project_root,
        xhs_entrypoint=xhs_entrypoint,
        venv_python=venv_python,
        output_dir=run_dir,
    )
    backend_used = str(backend_meta.get("backend_used") or "legacy")

    seed_queries = _extract_seed_queries(goal, constraints)
    round_entries: list[dict[str, Any]] = []
    successful_payloads: list[dict[str, Any]] = []
    previous_payload: dict[str, Any] | None = None

    for round_id in range(1, bounded_max_rounds + 1):
        strategy = _build_round_strategy(
            round_id=round_id,
            goal=goal,
            seed_queries=seed_queries,
            previous_payload=previous_payload,
            open_first=open_first,
        )
        payload, attempts = _execute_round(
            round_id=round_id,
            strategy=strategy,
            backend=backend_used,
            state_file=state_file,
            output_dir=run_dir,
            xhs_entrypoint=xhs_entrypoint,
            venv_python=venv_python,
            runner=runner,
            project_root=project_root,
            retry_count=round_retry_count,
            timeout_seconds=search_timeout_seconds,
        )
        observations = _summarize_observations(payload, attempts)
        continue_next, decision_reason = _should_continue(
            goal=goal,
            round_id=round_id,
            max_rounds=bounded_max_rounds,
            observations=observations,
        )
        next_plan = (
            f"进入第{round_id + 1}轮策略改写。"
            if continue_next and round_id < bounded_max_rounds
            else "结束编排并汇总最终结果。"
        )
        round_entry = {
            "round_id": round_id,
            "intent_summary": strategy["intent_summary"],
            "queries_tried": strategy["queries"],
            "observations": observations,
            "tool_raw_result": payload if payload is not None else {"error": "round execution failed"},
            "decision_reason": decision_reason,
            "next_plan": next_plan,
            "backend_used": backend_used,
        }
        round_entries.append(round_entry)
        if payload is not None:
            successful_payloads.append(payload)
            previous_payload = payload
        if not continue_next:
            break

    final_candidates = _merge_final_candidates(successful_payloads)
    final_results = {
        "workflow": "xhs-adaptive-search",
        "generated_at": _now_iso(now_fn),
        "goal": goal,
        "constraints": constraints,
        "session_memory": session_memory,
        "backend_policy": backend_policy,
        "backend_used": backend_used,
        "backend_fallback_reason": backend_meta.get("fallback_reason", ""),
        "max_rounds": bounded_max_rounds,
        "executed_rounds": len(round_entries),
        "final_candidates": final_candidates,
    }
    round_trace = {
        "workflow": "xhs-adaptive-search-trace",
        "generated_at": _now_iso(now_fn),
        "goal": goal,
        "constraints": constraints,
        "session_memory": session_memory,
        "backend_policy": backend_policy,
        "backend_resolution": backend_meta,
        "seed_queries": seed_queries,
        "rounds": round_entries,
    }
    final_results_path = run_dir / "final_results.json"
    round_trace_path = run_dir / "round_trace.json"
    _write_json(final_results_path, final_results)
    _write_json(round_trace_path, round_trace)
    return {
        "ok": True,
        "run_dir": str(run_dir),
        "backend_used": backend_used,
        "final_results_path": str(final_results_path),
        "round_trace_path": str(round_trace_path),
        "final_candidates_count": len(final_candidates),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Three-round adaptive search orchestrator for Xiaohongshu."
    )
    parser.add_argument("--goal", required=True, help="Search goal in natural language.")
    parser.add_argument(
        "--constraints",
        action="append",
        default=[],
        help="Optional constraints. Repeatable.",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=3,
        help="Maximum rounds (1-3).",
    )
    parser.add_argument(
        "--session-memory",
        choices=["inproc"],
        default="inproc",
        help="Session memory mode.",
    )
    parser.add_argument(
        "--backend-policy",
        choices=["auto", "mcp", "legacy"],
        default="auto",
        help="Backend selection policy.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Output root directory. A timestamped run folder is created inside.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help="State file forwarded to child search command.",
    )
    parser.add_argument(
        "--round-retry-count",
        type=int,
        default=1,
        help="Retry count for each failed round invocation.",
    )
    parser.add_argument(
        "--search-timeout-seconds",
        type=int,
        default=300,
        help="Timeout for each child command invocation.",
    )
    parser.add_argument(
        "--open-first",
        dest="open_first",
        action="store_true",
        help="Forward --open-first to child search.",
    )
    parser.add_argument(
        "--no-open-first",
        dest="open_first",
        action="store_false",
        help="Disable --open-first for child search.",
    )
    parser.set_defaults(open_first=True)
    parser.add_argument(
        "--uv-python",
        type=Path,
        default=None,
        help="Python interpreter path used by uv run --python.",
    )
    parser.add_argument(
        "--xhs-entrypoint",
        type=Path,
        default=DEFAULT_XHS_ENTRYPOINT,
        help="Path to xiaohongshu-automation xhs.py entrypoint.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    constraints = "; ".join(
        [str(value).strip() for value in args.constraints if str(value).strip()]
    )
    xhs_entrypoint = args.xhs_entrypoint
    if not xhs_entrypoint.is_absolute():
        xhs_entrypoint = (PROJECT_ROOT / xhs_entrypoint).resolve()
    venv_python = _resolve_venv_python(PROJECT_ROOT, args.uv_python)
    result = run_orchestration(
        goal=args.goal,
        constraints=constraints,
        max_rounds=args.max_rounds,
        session_memory=args.session_memory,
        backend_policy=args.backend_policy,
        output_root=args.output_dir if args.output_dir.is_absolute() else (PROJECT_ROOT / args.output_dir),
        state_file=args.state_file if args.state_file.is_absolute() else (PROJECT_ROOT / args.state_file),
        round_retry_count=args.round_retry_count,
        search_timeout_seconds=args.search_timeout_seconds,
        open_first=bool(args.open_first),
        xhs_entrypoint=xhs_entrypoint,
        venv_python=venv_python,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
