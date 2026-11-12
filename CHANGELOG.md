# Changelog

## 0.7.0 — Memory (2026-11-12)

Added
- Long-term memory in `~/.jarvis/memory.db`: saved facts (preferences,
  people, projects) and a searchable record of past exchanges.
- Tools `remember`, `recall`, `forget`; commands `/memories` and `/forget`.
- Relevant memories are included with each request automatically.
- Search by meaning with a local embedding model (`.[memory]` extra), with
  a word-matching fallback when it is not installed.
- `python -m jarvis setup` downloads and tests the memory and speech models
  (`voice-setup` still works).

## 0.6.0 — Fewer prompts, the web, and the screen (2026-11-12)

Added
- Permission modes: `careful`, `trusted` (now the default) and
  `unrestricted`, set with `mode` under `[permissions]`. In trusted mode
  JARVIS only asks before deleting or sending, and before acting after it
  has read a web page or outside file.
- Web tools: `web_search`, `read_page`, `open_url`.
- Screen tools: `list_windows`, `read_screen`, `open_app`, `focus_window`.
- Mouse and keyboard tools: `click`, `type_text`, `press_keys`.
- Typing anything that looks like a payment card number is blocked in every
  mode.

Changed
- Each tool now declares what kind of action it is (read, launch, write,
  execute, control, delete, send); the mode decides how each kind is treated.
- The per-tool tiers previously listed in `settings.toml` are gone; add a
  line under `[permissions.tools]` only to override the mode.

Not yet verified
- Web search could not be tested live from the build machine (search
  engines block its address); it is tested with stand-in results.
- The screen, mouse and keyboard tools use Windows UI Automation and were
  written and tested against a stand-in on Linux. Their first real run is
  on Windows.

## 0.5.0 — "Hey Jarvis" (2026-11-12)

Added
- Wake word: say "Hey Jarvis" and your request, with no click. Detection
  runs locally (openWakeWord); audio is checked in memory and discarded.
  Toggle with the ear button; configure under `[voice]` in `settings.toml`.
- `python -m jarvis voice-setup` now also downloads and tests the wake-word
  model.

Changed
- The window uses one shared microphone capture for the button and the wake
  word.

## 0.4.0 — Voice and a new interface (2026-11-11)

Added
- Voice: talk to JARVIS with the microphone button or Ctrl+Space, and hear
  replies in a British voice. Recognition (Whisper) and speech (Piper) run
  locally. `python -m jarvis voice-setup` downloads and tests the models.
- Replies are spoken sentence by sentence as they arrive; code blocks are
  skipped; speaking over JARVIS interrupts it; a mute button silences it.
- New HUD-style interface with an animated orb that shows what JARVIS is
  doing (standing by, listening, thinking, speaking, awaiting approval,
  halted) and reacts to the sound level.

Notes
- Tested in a browser with a simulated microphone. Not yet verified: the
  microphone permission prompt inside the native Windows window.
- The speech libraries do not yet support Python 3.15; use 3.14 for voice.

## 0.3.1 — Fix follow-up messages on the IFM service (2026-11-11)

Fixed
- The second message of a conversation failed with "Add a supported thinking
  field to each assistant message". The model's reasoning is now kept (never
  displayed) and sent back with each earlier reply, as the service requires.

## 0.3.0 — Hosted services (2026-11-11)

Added
- `provider = "openai_compatible"`: use any hosted model service that speaks
  the OpenAI chat format. Configure `base_url` and `model` under
  `[openai_compatible]`; the key is read from the `JARVIS_API_KEY`
  environment variable. Refuses to send a key over plain http.
- The action log now scrubs the value of every environment variable whose
  name ends in `_API_KEY`, `_TOKEN` or `_SECRET`.

- The shipped `settings.toml` now points at the IFM service
  (`https://api.ifm.ai/v1`, model `IFM/K2-Horizon-375B-A23B`).

Not yet verified against a real service; tested with a stand-in server.

## 0.2.1 — Faster local replies (2026-11-10)

Changed
- Local models no longer "think" silently before each answer (`think` under
  `[ollama]`), stay loaded for 30 minutes between messages (`keep_alive`),
  and use a smaller default context window (8192) so they are more likely
  to fit on the graphics card.
- Each local reply's timings are written to the action log; see `/log`.

## 0.2.0 — Free local model (2026-11-10)

Added
- Ollama backend: JARVIS can run on a model on your own machine at no cost.
  Choose with `provider = "ollama"` or `"anthropic"` in `settings.toml`;
  local settings live under `[ollama]`.
- Startup checks that explain what is missing (Ollama not running, model
  not downloaded, model cannot call tools, API key not set).

Changed
- `provider` now defaults to `"ollama"` in the shipped `settings.toml`.
- Model access moved out of the agent loop into `jarvis/core/brains.py`.

Not yet verified: the Ollama backend is tested against a stand-in server
that follows Ollama's documented API, not against a real Ollama install.

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
