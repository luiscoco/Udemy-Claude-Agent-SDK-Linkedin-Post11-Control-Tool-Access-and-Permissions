"""Local file checks and message evidence, kept separate from agent policy."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Any


def snapshot(workspace: Path) -> dict[str, str]:
    """Fingerprint files; record symlink targets without reading through them."""
    files = {}
    for path in sorted(workspace.rglob("*")):
        name = path.relative_to(workspace).as_posix()
        if path.is_symlink():
            files[name] = "symlink:" + str(path.readlink())
        elif path.is_file():
            files[name] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def compare(before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
    return {
        "added": sorted(after.keys() - before.keys()),
        "removed": sorted(before.keys() - after.keys()),
        "modified": sorted(k for k in before.keys() & after.keys() if before[k] != after[k]),
    }


@dataclass
class Audit:
    events: list[dict[str, Any]] = field(default_factory=list)
    requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    result: dict[str, Any] | None = None

    def observe(self, message: Any) -> None:
        """Printing a request observes intent; it never executes the tool."""
        from claude_agent_sdk import (
            AssistantMessage, ResultMessage, TextBlock, ToolResultBlock,
            ToolUseBlock, UserMessage,
        )

        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, ToolUseBlock):
                    event = {"kind": "tool_request", "id": block.id,
                             "tool": block.name, "input": block.input}
                    self.requests[block.id] = event
                    self.events.append(event)
                    print(f"[REQUEST] {block.name} | id={block.id} | {block.input}")
                elif isinstance(block, TextBlock):
                    self.events.append({"kind": "assistant_text", "text": block.text})
                    print(f"[CLAUDE] {block.text}")
            if message.error:
                self.events.append({"kind": "assistant_error", "error": message.error})
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    request = self.requests.get(block.tool_use_id)
                    self.events.append({
                        "kind": "tool_result", "tool_use_id": block.tool_use_id,
                        "tool": request["tool"] if request else None,
                        "matched_request": request is not None,
                        "is_error": block.is_error, "content": block.content,
                    })
                    print(f"[FEEDBACK] id={block.tool_use_id} | is_error={block.is_error}")
        elif isinstance(message, ResultMessage):
            self.result = {
                "subtype": message.subtype, "is_error": message.is_error,
                "num_turns": message.num_turns, "text": message.result,
                "total_cost_usd": message.total_cost_usd,
                "permission_denials": getattr(message, "permission_denials", None),
            }
            print(f"[FINAL] {message.subtype} | error={message.is_error} | turns={message.num_turns}")

    def summary(self) -> dict[str, Any]:
        returned = {e["tool_use_id"] for e in self.events if e["kind"] == "tool_result"}
        return {
            "requested_tools": sorted({r["tool"] for r in self.requests.values()}),
            "request_count": len(self.requests),
            "result_count": sum(e["kind"] == "tool_result" for e in self.events),
            "requests_without_feedback": sorted(self.requests.keys() - returned),
            "tool_error_count": sum(e["kind"] == "tool_result" and e["is_error"] is True
                                    for e in self.events),
        }
