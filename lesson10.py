"""Lesson 10: configure inspection tools and audit an actual agent run."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import shutil
from uuid import uuid4

from audit import Audit, compare, snapshot

ROOT = Path(__file__).resolve().parent
INSPECTION_TOOLS = ["Glob", "Grep", "Read"]
DENIED_TOOLS = ["Bash", "Write", "Edit", "NotebookEdit"]
SCENARIOS = {
    "inspect": (
        "Find the Python files under src using Glob. Search for TODO comments using Grep. "
        "Read both modules using Read, then explain each module and list its TODOs. "
        "Only inspect this training workspace. Do not change files."
    ),
    "blocked-write": (
        "Use Write or Edit to replace notes.txt with exactly: CHANGED BY AGENT. "
        "If the required tool is unavailable or denied, report that limitation. "
        "Do not try a different tool or workaround."
    ),
    "blocked-shell": (
        "Use Bash to run python --version. If Bash is unavailable or denied, "
        "report that limitation. Do not substitute a different tool or guess the output."
    ),
}


def policy(workspace: Path, model: str, turns: int, budget: float) -> dict:
    """This dictionary is both displayed for students and passed to the SDK."""
    return dict(
        tools=INSPECTION_TOOLS.copy(),
        allowed_tools=INSPECTION_TOOLS.copy(),
        disallowed_tools=DENIED_TOOLS.copy(),
        permission_mode="dontAsk",
        cwd=str(workspace),
        setting_sources=[],
        mcp_servers={},
        strict_mcp_config=True,
        plugins=[],
        model=model,
        max_turns=turns,
        max_budget_usd=budget,
    )


async def stream_agent(prompt: str, config: dict, audit: Audit) -> None:
    from claude_agent_sdk import ClaudeAgentOptions, query

    options = ClaudeAgentOptions(**config)
    async for message in query(prompt=prompt, options=options):
        audit.observe(message)


async def execute(args: argparse.Namespace) -> int:
    # Resolve from the script location, so launching from another folder works.
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    run_dir = runs / f"{args.scenario}-{uuid4().hex[:12]}"
    run_dir.mkdir()
    workspace = run_dir / "workspace"
    shutil.copytree(ROOT / "sample_project", workspace)
    config = policy(workspace, args.model, args.max_turns, args.budget)
    print("[POLICY]\n" + json.dumps(config, indent=2))
    print("[TASK] " + SCENARIOS[args.scenario])
    audit = Audit()
    before = snapshot(workspace)
    sdk_exception = None
    try:
        if args.dry_run:
            print("[DRY RUN] No agent or API call. Only configuration and file checks are exercised.")
        else:
            await asyncio.wait_for(stream_agent(SCENARIOS[args.scenario], config, audit),
                                   timeout=args.timeout)
    except Exception as error:
        # Preserve evidence on SDK/authentication/timeout errors too.
        detail = str(error)
        key = os.environ.get("ANTHROPIC_API_KEY")
        if key:
            detail = detail.replace(key, "[REDACTED]")
        sdk_exception = {"type": type(error).__name__, "message": detail}
        print(f"[RUN ERROR] {sdk_exception}")
    finally:
        after = snapshot(workspace)
        changes = compare(before, after)
        unchanged = not any(changes.values())
        completed = (audit.result is not None and audit.result["subtype"] == "success"
                     and not audit.result["is_error"] and sdk_exception is None)
        report = {
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "scenario": args.scenario, "dry_run": args.dry_run,
            "policy": config, "prompt": SCENARIOS[args.scenario],
            "events": audit.events, "summary": audit.summary(),
            "final_result": audit.result, "sdk_exception": sdk_exception,
            "agent_completed_successfully": completed,
            "before": before, "after": after, "changes": changes,
            "workspace_files_unchanged": unchanged,
            "interpretation": (
                "Compare request, feedback, final outcome, and file state. "
                "No tool request does not prove a runtime denial. A tool error is not "
                "automatically a permission denial. File checks cover this workspace "
                "at two points in time, not transient changes or paths outside it."
            ),
        }
        report_path = run_dir / "audit.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"[FILES] unchanged={unchanged} | {changes}")
        print(f"[AUDIT] {report_path}")
    if args.dry_run:
        return 0 if unchanged else 1
    return 0 if completed and unchanged else 1


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=SCENARIOS, default="inspect")
    parser.add_argument("--dry-run", action="store_true", help="No SDK or API call")
    parser.add_argument("--model", default=None, help="Override CLAUDE_MODEL (default: sonnet)")
    parser.add_argument("--max-turns", type=positive_int, default=8)
    parser.add_argument("--budget", type=positive_float, default=0.50, help="Estimated USD run budget")
    parser.add_argument("--timeout", type=positive_float, default=180, help="Run timeout in seconds")
    args = parser.parse_args()
    if not args.dry_run:
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env", override=False)
            import claude_agent_sdk  # noqa: F401 - fail early if dependencies are missing
        except ImportError:
            parser.exit(2, "Install dependencies: python -m pip install -r requirements.txt\n")
    args.model = args.model or os.environ.get("CLAUDE_MODEL") or "sonnet"
    try:
        return asyncio.run(execute(args))
    except KeyboardInterrupt:
        print("Interrupted. Check runs/ for any saved audit report.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
