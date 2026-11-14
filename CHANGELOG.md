# Changelog

## 0.17.0 — Faster in the browser; unrestricted by default (2026-11-14)

Changed
- The shipped permission mode is now `unrestricted`: nothing asks except
  banking, payment and finance sites and apps. A mode you chose yourself
  under CONTROL > Settings still wins.
- Working a website takes far fewer steps. Opening a page, clicking and
  typing each hand JARVIS the page as it is afterwards, so it no longer
  reads the page separately between every action. Sending a chat message
  is now three steps: open, click the conversation, type and send.
- The extension waits a few seconds for script-built pages (WhatsApp Web,
  mail, chat apps) to finish drawing before reading them, instead of
  returning an empty page.
- Clickable boxes that are not real links or buttons, such as a chat in a
  conversation list, are now numbered and can be clicked.
- When a chat box ignores Enter, the extension presses the Send button
  next to it.
- JARVIS is told not to list tabs, re-read, or look at the screen to
  double-check a website it is already working in.

Not yet verified
- Tested against a stand-in chat page, not against WhatsApp Web itself.
  The browser extension must be reloaded (it is now version 1.1.0).

## 0.16.0 — Unrestricted means no questions, except banking (2026-11-14)

Changed
- Unrestricted mode now asks nothing at all, with one exception: clicking
  or typing on a banking, payment or finance website, or in a desktop app
  or browser window that looks like one, always asks, in every mode.
  Passwords, card numbers and blocked system commands are still refused.

Fixed
- JARVIS typed messages into its own input box. After you answered a
  question (or typed a request) JARVIS's window was in front, so the
  keystrokes landed there. It now remembers the window it was working in,
  ignores its own window, and brings the right one forward before every
  click and keystroke. Answering a question no longer moves the cursor
  into JARVIS's input box either.

Not yet verified
- The window handling is Windows-only code and has not been run on a real
  Windows machine yet.

## 0.15.0 — One approval per site or app (2026-11-14)

Changed
- An approved website is now approved for everything: on it, JARVIS no
  longer asks before sending, posting, submitting or deleting. Unapproved
  sites ask once, with "Yes, and always on this site". Banking and payment
  sites still ask every time, and passwords and card details are still
  never entered.
- Desktop apps can be approved the same way. Clicking and typing in an app
  after reading web content asks once, with "Yes, and always in <app>";
  after that it does not ask there. Browsers cannot be approved as apps.
- After typing with Enter, JARVIS is told plainly that a chat message has
  been sent and that an empty box is normal, so it does not send the same
  message twice.

Not yet verified
- Working out which program a window belongs to is Windows-only code. If
  it cannot tell, JARVIS simply asks each time, as before.

## 0.14.1 — Browser extension connection fixes (2026-11-14)

Fixed
- The extension's popup said "Connecting…" forever when it could not reach
  JARVIS. It now says what is wrong: JARVIS not found, or a wrong pairing
  code.
- JARVIS and the extension now agree on a short list of ports (47821 to
  47824) instead of one, so they still find each other when the first is
  taken, for example by a copy of JARVIS that has not finished closing.
- A newly pasted pairing code is tried at once.

Added
- CONTROL > Accounts > Browser shows which port JARVIS is on, and warns if
  it is one the extension cannot reach. The port is also written to the
  action log at start.

After updating, reload the extension: on the browser's Extensions page,
click the round arrow on the JARVIS card.

## 0.14.0 — JARVIS in your browser; sight on its own judgment (2026-11-14)

Added
- A browser extension (`extension/`, for Chrome and Edge) and browser tools:
  `browser_tabs`, `browser_open`, `browser_read`, `browser_scroll`,
  `browser_click`, `browser_type`, `browser_select`, `browser_key`,
  `browser_close`. JARVIS reads and works pages in your own browser,
  including sites you are signed in to.
- Approved sites: JARVIS acts freely on sites you approve and asks
  elsewhere, with "Yes, and always on this site" in the prompt. Sending,
  buying and deleting always ask; banking and payment sites always ask;
  password fields and card details are never filled in.
- CONTROL > Accounts > Browser: pairing code, setup steps, approved sites.

Changed
- Sight: JARVIS may now look at the screen on its own judgment when that
  helps with a request, without being asked each time. The eye button still
  switches sight off completely.

Tested
- The extension was loaded into a real Chromium and driven end to end
  against a test website (read, type, choose, click, search, follow links,
  refuse a password field). It has not been tried on real sites such as
  WhatsApp Web, which build their pages in more complicated ways.

## 0.13.0 — Sight, a setup screen and an installer (2026-11-13)

Added
- Sight: `look_at_screen` takes one picture of the window in front or the
  whole screen, when asked, and has Google Gemini describe it. An eye button
  switches sight off entirely. The latest picture is kept at
  `~/.jarvis/last_look.jpg`. Connect with a free Gemini key.
- A setup screen, shown the first time JARVIS starts and available from
  CONTROL > Settings: what to call you, your city, which model to use, the
  key, and the permission mode. It checks that the model answers.
- Accounts can be connected from CONTROL > Accounts, without a terminal.
- `installer/Install-JARVIS.bat`: one file that installs or updates JARVIS
  on a Windows PC, including Python and Git if missing.

Changed
- Model keys may now be kept in Windows Credential Manager (entered on the
  setup screen) as well as in environment variables.
- JARVIS opens its window even when no model is configured, instead of
  stopping with an error.
- New installations start in Careful mode (chosen on the setup screen).

Not yet verified
- The installer is PowerShell and has not been run; it could only be
  proofread here.
- Capturing the screen is Windows-only code, tested with a stand-in.
- Gemini is tested against a stand-in following Google's documentation,
  not with a live key.

## 0.12.0 — Dependability (2026-11-13)

Added
- The conversation survives a restart: it is saved to
  `~/.jarvis/conversation.json` and redrawn in the window. The model
  continues from a written recap of it.
- Long conversations are condensed automatically once they pass
  `context_budget` tokens (default 40,000), with a notice in the window.
- Token usage: a Usage widget (today against the daily allowance, and the
  size of the conversation), `/usage`, a warning at 80% of the allowance,
  and a per-day record in `~/.jarvis/usage.json`. Uses the service's own
  figures where it reports them, and estimates otherwise.
- Updating from the window: CONTROL > Settings shows the version and any
  updates, with Update now and Restart JARVIS now.
- `settings.local.toml`: personal settings layered over `settings.toml` and
  ignored by git, so updates never clash with them.

Changed
- `/clear` now also forgets the saved conversation.

Not yet verified
- Restarting from the window is Windows-only and untested here.
- Whether the IFM service reports token counts and the remaining allowance
  in the way its documentation describes. If it does not, JARVIS falls back
  to its own estimate automatically.

## 0.11.2 — Documentation (2026-11-12)

Changed
- README brought up to date and reordered for a first-time reader: a
  screenshot, a contents list, corrected setup steps (Python 3.14, the
  optional extras, `setup`, `install-shortcut`), the three model providers
  with the hosted one as the default, the full command lists, a "What
  leaves your computer" section, and where JARVIS keeps its files.
- Removed statements that described finished features as still to come.

## 0.11.1 — Stop asking for the microphone on every start (2026-11-12)

Fixed
- The window asked for microphone permission each time JARVIS started.
  Two causes: it used a different port (so a different address) on every
  start, and it ran as a private window that forgets its settings on exit.
  It now prefers a fixed port (47821), keeps its settings in
  `~/.jarvis/webview`, and answers the permission question for its own page
  automatically where the browser control allows.

Not yet verified: this is Windows-only code and untested here.

## 0.11.0 — A heads-up-display window (2026-11-12)

Changed
- The window is redesigned as a HUD: a large segmented central dial on a
  black field, with live widgets around it.
- The dial's twelve segments name the tool groups and light up as JARVIS
  uses them.
- CONTROL and STOP are restyled as angled keys; they work as before.

Added
- Widgets: date and clock, processor / memory / disk / battery gauges,
  connected accounts, the next scheduled item, weather.
- Quick-launch buttons, configured under `[launcher]` in `settings.toml`.
- `psutil` is now a dependency, for the system gauges.

## 0.10.0 — Scheduling, the tray icon, GitHub and Notion (2026-11-12)

Added
- Reminders and scheduled tasks (`schedule_add`, `schedule_list`,
  `schedule_remove`; `/schedule`, `/unschedule`; a Schedule tab in the
  control panel). Results are shown, spoken and sent as notifications.
- A ready-made morning briefing at 08:00: weather, calendar, unread email.
- A `weather` tool (Open-Meteo; no key).
- A tray icon: closing the window hides JARVIS, which keeps listening and
  keeps its schedule. `python -m jarvis autostart on` starts it in the tray
  when you sign in to Windows.
- GitHub (`github_repos`, `github_issues`, `github_read`, `github_file`,
  `github_notifications`, `github_create_issue`, `github_comment`) and
  Notion (`notion_search`, `notion_read`, `notion_create_page`,
  `notion_append`), connected with `python -m jarvis connect github|notion`.

Changed
- The window can play sound and use the microphone without a first click,
  so the wake word and spoken reminders work when JARVIS starts hidden.

Not yet verified
- The tray icon, hiding the window, starting with Windows and Windows
  notifications are Windows-only and untested here. In particular, the
  wake word while the window is hidden has not been tried.
- GitHub and Notion are tested against stand-ins following their published
  interfaces, not live accounts. The weather service rate-limited the build
  machine, so the weather tool is likewise tested with stand-in data.

## 0.9.0 — Launcher, documents, follow-up listening, control panel (2026-11-12)

Added
- `python -m jarvis install-shortcut`: a JARVIS icon on the desktop and in
  the Start menu, starting without a terminal window. Problems at startup
  appear in a message box; output goes to `~/.jarvis/jarvis.log`.
- `read_document`: reads PDF, Word, PowerPoint and Excel files.
- Follow-up listening: after a spoken answer JARVIS listens for a few
  seconds for your reply (`follow_up` under `[voice]`).
- A control panel in the window (CONTROL button): memory, activity,
  accounts and settings. Settings changes apply at once and are saved to
  `~/.jarvis/overrides.json`.

Changed
- JARVIS's own settings files are now protected paths: its file tools need
  approval to write to them.

Not yet verified
- The shortcut and the windowless start are Windows-only and untested here.
- Follow-up listening was tested with a simulated microphone, not against
  real room noise or speaker echo.

## 0.8.0 — Gmail, Calendar and Spotify (2026-11-12)

Added
- Direct connections to Gmail, Google Calendar and Spotify, replacing
  slow click-by-click control of their websites and apps.
- `python -m jarvis connect|disconnect|connections`. Sign-in uses each
  provider's standard browser approval; tokens go in the OS keychain.
- Gmail: `gmail_search`, `gmail_read`, `gmail_send`, `gmail_draft`.
  Sending always shows the complete message and waits for approval.
- Calendar: `calendar_events`, `calendar_create`, `calendar_delete`.
  Inviting guests asks first, since it emails them.
- Spotify: `spotify_play`, `spotify_queue`, `spotify_control`,
  `spotify_now_playing`.
- Reading email or calendar content counts as untrusted, like a web page.

Not yet verified
- No Google or Spotify account was available on the build machine. These
  tools are tested against stand-ins that follow each service's published
  interface; their first real run is yours.

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
