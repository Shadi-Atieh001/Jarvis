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

## Memory

JARVIS remembers across conversations. Tell it things ("my sister is called
Layla", "I prefer short answers") and it saves them; facts that look
relevant to a new request are passed to the model with it. It also keeps a
record of past requests and replies, which it can search when you refer to
something from before.

| Command | What it does |
|---|---|
| `/memories` | Lists everything remembered |
| `/memories sister` | Lists memories related to a word or phrase |
| `/forget 3` | Deletes memory number 3 |
| `/forget all` | Deletes every memory and the record of past exchanges |

- Everything is in one file on your computer, `~/.jarvis/memory.db`.
  Deleting that file also erases all memory.
- Memories relevant to a request are sent to the model along with it. With
  a hosted model, that means they leave your computer at that point.
- Passwords and keys are scrubbed before saving.
- Search is by meaning, using a small model that runs locally (about
  65 MB, downloaded by `python -m jarvis setup`). Without it, search falls
  back to matching words.
- In trusted mode, saving a memory needs your approval if JARVIS has just
  read a web page, so a page cannot plant false "facts".
- `enabled = false` under `[memory]` in `settings.toml` turns it all off.

## Voice

Click the microphone (or press Ctrl+Space), speak, and stop talking; JARVIS
transcribes what you said, and answers aloud when you spoke to it. Clicking
the microphone while it is talking interrupts it. Speech recognition
(Whisper) and the British voice (Piper) both run on your computer.

One-time setup:

```powershell
pip install -e ".[desktop,memory,voice,dev]"
python -m jarvis setup
```

`setup` downloads the models (about 280 MB including memory), then says a
sentence and listens to itself to confirm both directions work.

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

### "Hey Jarvis"

With the window open, say "Hey Jarvis" followed by your request, in one
breath or after the chime. The ear button beside the microphone turns this
on and off, and the window remembers your choice.

- While it is on, the microphone stays open and Windows shows its
  microphone indicator. The audio goes only to JARVIS's own server on your
  computer, is checked for the phrase and discarded. Nothing is recorded or
  transcribed until the phrase is heard, and none of it leaves the machine.
- It does not listen while JARVIS is speaking, working, waiting for an
  approval, or stopped, so it cannot wake itself.
- Each wake is written to the action log.
- If it wakes by mistake, raise `wake_threshold` under `[voice]` in
  `settings.toml`; if it misses you, lower it. `wake_word = false` turns
  the feature off entirely.
- It works only while the JARVIS window is open. Waking from the system
  tray comes with the scheduling phase.

## Running

| Command | What it does |
|---|---|
| `python -m jarvis` | Opens the desktop window |
| `python -m jarvis web` | Same interface in your browser |
| `python -m jarvis chat` | Chat in the terminal |
| `python -m jarvis stop` | **Emergency stop**, from any terminal |
| `python -m jarvis resume` | Clears the emergency stop |
| `python -m jarvis log 50` | Shows the last 50 actions |
| `python -m jarvis setup` | Downloads and tests the memory and speech models |
| `python -m pytest` | Runs the tests |

Inside a chat, type `/help` for commands: `/tools`, `/log`, `/stop`,
`/resume`, `/clear`, `/quit`.

## What JARVIS can do

| Area | Tools |
|---|---|
| Files | read, list, search, write, move, delete |
| Commands and code | run PowerShell commands; write and run Python in the workspace |
| Web | search the web, read a page's text, open a page in your browser |
| Screen | list open windows, read what is in a window, open apps |
| Mouse and keyboard | click, type, press key combinations |

**How it "sees" the screen.** The current model reads text only, so JARVIS
does not look at screenshots. It asks Windows what each window contains
(titles, buttons, menus, text fields and their contents), the same way a
screen reader does. That works well for ordinary apps and browsers. Apps
that draw their own interface, such as games, video and images, expose
little or nothing.

**Web search** uses free public search engines through the `ddgs` library,
with no account or key. They sometimes rate-limit; if a search fails, wait a
minute. Pages that need a login or build their content with scripts may
come back nearly empty; for those, JARVIS can open the page in your browser
and read it from the screen instead.

## Permissions

Every tool call goes through one gate (`jarvis/core/permissions.py`) before
it runs. The gate is ordinary code; the model cannot talk its way past it.

`mode` under `[permissions]` in `settings.toml` sets how much JARVIS may do
without asking:

| Mode | Runs without asking | Asks first |
|---|---|---|
| `careful` | Reading; new files in the workspace | Everything else |
| `trusted` (default) | Commands, code, files anywhere, opening apps, clicking and typing | Deleting; sending (once email and messaging exist); and see "after reading the web" below |
| `unrestricted` | Everything | Nothing |

In every mode:

- **Blocked stays blocked.** Commands that change firewall, antivirus,
  account, boot or disk settings are refused, and so is typing anything
  that looks like a payment card number. The command patterns are a
  backstop rather than a guarantee; a determined attacker could word a
  command to slip past them.
- **Sensitive paths** (`.ssh`, `.env`, browser profiles, key files; see
  `[permissions.sensitive]`) need confirmation to read or write, except in
  `unrestricted`.
- **The Stop button works.**

**After reading the web (trusted mode).** A web page, a search result or a
file from outside the workspace can contain hidden text written to
manipulate an assistant, such as "run this command". Once JARVIS has read
one, it asks before changing files, running commands, clicking or typing
for the rest of that request. Looking things up, reading the screen and
opening pages or apps stay automatic. Your next message starts fresh. If
you would rather never be asked, set `confirm_after_untrusted = false`,
understanding that a malicious page could then make JARVIS act unseen.

Reading the screen does not trigger this, because JARVIS could not operate
any app if it did. That is a deliberate trade-off: text on your screen is
treated as yours.

A per-tool line under `[permissions.tools]` overrides the mode for that
tool, for example `run_command = "confirm"`.

### Untrusted content

Text from files, command output, web pages and the screen is wrapped in
`<untrusted_data>` tags before the model sees it, and the model is told to
treat it as information only and to report any instructions it finds there.
Because a model can still be fooled, the confirmation rule above is the
mechanical backstop.

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
  memory/store.py    long-term memory (SQLite and local embeddings)
  voice/engine.py    speech-to-text and text-to-speech
  tools/             one file per group of tools: files, shell, code, web, desktop
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
