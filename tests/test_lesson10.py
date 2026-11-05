"""Offline checks: real SDK message objects, no network or model calls."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ResultMessage, ToolResultBlock,
    ToolUseBlock, UserMessage,
)

from audit import Audit, compare, snapshot
import lesson10


@contextlib.contextmanager
def local_fixture():
    # Normal mkdir works under Windows workspace ACLs too; mode=0o700
    # temporary directories can exclude the sandbox's effective identity.
    parent = (lesson10.ROOT / "runs").resolve()
    parent.mkdir(exist_ok=True)
    target = parent / f"test-{uuid4().hex}"
    target.mkdir()
    try:
        yield str(target)
    finally:
        if target.resolve().parent != parent:
            raise RuntimeError("Test cleanup must stay within its fixture parent")
        shutil.rmtree(target)


class AuditTests(unittest.TestCase):
    def test_file_changes_are_detected(self):
        with local_fixture() as directory:
            root = Path(directory)
            (root / "modified.txt").write_text("before")
            (root / "removed.txt").write_text("gone")
            before = snapshot(root)
            (root / "modified.txt").write_text("after")
            (root / "removed.txt").unlink()
            (root / "added.txt").write_text("new")
            self.assertEqual(compare(before, snapshot(root)), {
                "added": ["added.txt"], "removed": ["removed.txt"], "modified": ["modified.txt"]})

    def test_feedback_links_to_request_and_error_is_not_called_a_denial(self):
        audit = Audit()
        with contextlib.redirect_stdout(io.StringIO()):
            audit.observe(AssistantMessage(model="test", content=[
                ToolUseBlock(id="call-1", name="Read", input={"file_path": "missing.py"})]))
            audit.observe(UserMessage(content=[
                ToolResultBlock(tool_use_id="call-1", content="File not found", is_error=True)]))
            audit.observe(UserMessage(content="Plain user text is not a list of blocks."))
        self.assertTrue(audit.events[-1]["matched_request"])
        self.assertEqual(audit.events[-1]["tool"], "Read")
        self.assertEqual(audit.summary()["tool_error_count"], 1)
        self.assertEqual(audit.summary()["requests_without_feedback"], [])
        self.assertNotIn("denied", audit.events[-1])

    def test_unmatched_result_and_unanswered_request_remain_visible(self):
        audit = Audit()
        with contextlib.redirect_stdout(io.StringIO()):
            audit.observe(AssistantMessage(model="test", content=[
                ToolUseBlock(id="unanswered", name="Glob", input={"pattern": "*.py"})]))
            audit.observe(UserMessage(content=[ToolResultBlock(tool_use_id="unknown", content="x")]))
        self.assertFalse(audit.events[-1]["matched_request"])
        self.assertEqual(audit.summary()["requests_without_feedback"], ["unanswered"])

    def test_policy_is_accepted_by_installed_sdk(self):
        options = ClaudeAgentOptions(**lesson10.policy(Path("fixture"), "sonnet", 8, .5))
        self.assertEqual(options.tools, ["Glob", "Grep", "Read"])
        self.assertIn("Write", options.disallowed_tools)
        self.assertEqual(options.permission_mode, "dontAsk")
        self.assertTrue(options.strict_mcp_config)
        self.assertEqual(options.setting_sources, [])

    def test_sdk_failure_still_saves_report(self):
        async def failure(prompt, config, audit):
            raise RuntimeError("synthetic SDK connection failure")

        with local_fixture() as directory:
            root = Path(directory)
            fixture = root / "sample_project"
            fixture.mkdir()
            (fixture / "notes.txt").write_text("original")
            args = lesson10.argparse.Namespace(scenario="inspect", model="sonnet",
                max_turns=8, budget=.5, timeout=1, dry_run=False)
            with patch.object(lesson10, "ROOT", root), patch.object(lesson10, "stream_agent", failure), contextlib.redirect_stdout(io.StringIO()):
                code = asyncio.run(lesson10.execute(args))
            report = json.loads(next(root.glob("runs/*/audit.json")).read_text())
            self.assertEqual(code, 1)
            self.assertEqual(report["sdk_exception"]["type"], "RuntimeError")
            self.assertFalse(report["agent_completed_successfully"])
            self.assertTrue(report["workspace_files_unchanged"])

    def test_successful_final_message_does_not_hide_file_changes(self):
        async def changed_run(prompt, config, audit):
            (Path(config["cwd"]) / "notes.txt").write_text("unexpected change")
            audit.observe(ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1,
                is_error=False, num_turns=1, session_id="test", result="Done"))

        with local_fixture() as directory:
            root = Path(directory)
            (root / "sample_project").mkdir()
            (root / "sample_project" / "notes.txt").write_text("original")
            args = lesson10.argparse.Namespace(scenario="blocked-write", model="sonnet",
                max_turns=8, budget=.5, timeout=1, dry_run=False)
            with patch.object(lesson10, "ROOT", root), patch.object(lesson10, "stream_agent", changed_run), contextlib.redirect_stdout(io.StringIO()):
                code = asyncio.run(lesson10.execute(args))
            report = json.loads(next(root.glob("runs/*/audit.json")).read_text())
            self.assertEqual(code, 1)
            self.assertTrue(report["agent_completed_successfully"])
            self.assertFalse(report["workspace_files_unchanged"])
            self.assertEqual(report["changes"]["modified"], ["notes.txt"])


if __name__ == "__main__":
    unittest.main()
