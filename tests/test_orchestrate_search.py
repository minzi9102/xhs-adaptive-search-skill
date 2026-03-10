import importlib.util
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "orchestrate_search.py"
)
SPEC = importlib.util.spec_from_file_location("xhs_adaptive_orchestrate", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _abs_path(raw: str, cwd: Path) -> Path:
    candidate = Path(raw)
    return candidate if candidate.is_absolute() else (cwd / candidate)


class FakeRunner:
    def __init__(self, *, mcp_doctor_ok: bool = False, fail_first_round_once: bool = False):
        self.mcp_doctor_ok = mcp_doctor_ok
        self.fail_first_round_once = fail_first_round_once
        self.round1_fail_triggered = False

    def __call__(self, command, cwd: Path, timeout_seconds: int):
        cmd = list(command)
        if "doctor" in cmd:
            backend = cmd[cmd.index("--backend") + 1]
            output_json = _abs_path(cmd[cmd.index("--output-json") + 1], cwd)
            output_json.parent.mkdir(parents=True, exist_ok=True)
            ok = backend == "legacy" or self.mcp_doctor_ok
            payload = {
                "workflow": f"doctor-{backend}",
                "errors": [] if ok else [{"message": f"{backend} unavailable"}],
            }
            output_json.write_text(json.dumps(payload), encoding="utf-8")
            return MODULE.CommandResult(returncode=0 if ok else 1, stdout="", stderr="")

        if "search" in cmd:
            output_json = _abs_path(cmd[cmd.index("--output-json") + 1], cwd)
            output_json.parent.mkdir(parents=True, exist_ok=True)
            match = re.search(r"round(\d+)-search\.json", output_json.name)
            round_id = int(match.group(1)) if match else 1
            if (
                self.fail_first_round_once
                and round_id == 1
                and not self.round1_fail_triggered
            ):
                self.round1_fail_triggered = True
                return MODULE.CommandResult(returncode=2, stdout="", stderr="simulated failure")

            queries = []
            for idx, token in enumerate(cmd):
                if token == "--query" and idx + 1 < len(cmd):
                    queries.append(cmd[idx + 1])
            if not queries:
                queries = ["AI"]
            items = []
            query_results = []
            for idx, query in enumerate(queries):
                item = {
                    "query": query,
                    "title": f"Round{round_id}-{query}",
                    "likes_value": round_id * 100 + idx,
                    "report_url": f"https://example.com/{round_id}/{idx}",
                }
                items.append(item)
                query_results.append({"query": query, "items": [item], "errors": []})
            payload = {
                "workflow": "xhs-search",
                "items": items,
                "errors": [],
                "query_results": query_results,
                "artifacts": [f"round{round_id}.png"],
            }
            output_json.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return MODULE.CommandResult(returncode=0, stdout="", stderr="")

        return MODULE.CommandResult(returncode=1, stdout="", stderr="unknown command")


class TestAdaptiveSearch(unittest.TestCase):
    def test_extract_seed_queries_for_ai_goal(self):
        queries = MODULE._extract_seed_queries(
            "调研小红书上关于ai的最新热点",
            "关注工具、编程、Agent",
        )
        self.assertLessEqual(len(queries), 6)
        self.assertIn("AI", queries)

    def test_resolve_backend_auto_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            fake_runner = FakeRunner(mcp_doctor_ok=False)
            result = MODULE._resolve_backend(
                policy="auto",
                runner=fake_runner,
                project_root=out_dir,
                xhs_entrypoint=out_dir / "xhs.py",
                venv_python=out_dir / "python.exe",
                output_dir=out_dir,
            )
            self.assertEqual(result["backend_used"], "legacy")
            self.assertTrue(result["fallback_reason"])

    def test_run_orchestration_writes_trace_with_required_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_runner = FakeRunner(mcp_doctor_ok=False)
            result = MODULE.run_orchestration(
                goal="调研小红书上关于ai的最新热点",
                constraints="输出热点标题和链接",
                max_rounds=3,
                session_memory="inproc",
                backend_policy="auto",
                output_root=root / "output",
                state_file=root / "state.json",
                round_retry_count=1,
                search_timeout_seconds=10,
                open_first=False,
                xhs_entrypoint=root / "xhs.py",
                venv_python=root / "python.exe",
                runner=fake_runner,
                project_root=root,
            )
            trace_path = Path(result["round_trace_path"])
            self.assertTrue(trace_path.exists())
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertGreaterEqual(len(trace["rounds"]), 2)
            required = {
                "round_id",
                "intent_summary",
                "queries_tried",
                "observations",
                "tool_raw_result",
                "decision_reason",
                "next_plan",
                "backend_used",
            }
            for round_item in trace["rounds"]:
                self.assertTrue(required.issubset(set(round_item.keys())))

    def test_retry_once_when_round_execution_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_runner = FakeRunner(mcp_doctor_ok=False, fail_first_round_once=True)
            result = MODULE.run_orchestration(
                goal="调研小红书上关于ai的最新热点",
                constraints="",
                max_rounds=1,
                session_memory="inproc",
                backend_policy="auto",
                output_root=root / "output",
                state_file=root / "state.json",
                round_retry_count=1,
                search_timeout_seconds=10,
                open_first=False,
                xhs_entrypoint=root / "xhs.py",
                venv_python=root / "python.exe",
                runner=fake_runner,
                project_root=root,
            )
            trace = json.loads(Path(result["round_trace_path"]).read_text(encoding="utf-8"))
            first_round = trace["rounds"][0]
            self.assertEqual(first_round["observations"]["attempt_count"], 2)


if __name__ == "__main__":
    unittest.main()
