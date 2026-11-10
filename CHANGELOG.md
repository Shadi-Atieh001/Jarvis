# Changelog

## 0.1.0 — Phase 1: core (2026-11-10)

Added
- Agent loop on the Anthropic API (`claude-fable-5-2`) with native tool use,
  streaming replies, and a cap on steps per request.
- Plugin system: every file in `jarvis/tools/` is loaded at startup.
- Tools: `read_file`, `list_dir`, `search_files`, `write_file`, `make_dir`,
  `move_file`, `delete_file`, `run_command`, `run_python`.
- Three-tier permission gate (auto / confirm / blocked) configured in
  `settings.toml`, with per-call escalation and blocked command patterns.
- Untrusted-content handling: file contents and command output are wrapped
  as data; after reading a file outside the workspace, every change in that
  request needs confirmation.
- Action log (`~/.jarvis/actions.jsonl`) with secret redaction; `/log`.
- Emergency stop: Stop button, `/stop`, and `python -m jarvis stop`.
- Interfaces: desktop window, browser, and terminal chat.
- 52 automated tests.

Not yet verified on Windows (built and tested on Linux): the PowerShell
command path, process-tree killing via `taskkill`, and the pywebview window.
