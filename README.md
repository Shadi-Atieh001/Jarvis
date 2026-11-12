# JARVIS

A personal AI assistant that runs on your own machine and acts on your behalf,
with a permission system that decides what it may do without asking.

**Status:** all planned phases are built. It runs on a hosted model, a free
local model through Ollama, or Claude through the Anthropic API. Chat, the agent loop, file/shell/code tools,
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

## Connecting your accounts

Gmail, Google Calendar and Spotify are reached through each service's own
interface, which is much faster and more dependable than clicking through a
browser. Each needs a one-time setup, because Google and Spotify require
every app, even a personal one, to be registered with them.

Sign-in tokens are stored in Windows Credential Manager (entries named
JARVIS), never in a file. Your passwords never reach JARVIS.

| Command | What it does |
|---|---|
| `python -m jarvis connections` | Shows what is connected |
| `python -m jarvis connect google` | Signs in to Gmail and Calendar |
| `python -m jarvis connect spotify` | Signs in to Spotify |
| `python -m jarvis connect github` | Stores a GitHub access token |
| `python -m jarvis connect notion` | Stores a Notion integration secret |
| `python -m jarvis disconnect google` | Signs out and deletes the stored tokens |

### Connecting Google (about 10 minutes, once)

1. Go to <https://console.cloud.google.com> and sign in. Create a new
   project called `JARVIS` (project menu at the top, then New Project).
2. Open **APIs & Services > Library**. Search for **Gmail API** and click
   Enable. Do the same for **Google Calendar API**.
3. Open **APIs & Services > OAuth consent screen** (it may be titled
   Google Auth Platform). Click Get started. App name `JARVIS`, your email
   for support and contact, audience **External**. Finish.
4. Under **Audience**, add your own Gmail address as a **Test user**.
5. Under **Clients**, click Create client. Application type **Desktop
   app**, any name. Create. Copy the **Client ID** and **Client secret**.
6. In a terminal in the Jarvis folder:

   ```powershell
   .venv\Scripts\python -m jarvis connect google
   ```

   Paste the Client ID and secret when asked. Your browser opens. Google
   will warn that it "hasn't verified this app"; that is expected, because
   the app is your own. Choose Advanced, then "Go to JARVIS", and allow the
   permissions listed.

While the app is in Google's "Testing" state, Google ends the sign-in after
seven days and you will need to run `connect google` again. To avoid that,
go to **Audience** and click **Publish app**. It stays private to you; the
warning screen simply remains.

What JARVIS can then do: search and read mail, send (always after showing
you the complete message), save drafts, list calendar events, add events,
delete events (asks first), and invite guests (asks first, since that
emails them).

With a hosted model, the content of any email or event JARVIS reads is sent
to that model's provider.

### Connecting Spotify (about 5 minutes, once)

Needs Spotify Premium (Student is a Premium plan). The account that
creates the app must be the one you listen with.

1. Go to <https://developer.spotify.com/dashboard>, sign in, and click
   Create app.
2. Name and description: anything. **Redirect URI**: exactly
   `http://127.0.0.1:8899/callback`. Tick **Web API**. Save.
3. Open the app's Settings and copy the **Client ID**.
4. In a terminal in the Jarvis folder:

   ```powershell
   .venv\Scripts\python -m jarvis connect spotify
   ```

   Paste the Client ID and approve in the browser.

If Spotify answers "403", open the app's **User Management** page on the
dashboard and add your own Spotify email address there.

Spotify must be open on some device for there to be something to control;
JARVIS can open the app for you first. The sign-in lasts six months, after
which `connect spotify` is needed again.

### Connecting GitHub (about 3 minutes, once)

1. Go to <https://github.com/settings/personal-access-tokens/new> (Settings
   > Developer settings > Personal access tokens > Fine-grained tokens).
2. Name it `JARVIS`, choose an expiry, and under **Repository access** pick
   All repositories, or only the ones JARVIS should see.
3. Under **Permissions > Repository permissions**, set **Contents** to
   Read-only, and **Issues** and **Pull requests** to Read and write (or
   Read-only, if JARVIS should never post).
4. Click Generate token and copy it. Then:

   ```powershell
   .venv\Scripts\python -m jarvis connect github
   ```

   Paste the token when asked (it will not show as you type).

JARVIS can then list your repositories, read issues, pull requests and
files, and open issues or post comments. Posting always shows you the text
and asks first, because it is public. Notifications need a "classic" token
with the `notifications` scope; with a fine-grained token that one tool
will report that it lacks permission.

### Connecting Notion (about 3 minutes, once)

1. Go to <https://www.notion.so/profile/integrations> and click New
   integration. Name it `JARVIS`, choose your workspace, type Internal.
2. Copy the **Internal Integration Secret**. Then:

   ```powershell
   .venv\Scripts\python -m jarvis connect notion
   ```

   Paste the secret when asked.
3. **Share pages with it.** Notion shows an integration nothing until you
   do: open a page in Notion, click `...` at the top right, choose
   Connections, and add JARVIS. Sharing a page also shares everything
   beneath it, so sharing one top-level page is usually enough.

JARVIS can then search your pages, read them, create new pages beneath an
existing one, and add text to a page.

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

### Follow-up listening

After JARVIS answers a spoken request, it listens for about six seconds so
you can reply without saying "Hey Jarvis" again. Say nothing and it goes
back to standing by. Turn it off in the control panel, or with
`follow_up = false` under `[voice]`.

If it ever picks up its own voice or background noise as a reply, turn this
off and tell whoever maintains the code; the pause before it starts
listening is `400` milliseconds in `maybeFollowUp` in `index.html`.

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

## Starting JARVIS without a terminal

Run this once, in a terminal in the Jarvis folder:

```powershell
.venv\Scripts\python -m jarvis install-shortcut
```

It adds a JARVIS icon to your desktop and Start menu. From then on,
double-click it, or press the Windows key and type "Jarvis". You can pin it
to the taskbar by right-clicking the icon.

Started this way there is no terminal window. If JARVIS cannot start (for
example the key is missing), a message box says why, and anything it would
have printed is kept in `~/.jarvis/jarvis.log`.

If you ever move the Jarvis folder, run the command again.

## Reminders, scheduled tasks and the morning briefing

Just ask: "remind me at six to call Layla", "every weekday at 7:30 tell me
my first class", "every Friday at five summarise this week's email".

- A **reminder** says and shows a fixed message at the time.
- A **task** carries out a request at the time, as if you had just asked,
  in its own conversation. The **morning briefing** is a task that comes
  ready-made: every day at 08:00 it reads out Sharjah's weather, today's
  calendar and a summary of unread email. Change its time by cancelling it
  and asking for a new one, or delete it; it will not come back.
- Results appear in the window, are spoken aloud (unless muted or speaking
  is set to Never), and show as a Windows notification.
- See, run or cancel everything under **CONTROL > Schedule**, or with
  `/schedule` and `/unschedule 3`.

Things to know:

- **JARVIS must be running**, in the window or in the tray. Nothing fires
  while it is closed. If it starts within a few hours of a missed item
  (12 hours for a one-off, 3 for a repeating one), the item runs then and
  says it is late.
- **Unattended tasks follow the same permission rules.** If one needs your
  approval, a card appears in the window; with no answer in two minutes,
  the answer is no. The briefing reads email, so in trusted mode anything
  it tried to change afterwards would need your approval.
- **Scheduling asks first if JARVIS has just read a web page or email**, so
  hidden instructions cannot plant a task to run later unseen.
- **The emergency stop pauses the schedule.** Items due during a stop run
  when it is cleared.
- The list lives in `~/.jarvis/schedule.json`, which you can read or edit
  while JARVIS is closed.

Weather comes from Open-Meteo, a free service with no account or key.

## The tray icon and starting with Windows

With the tray icon, closing the window hides JARVIS instead of quitting it.
It keeps listening for "Hey Jarvis" and keeps firing reminders. Find the
icon by the clock (it may be under the small up-arrow). Double-click it to
open the window; right-click for Open, Emergency stop and Quit.

To have JARVIS start in the tray whenever you sign in to Windows:

```powershell
.venv\Scripts\python -m jarvis autostart on
```

`autostart off` undoes it. This is what makes an 8am briefing practical:
JARVIS is already running when the time comes.

**The microphone question.** The first time the window uses the microphone,
Windows' browser engine may ask "wants to use your microphones". Click
Allow once; JARVIS keeps the same address between runs and stores the
window's settings in `~/.jarvis/webview`, so it is remembered. JARVIS also
tries to answer that question itself so it never appears. If you are asked
on every start, another program is probably using port 47821, which forces
JARVIS onto a different address each time.

While JARVIS sits in the tray the microphone stays open for the wake word,
exactly as it does with the window showing. Turn the wake word off in
**CONTROL > Settings** if you would rather it did not.

## The window

The window is laid out as a heads-up display around a central dial.

- **The dial** shows what JARVIS is doing by colour and motion: cyan
  standing by or thinking, green listening, amber waiting for your approval,
  red stopped. The bright ring swells with the sound of your voice or its
  own. The twelve segments around it name the groups of tools (FILES, WEB,
  MAIL, MUSIC and so on); each lights up when JARVIS uses a tool from that
  group, so you can see at a glance what it is touching.
- **Left**: the date and clock (the ring fills as the day passes), processor,
  memory, disk and battery gauges, which accounts are connected, and the
  next scheduled item.
- **Right**: quick-launch buttons, and the weather for your location.
- **CONTROL** and **STOP** are at the top right, as before.

When a conversation starts, the dial moves aside to make room for it. In a
window narrower than about 1040 pixels the side widgets are hidden.

The quick-launch buttons are yours to edit: see `[launcher]` in
`settings.toml`. Each entry is a label and something to open: a folder, a
web address, or an app's name as it appears in the Start menu. Clicking one
opens it directly, without involving the model.

Two fonts are used if present: Bahnschrift (included with Windows 10 and
11) for the labels and Cascadia Code for monospaced text.

## The control panel

Click **CONTROL** at the top right of the window:

- **Schedule**: reminders and scheduled tasks, with Run now and Cancel.
- **Memory**: everything JARVIS remembers, with a Forget button on each
  item and one to forget everything.
- **Activity**: the action log, newest first.
- **Accounts**: which accounts are connected, with a Disconnect button.
  Connecting still happens in a terminal, because it needs you to paste a
  Client ID.
- **Settings**: the permission mode, when to answer aloud, follow-up
  listening and the wake word. Changes apply immediately.

Choices made in the panel are saved to `~/.jarvis/overrides.json` and take
priority over `settings.toml`, which is never rewritten. Delete that file
to return to what `settings.toml` says. JARVIS itself needs your approval
to write to either file, so it cannot quietly loosen its own permissions
through its file tools.

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
| `python -m jarvis install-shortcut` | Adds JARVIS to the desktop and Start menu |
| `python -m jarvis autostart on` | Starts JARVIS in the tray when you sign in |
| `python -m pytest` | Runs the tests |

Inside a chat, type `/help` for commands: `/tools`, `/log`, `/stop`,
`/resume`, `/clear`, `/quit`.

## What JARVIS can do

| Area | Tools |
|---|---|
| Files | read, list, search, write, move, delete |
| Documents | read PDF, Word, PowerPoint and Excel files |
| Commands and code | run PowerShell commands; write and run Python in the workspace |
| Web | search the web, read a page's text, open a page in your browser |
| Screen | list open windows, read what is in a window, open apps |
| Mouse and keyboard | click, type, press key combinations |
| Memory | remember, recall, forget |
| Gmail | search, read, send, draft |
| Google Calendar | list, add and delete events |
| Spotify | play, queue, pause, skip, volume, what's playing |
| GitHub | repositories, issues, pull requests, files, notifications; open issues, comment |
| Notion | search, read, create and add to pages |
| Schedule | reminders, recurring tasks, the morning briefing |
| Weather | current conditions and a three-day forecast |

**How it "sees" the screen.** The current model reads text only, so JARVIS
does not look at screenshots. It asks Windows what each window contains
(titles, buttons, menus, text fields and their contents), the same way a
screen reader does. That works well for ordinary apps and browsers. Apps
that draw their own interface, such as games, video and images, expose
little or nothing.

**Documents.** `read_document` extracts the text of `.pdf`, `.docx`,
`.pptx` (including speaker notes) and `.xlsx` files, so you can ask for a
summary of a lecture, a quiz on a chapter, or the deadlines in a syllabus.
Long documents are read in parts. Two limits: a scanned PDF is pictures of
pages and has no text to read, and the old `.doc`, `.ppt` and `.xls`
formats are not supported (save them as the modern format first).

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
    secrets.py       the OS keychain (Windows Credential Manager)
    permissions.py   the permission gate
    tools.py         tool definitions and the plugin loader
    persona.py       the system prompt (personality and rules)
    actionlog.py     the action log
    killswitch.py    the emergency stop
    commands.py      /slash commands
    config.py        reads settings.toml
  memory/store.py    long-term memory (SQLite and local embeddings)
  scheduler/         the schedule (store.py) and what runs it (runner.py)
  voice/engine.py    speech-to-text and text-to-speech
  integrations/      sign-in for Google and Spotify (oauth.py), GitHub and
                     Notion (tokens.py)
  tools/             one file per group of tools: files, shell, code, web,
                     documents, desktop, memory, google, spotify
  ui/
    terminal.py      terminal chat
    server.py        local server behind the window
    desktop.py       the window itself
    shortcut.py      the desktop and Start menu shortcut
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

Everything in the original plan is built: the core, memory, the
integrations, scheduling and voice. Ideas not yet done:

- WhatsApp, which today works only by controlling WhatsApp Web on screen.
- Seeing screenshots, which needs a model that accepts images.
- A sandbox stronger than a folder (a container or virtual machine).
