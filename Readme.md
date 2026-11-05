# Lesson 10: Control Tool Access and Permissions

Build a small code-inspection assistant with the Claude Agent SDK for Python. It finds Python files, searches for TODO comments, and explains the source without needing file-writing or shell tools.

This application accompanies the **Lesson 10 slides in the parent folder**.

## 1. Purpose and learning objectives

Imagine a team wants an assistant to review a project before a meeting. It needs to discover files and inspect their contents. It does not need to edit the project or run commands.

You will learn to:

- Choose capabilities from the task: `Glob`, `Grep`, and `Read`.
- Separate tool availability, automatic approval, and explicit denial.
- Select `dontAsk` for a run that should not wait for permission prompts.
- Observe tool requests and correlate them with returned feedback.
- Check the final run outcome and compare file state before and after.

The project includes two Python modules with two TODO comments. Each invocation copies them into a new `runs/<scenario>-<unique-id>/workspace/` directory. Your original sample files remain available for the next exercise. The application does not run the sample Python modules.

## 2. Project structure

```text
practical-application/
  lesson10.py                 CLI, scenarios, policy, and SDK query
  audit.py                    Message evidence and file fingerprints
  Readme.md                   This guide
  requirements.txt            Dependencies
  .env.example                Configuration template; contains no key
  .gitignore                  Excludes credentials and generated runs
  sample_project/
    notes.txt
    src/
      pricing.py
      catalog.py
  tests/
    test_lesson10.py           Offline automated checks
  runs/                       Created when you run the application
```

## 3. Configure the application

Use Python 3.10 or newer. The SDK version is pinned to `0.2.175`, the version used for the local checks. Live runs need network access and valid Anthropic authentication. See the official [SDK quickstart](https://code.claude.com/docs/en/agent-sdk/quickstart) for installation and authentication details.

### Windows PowerShell

Open a terminal in this subfolder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Using the environment's Python directly avoids needing to activate it. Open `.env` and configure your own key:

```dotenv
ANTHROPIC_API_KEY=your_anthropic_api_key
CLAUDE_MODEL=sonnet
```

The live application loads `.env` from the application directory. Existing environment variables take precedence. `--model` overrides `CLAUDE_MODEL`; the fallback is `sonnet`. The Inworld key from the video task is unrelated and cannot authenticate Claude.

### macOS or Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` as above. In the following commands, replace `.\.venv\Scripts\python.exe` with `.venv/bin/python` on macOS/Linux.

Most supported SDK wheels include the Claude Code runtime. If the runtime cannot be found, follow the quickstart's platform-specific installation instructions. An existing compatible Claude Code login may also provide authentication; the API key path above is the explicit setup for this exercise.

## 4. Run the application

### A. Preview without credentials or API calls

```powershell
python lesson10.py --dry-run
```

This mode works with the Python standard library alone. It creates a disposable workspace, prints the policy and task, compares files, and saves a report. It does **not** start Claude or validate permission enforcement. It also does not load `.env`, since no credentials are needed.

### B. Inspect the sample project

```powershell
.\.venv\Scripts\python.exe lesson10.py --scenario inspect
```

Read the output in order:

1. `[POLICY]` shows the options passed to the SDK.
2. `[REQUEST]` records the model's requested tool and request ID.
3. `[FEEDBACK]` records returned feedback with the corresponding ID.
4. `[FINAL]` shows the final subtype, error flag, and number of turns.
5. `[FILES]` reports additions, removals, and modifications.
6. `[AUDIT]` gives the saved report path.

For a successful inspection, expect discussion of `src/catalog.py`, `src/pricing.py`, and both TODO comments, with unchanged workspace files. The model controls the exact sequence and number of calls. A prompt requesting three tools does not guarantee that all three will be used; inspect the evidence.

### C. Request a blocked write

```powershell
.\.venv\Scripts\python.exe lesson10.py --scenario blocked-write
```

This task deliberately asks for a change to `notes.txt`. It uses the same inspection policy, with `Write` and `Edit` denied. Compare the copied `notes.txt` and the report. The agent may explain that the tool is unavailable without making a visible request. That demonstrates restricted availability; it is not evidence of a particular call being denied at runtime.

### D. Request a blocked shell command

```powershell
.\.venv\Scripts\python.exe lesson10.py --scenario blocked-shell
```

The task asks for `python --version` through `Bash`. Bash is excluded from the tool surface and explicitly denied. The assistant should report the limitation rather than invent command output or use another route.

### E. Adjust run limits

```powershell
.\.venv\Scripts\python.exe lesson10.py --scenario inspect --max-turns 10 --budget 1.00 --timeout 240
```

`--max-turns` limits agent turns, not the number of files. `--budget` supplies the SDK's estimated USD cost limit; it is not an exact billing ceiling. `--timeout` limits how long the application waits for the query. Live invocations can incur model charges.

Exit code `0` means the SDK reported successful completion and workspace file fingerprints stayed unchanged, or the dry run completed unchanged. Exit code `1` means an SDK/timeout failure, missing or unsuccessful final result, or a detected file change. A blocked-action scenario can return `0` when the assistant successfully explains its limitation. This exit code does not by itself certify permission enforcement. Invalid command-line arguments return `2`.

## 5. How the application was built

### Step 1: Define a task-sized policy

The policy function in `lesson10.py` builds the SDK options. Its central fields are:

```python
tools=["Glob", "Grep", "Read"],
allowed_tools=["Glob", "Grep", "Read"],
disallowed_tools=["Bash", "Write", "Edit", "NotebookEdit"],
permission_mode="dontAsk",
```

These fields answer different questions:

| Field | What it controls in this example |
| --- | --- |
| `tools` | Built-in capabilities presented to the model |
| `allowed_tools` | Calls eligible for automatic approval |
| `disallowed_tools` | Explicitly blocked named tools |
| `permission_mode` | Handling of calls that would still require approval |

An allow list alone does not restrict the tool inventory. `dontAsk` denies remaining prompts; it still permits calls already authorized or requiring no prompt. Other modes include `default`, `acceptEdits`, and `bypassPermissions`; changing modes does not create a filesystem sandbox. See the official [permissions guide](https://code.claude.com/docs/en/agent-sdk/permissions).

### Step 2: Make the training configuration explicit

```python
cwd=str(workspace),
setting_sources=[],
mcp_servers={},
strict_mcp_config=True,
plugins=[],
```

The working directory is the disposable copy. Filesystem settings sources are disabled, and strict MCP configuration limits servers to the supplied empty configuration. No plugins are added by the application. Managed policies can still affect the run. These fields reduce configuration surprises; they are not an operating system security boundary. Their definitions are in the official [Python reference](https://code.claude.com/docs/en/agent-sdk/python).

### Step 3: Start the SDK query

```python
options = ClaudeAgentOptions(**config)
async for message in query(prompt=prompt, options=options):
    audit.observe(message)
```

`query()` yields messages while Claude works. Our loop delegates observations to the audit collector. It does not execute the requested tools itself. The separate scenario prompts let you compare different tasks while keeping the policy constant.

### Step 4: Correlate requests and feedback

The collector stores a request by its ID:

```python
self.requests[block.id] = event
```

When a `ToolResultBlock` arrives, it looks up the originating request:

```python
request = self.requests.get(block.tool_use_id)
```

The report retains arguments, returned content, error indicators, unmatched feedback, and requests without feedback. It checks that `UserMessage.content` is a list before iterating blocks. `is_error=True` can describe an ordinary tool failure, such as a missing file; the application does not automatically label it a permission denial. It also records the final `ResultMessage` and any supplied `permission_denials`. See the SDK's [message type definitions](https://github.com/anthropics/claude-agent-sdk-python/blob/main/src/claude_agent_sdk/types.py).

### Step 5: Verify file state and preserve the report

```python
before = snapshot(workspace)
# Run the query, collecting message evidence.
after = snapshot(workspace)
changes = compare(before, after)
```

`snapshot()` fingerprints each regular file with SHA-256 and records symlink targets without reading through them. `compare()` identifies added, removed, and modified files. Reports are stored beside the workspace, so writing `audit.json` does not create a change inside the inspected fixture.

The query runs inside `try/except/finally`, allowing SDK errors and timeouts to be captured alongside file checks. A final success message does not override an unexpected file change.

## 6. Read the audit report

Open the path printed after `[AUDIT]`. Important fields include:

| Field | How to use it |
| --- | --- |
| `dry_run` | Distinguishes local preparation from an actual model run |
| `policy`, `prompt` | Records the application's requested configuration and task |
| `events` | Contains observed requests, feedback, and assistant text |
| `summary` | Lists requested tools, counts, and missing feedback |
| `final_result` | Captures the SDK outcome, turns, cost, and available denial metadata |
| `sdk_exception` | Explains a query or timeout failure |
| `changes` | Separates added, removed, and modified workspace files |
| `workspace_files_unchanged` | States what the two file snapshots establish |

**Interpret the evidence together.** A logged request proves intent, not execution. No request does not prove a runtime denial. The snapshots compare workspace files at two moments; they cannot detect a temporary change that was undone, inspect files outside the fixture, or certify that a shell command never ran. `cwd` selects a starting directory, not a sandbox. The report records the requested policy; it is not a dump of every effective managed runtime setting.

## 7. Run the offline checks

After installing dependencies:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The checks use real SDK message classes with synthetic content. They verify file-change detection, request/result correlation, unmatched messages, SDK option construction, report preservation on failure, and detection of changed files even when the final message says success. They do not call Claude or prove live permission enforcement.

## 8. Student exercises

1. Run `inspect`, then explain why each requested tool was appropriate.
2. Run `blocked-write`. Compare assistant text, any denial metadata, and file state. Which conclusions are supported?
3. Remove `Grep` from both `tools` and `allowed_tools`. Predict how the agent might find TODOs using file reads, then inspect its actual calls.
4. Change only `allowed_tools` to an empty list. Keep the restricted tool surface and denials. Observe why an empty approval list does not mean no capabilities exist.
5. Reduce `--max-turns` to `1`. Compare the final outcome with the tool feedback; a tool result is not necessarily a finished task.

## 9. Troubleshooting

| Symptom | Next step |
| --- | --- |
| Missing Python package | Install `requirements.txt` with the same Python used to launch the app |
| Authentication or billing error | Check your Anthropic credential and account; inspect `sdk_exception` and the final result |
| Runtime executable not found | Follow the official quickstart's installation instructions for your platform |
| Run exceeds turns, budget, or timeout | Read the report first, then increase the relevant limit deliberately |
| No visible blocked tool request | The tool may have been removed from the model's available tools; inspect the assistant's explanation |
| Configuration differs from expectations | Check model access and managed runtime policy; review the SDK and runtime versions |
| Files changed unexpectedly | Inspect the saved disposable workspace and `changes`; retain the report for discussion |

Use the dry-run mode to check local setup independently of authentication and network access.
