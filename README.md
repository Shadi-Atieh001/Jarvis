# JARVIS

A personal AI assistant that runs on your own machine and acts on your behalf,
with a permission system that decides what it may do without asking.

**Status: Phase 1 of 5.** It runs free on a local model through Ollama, or
on Claude through the Anthropic API. Chat, the agent loop, file/shell/code tools,
permissions, the action log and the emergency stop are built. Memory,
integrations (Gmail, Calendar, Notion, Spotify, GitHub, WhatsApp),
scheduling and voice come next; see [Roadmap](#roadmap).

## Setup (Windows)

1. Install [Python 3.13 or newer](https://www.python.org/downloads/windows/).
   Tick "Add python.exe to PATH" in the installer.
2. Open PowerShell and get the code:

   ```powershell
   git clone https://github.com/Shadi-Atieh001/Jarvis.git
   cd Jarvis
   ```

3. Create a private Python environment and install JARVIS into it:

   ```powershell
   py -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -e ".[desktop,dev]"
   ```

   If PowerShell refuses to run `Activate.ps1`, use `.venv\Scripts\activate.bat`
   from Command Prompt instead.

4. Choose a brain (next section).

## Choosing a brain

`provider` in `settings.toml` decides which model JARVIS thinks with.

### Free: a local model with Ollama (the default)

1. Install Ollama from <https://ollama.com/download> and let it start.
2. Download a model that supports tool calling (about 5 GB):

   ```powershell
   ollama pull qwen3:8b
   ```

3. Start JARVIS. Nothing leaves your computer and there is no cost.

To use a different model, pull it and change `model` under `[ollama]` in
`settings.toml`. Larger models are noticeably more reliable if your graphics
card has the memory. Models that support tools are listed at
<https://ollama.com/search?c=tool>.

What to expect from a small local model: it is fine for conversation and
simple one- or two-step tasks, but it will sometimes pick the wrong tool,
leave out an argument, or lose the thread on longer jobs. The permission
gate applies to it exactly as it does to Claude, so a mistake still cannot
overwrite, delete or run anything without your yes. Small models are also
easier to fool with instructions hidden in files, which is one more reason
to read confirmation prompts before approving.

### A hosted service with its own key (OpenAI-compatible)

Many model services (OpenRouter, Groq, Together and others) use the OpenAI
"chat completions" format. To use one:

1. In `settings.toml` set `provider = "openai_compatible"`, then under
   `[openai_compatible]` fill in `base_url` (from the service's API
   documentation, ending in `/v1`) and `model`. The model must support tool
   calling.
2. Store the key in your Windows user environment, never in a file:

   ```powershell
   setx JARVIS_API_KEY "your-key-here"
   ```

3. Open a new terminal and start JARVIS.

With this option your messages, and any file contents JARVIS reads, are sent
to that service.

### Paid: Claude through the Anthropic API

Set `provider = "anthropic"` in `settings.toml`, then store your API key in
your Windows user environment (not in any file in this folder):

```powershell
setx ANTHROPIC_API_KEY "your-key-here"
```

Open a new terminal so the key is picked up. This uses `claude-fable-5-2`
and is billed per use by Anthropic.

## Voice

Click the microphone (or press Ctrl+Space), speak, and stop talking; JARVIS
transcribes what you said, and answers aloud when you spoke to it. Clicking
the microphone while it is talking interrupts it. Speech recognition
(Whisper) and the British voice (Piper) both run on your computer.

One-time setup:

```powershell
pip install -e ".[voice]"
python -m jarvis voice-setup
```

`voice-setup` downloads the models (about 210 MB), then says a sentence and
listens to itself to confirm both directions work.

- **Python 3.15 is too new for the speech libraries.** If `pip install`
  fails on `onnxruntime`, install Python 3.14 (`winget install
  Python.Python.3.14`), delete the `.venv` folder, recreate it with
  `py -3.14 -m venv .venv`, and install again.
- **Approving actions is by click only.** Saying "yes" aloud does not
  approve a permission prompt, so nothing overheard can authorise an action.
- **If the voice is missing** JARVIS falls back to the voice built into
  Windows. If recognition is missing, the microphone button is disabled.
- Settings are under `[voice]` in `settings.toml`: recognition model,
  voice, and when to answer aloud (`when_spoken`, `always`, `never`).

The wake word ("Hey Jarvis") is not built yet; it comes next.

## Running

| Command | What it does |
|---|---|
| `python -m jarvis` | Opens the desktop window |
| `python -m jarvis web` | Same interface in your browser |
| `python -m jarvis chat` | Chat in the terminal |
| `python -m jarvis stop` | **Emergency stop**, from any terminal |
| `python -m jarvis resume` | Clears the emergency stop |
| `python -m jarvis log 50` | Shows the last 50 actions |
| `python -m jarvis voice-setup` | Downloads and tests the speech models |
| `python -m pytest` | Runs the tests |

Inside a chat, type `/help` for commands: `/tools`, `/log`, `/stop`,
`/resume`, `/clear`, `/quit`.

## Permissions

Every tool call goes through one gate (`jarvis/core/permissions.py`) before
it runs. The gate is ordinary code; the model cannot talk its way past it.

| Tier | Meaning | Phase 1 examples |
|---|---|---|
| auto | Runs without asking | Reading, listing and searching files; creating new files in the workspace |
| confirm | Shows exactly what will happen and waits for your yes | Overwriting or deleting; anything outside the workspace; every shell command and script |
| blocked | Never runs | Commands that change firewall, antivirus, accounts, boot or disk settings |

Tiers are set in `settings.toml` under `[permissions.tools]`. Things worth
knowing:

- **A tool can escalate a single call.** `write_file` is "auto", but
  overwriting a file or writing outside the workspace still asks. Settings
  can make any tool stricter; they cannot switch that escalation off.
- **Commands and scripts always ask by default.** A command started in the
  workspace can still reach your whole machine, so there is no safe subset
  to wave through. You can set `run_python = "auto"` if you accept that risk.
- **Sensitive paths** (`.ssh`, `.env`, browser profiles, key files; see
  `[permissions.sensitive]`) need confirmation even to read, and are left
  out of content searches.
- **Blocked patterns are a backstop, not a guarantee.** They are regular
  expressions over the command text and can be evaded by a determined
  attacker. The real protection is that you see every command before it runs.
- **Payments and moving money** have no tool at all, so they cannot happen.
  When web and browser tools arrive they will be blocked at the tool level.

### Untrusted content

Text that comes from files and command output (later: web pages and email)
is wrapped in `<untrusted_data>` tags before the model sees it, and the model
is told to treat it as information only and to report any instructions it
finds there. Because a model can still be fooled, there is a second,
mechanical defence: once JARVIS has read a file from outside the workspace,
every action that changes anything needs your confirmation for the rest of
that request (`confirm_after_untrusted` in `settings.toml`).

### Emergency stop

The Stop button, `/stop`, or `python -m jarvis stop` in any terminal. It
halts the current request, kills any command JARVIS started, and refuses all
further work until `/resume`. The command-line form works by creating
`~/.jarvis/STOP`, so it works even if the window has frozen. In terminal
chat, Ctrl+C interrupts the current task without engaging the stop.

### Action log

Everything JARVIS does is appended to `~/.jarvis/actions.jsonl`: each
message you send, each tool call with its arguments, the tier, whether it
ran automatically, was approved, denied or blocked, and the result. API keys
and anything that looks like a password or token are removed before writing.

## How it is organised

```
settings.toml        everything you can configure
jarvis/
  __main__.py        the command line (python -m jarvis ...)
  app.py             builds a Jarvis from settings
  core/
    agent.py         the agent loop
    brains.py        the model backends: Anthropic, Ollama, OpenAI-compatible
    permissions.py   the permission gate
    tools.py         tool definitions and the plugin loader
    persona.py       the system prompt (personality and rules)
    actionlog.py     the action log
    killswitch.py    the emergency stop
    commands.py      /slash commands
    config.py        reads settings.toml
  voice/engine.py    speech-to-text and text-to-speech
  tools/             one file per group of tools
  ui/
    terminal.py      terminal chat
    server.py        local server behind the window
    desktop.py       the window itself
    web/index.html   the interface
tests/
```

### Adding a tool

Create a file in `jarvis/tools/`, for example `jarvis/tools/hello.py`:

```python
from jarvis.core.tools import tool

@tool(
    name="say_hello",
    description="Greets someone by name.",
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
        "additionalProperties": False,
    },
    tier="auto",      # auto | confirm | blocked; omit to use the default (confirm)
    read_only=True,   # True only if it changes nothing
)
def say_hello(args, ctx):
    return f"Hello, {args['name']}."
```

Restart JARVIS and it is available. Optional extras on `@tool`:
`escalate` (raise the tier for risky calls), `describe` (the text shown when
asking permission), `blockable_text` (text checked against blocked patterns).
`jarvis/tools/files.py` uses all three.

## Decisions you may need to understand

- **Two brains, one loop.** `brains.py` holds both backends. The history is
  kept in Anthropic's message format and translated for Ollama on each
  request, so everything else (permissions, logging, tools) is shared.
- **The API key** is read from `ANTHROPIC_API_KEY` by the Anthropic library.
  JARVIS never stores it, and the log scrubs it.
- **The conversation history is append-only.** The model verifies that
  earlier turns were not edited, so the code only ever adds to
  `Jarvis.messages`. To start over, use `/clear`.
- **The system prompt never changes between requests** (the current time is
  added to your message instead). This lets Anthropic cache it, which makes
  replies cheaper and faster. Avoid putting changing values in `persona.py`.
- **`effort`** in `settings.toml` controls how hard the model thinks.
  "medium" is the default; raise it to "high" for difficult work.
- **`refusal_fallback`**: if the model's safety filter declines a request,
  Anthropic retries it on another of its models. Turn it off to see the
  refusal instead.
- **The "sandbox" is a folder, not a virtual machine.** Scripts run in
  `~/.jarvis/workspace` with a timeout, but with your user account's full
  rights. That is why running code asks first.
- **The window is a local web page.** The server listens only on
  `127.0.0.1` and requires a random token plus a matching origin, so other
  programs and web pages cannot send JARVIS commands.

## Roadmap

1. **Core** — done.
2. **Memory** — SQLite with local embeddings; `/memories` to view and delete.
3. **Integrations** — Gmail and Calendar, then GitHub, Notion, Spotify, web
   search and browsing, then WhatsApp Web. Tokens stored in Windows
   Credential Manager.
4. **Scheduling** — reminders, recurring tasks, the 8am briefing; tray icon
   and start at login.
5. **Voice** — "Hey Jarvis" wake word, local speech-to-text and
   text-to-speech.
