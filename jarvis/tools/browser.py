"""Browser tools: read and work web pages in the user's own Chrome or Edge,
through the JARVIS extension. Because this is the user's real browser, it
sees what they see, including sites they are signed in to.

That makes these the most powerful tools JARVIS has, so they have their own
permission rules (in trusted mode):

  * Reading a page, listing tabs, opening a page, scrolling: no question.
  * On an APPROVED site: no question, whatever the action, including
    sending and submitting. Approving a site means trusting JARVIS on it.
  * Anywhere else: asks, and offers to approve the site there and then.
  * Banking and payment sites ([browser] always_ask): always ask, even
    when approved.
  * Password fields and card numbers: never, in any mode.

In careful mode every click and keystroke asks. Whatever a page says is
untrusted data; reading one also makes JARVIS's other tools (files,
commands, email) ask before acting for the rest of that request.
"""

from __future__ import annotations

import re

from jarvis.core.tools import AUTO, BLOCKED, CONFIRM, ToolContext, ToolResult, tool
from jarvis.integrations.browser import BrowserError, always_asks, is_approved, site_of
from jarvis.tools.desktop import looks_like_card_number

PAGE_CHARS = 12_000
_TAB = {"type": "integer", "description": "Tab id from browser_tabs. Omit for the tab you are working in."}


def _bridge(ctx: ToolContext):
    if ctx.browser is None:
        raise BrowserError("The browser tools are only available in the JARVIS window, not in terminal chat.")
    return ctx.browser


def _guard(func):
    def wrapper(args: dict, ctx: ToolContext):
        try:
            return func(args, ctx)
        except BrowserError as exc:
            return ToolResult(str(exc), is_error=True)

    wrapper.__name__ = func.__name__
    wrapper.__module__ = func.__module__
    return wrapper


def _element(args: dict, ctx: ToolContext) -> dict | None:
    page = ctx.browser.page(args.get("tab")) if ctx.browser is not None else None
    return (page or {}).get("elements", {}).get(args.get("ref")) if page else None


def _where(args: dict, ctx: ToolContext) -> str:
    page = ctx.browser.page(args.get("tab")) if ctx.browser is not None else None
    return f"on {site_of(page['url'])} ({page.get('title', '')[:60]})" if page and page.get("url") else "in the browser"


def _name(element: dict | None, ref) -> str:
    return f'{element["kind"]} "{element.get("label", "")}"' if element else f"element {ref}"


def _rule(args: dict, ctx: ToolContext):
    """The permission rule for every click and keystroke in the browser."""
    if ctx.browser is None:
        return None
    page = ctx.browser.page(args.get("tab"))
    if not page or not page.get("url"):
        return CONFIRM, "JARVIS has not read this tab yet, so cannot tell which site it is", "strict"
    element = _element(args, ctx)
    if element and element.get("secret") == "password":
        return BLOCKED, "it is a password field, which JARVIS never fills in"
    if element and element.get("secret") == "card" or looks_like_card_number(str(args.get("text", ""))):
        return BLOCKED, "it involves payment card details, which JARVIS never enters"
    url = page["url"]
    if always_asks(ctx.settings, url):
        return CONFIRM, f"{site_of(url)} looks like a banking or payment site, which always asks", "always"
    if not is_approved(ctx.settings, url):
        return CONFIRM, f"{site_of(url)} is not an approved site", "strict", {"offer_site": site_of(url)}
    return None  # an approved site: go ahead with whatever is needed


def _outline(result: dict, start: int = 0) -> str:
    tab, text = result["tab"], result["text"]
    chunk = text[start : start + PAGE_CHARS]
    lines = [f"Tab {tab['id']}: {result.get('title') or tab.get('title', '')}", result.get("url") or tab.get("url", ""), ""]
    lines.append(chunk or "(The page has no readable text.)")
    if start + PAGE_CHARS < len(text):
        lines.append(f"\n[Showing characters {start}-{start + len(chunk)} of {len(text)}. Call browser_read with start={start + PAGE_CHARS} for more.]")
    scroll = result.get("scroll") or {}
    if scroll.get("height", 0) > scroll.get("view", 0) * 1.5:
        lines.append("[Some pages only load more as you scroll: use browser_scroll, then read again.]")
    return "\n".join(lines)


def _read(ctx: ToolContext, tab: int | None, start: int = 0, result: dict | None = None, prefix: str = "") -> ToolResult:
    """Show a page. `result` is a reading the extension already sent back
    with an action, which saves asking for it again."""
    bridge = _bridge(ctx)
    if result is None:
        result = bridge.call("read", {"tab": tab if tab is not None else bridge.working_tab})
    if len(result.get("elements", [])) < 3 and len(result.get("text", "")) < 200:
        prefix += "[The page is still loading or shows very little. Call browser_read again in a moment.]\n\n"
    bridge.remember({**result["tab"], "url": result.get("url") or result["tab"].get("url", "")}, result.get("elements", []))
    return ToolResult(prefix + _outline(result, start), untrusted_source=result.get("url", "web page"), taints=True)


# ---------------------------------------------------------------- looking


@tool(
    name="browser_tabs",
    description="List the tabs open in the user's browser, with their ids, titles and addresses.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: "List the browser's open tabs",
)
@_guard
def browser_tabs(args: dict, ctx: ToolContext) -> ToolResult:
    tabs = _bridge(ctx).call("tabs")
    rows = [f"{'*' if t['active'] else ' '} tab {t['id']}: {t['title'][:80]}  {t['url'][:120]}" for t in tabs]
    return ToolResult("\n".join(rows) or "No tabs are open.", untrusted_source="browser tabs")


@tool(
    name="browser_open",
    description=(
        "Open a web address in the user's own browser and read the page. Unlike read_page, this sees the page as "
        "the user does, including sites they are signed in to. Opens a new tab unless new_tab is false."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full address starting with http:// or https://"},
            "new_tab": {"type": "boolean", "description": "Default true. False loads it in the tab you are working in."},
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    tier=AUTO, kind="launch",
    describe=lambda a, c: f"Open {a['url']} in the browser",
)
@_guard
def browser_open(args: dict, ctx: ToolContext) -> ToolResult:
    url = args["url"].strip()
    if not re.match(r"https?://[^\s/]+", url, re.IGNORECASE):
        return ToolResult("Only http and https web addresses can be opened.", is_error=True)
    bridge = _bridge(ctx)
    tab = bridge.call("open", {"url": url, "new_tab": args.get("new_tab", True), "tab": bridge.working_tab})
    bridge.remember(tab, [])
    page = tab.get("page")
    return _read(ctx, tab["id"], result={"tab": tab, **page} if page else None)


@tool(
    name="browser_read",
    description=(
        "Read a tab in the user's browser: its text in reading order, with every link, button and field numbered "
        "like [12]. Use those numbers with browser_click and browser_type. browser_open, browser_click and "
        "browser_type already return the page as it is afterwards, so only call this for a tab you have not seen "
        "or to read further down a long page."
    ),
    input_schema={
        "type": "object",
        "properties": {"tab": _TAB, "start": {"type": "integer", "minimum": 0, "description": "Character offset to continue from."}},
        "additionalProperties": False,
    },
    tier=AUTO, read_only=True, kind="read",
    describe=lambda a, c: "Read the page in the browser",
)
@_guard
def browser_read(args: dict, ctx: ToolContext) -> ToolResult:
    return _read(ctx, args.get("tab"), args.get("start", 0))


@tool(
    name="browser_scroll",
    description="Scroll the page in the browser: down, up, top or bottom. Read the page again afterwards.",
    input_schema={
        "type": "object",
        "properties": {"direction": {"type": "string", "enum": ["down", "up", "top", "bottom"]}, "tab": _TAB},
        "required": ["direction"],
        "additionalProperties": False,
    },
    tier=AUTO, kind="launch",
    describe=lambda a, c: f"Scroll {a['direction']} in the browser",
)
@_guard
def browser_scroll(args: dict, ctx: ToolContext) -> ToolResult:
    bridge = _bridge(ctx)
    done = bridge.call("scroll", {"direction": args["direction"], "tab": args.get("tab", bridge.working_tab)})
    return ToolResult(f"Scrolled {args['direction']} (now at {done.get('y')} of {done.get('height')} pixels). Read the page again to see it.")


# ------------------------------------------------------------------ acting


def _act(ctx: ToolContext, action: str, args: dict) -> ToolResult:
    bridge = _bridge(ctx)
    tab = args.get("tab", bridge.working_tab)
    if action != "key" and _element(args, ctx) is None:
        return ToolResult(f"There is no element {args.get('ref')} in what you last read. Use browser_read first.", is_error=True)
    ctx.kill.check()
    done = bridge.call(action, {**args, "tab": tab})
    bridge.remember(done["tab"], [] if done.get("navigated") else None)
    extra = f" The tab is now at {done['tab']['url']}." if done.get("navigated") else ""
    note = ""
    if action == "type" and args.get("submit"):
        note = " In a chat or message box, Enter SENDS: the message has gone and the box is now empty, which is normal; do not type it again."
    summary = f"Done: {done.get('done', action)}.{extra}{note}"
    if done.get("page"):
        # The extension read the page straight after acting: show it now.
        return _read(ctx, done["tab"]["id"], result={"tab": done["tab"], **done["page"]}, prefix=summary + " The page now:\n\n")
    return ToolResult(f"{summary} Read the page again to see the result.")


@tool(
    name="browser_click",
    description="Click a link, button or other element in the browser, by its number from browser_read.",
    input_schema={
        "type": "object",
        "properties": {"ref": {"type": "integer", "minimum": 1}, "tab": _TAB},
        "required": ["ref"],
        "additionalProperties": False,
    },
    tier=CONFIRM, kind="control", own_trust_rules=True,
    escalate=_rule,
    describe=lambda a, c: f"Click the {_name(_element(a, c), a.get('ref'))} {_where(a, c)}",
)
@_guard
def browser_click(args: dict, ctx: ToolContext) -> ToolResult:
    return _act(ctx, "click", args)


@tool(
    name="browser_type",
    description=(
        "Type into a field in the browser, by its number from browser_read. Replaces what is there unless clear "
        "is false. Set submit to true to press Enter afterwards (to run a search or send a chat message). Never "
        "use this for passwords or payment details; ask the user to enter those."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "ref": {"type": "integer", "minimum": 1},
            "text": {"type": "string"},
            "submit": {"type": "boolean", "description": "Press Enter afterwards. Default false."},
            "clear": {"type": "boolean", "description": "Replace the existing text. Default true."},
            "tab": _TAB,
        },
        "required": ["ref", "text"],
        "additionalProperties": False,
    },
    tier=CONFIRM, kind="control", own_trust_rules=True,
    escalate=_rule,
    describe=lambda a, c: (
        f"Type into the {_name(_element(a, c), a.get('ref'))} {_where(a, c)}"
        + (" and press Enter" if a.get("submit") else "") + f":\n\n{a.get('text', '')}"
    ),
)
@_guard
def browser_type(args: dict, ctx: ToolContext) -> ToolResult:
    return _act(ctx, "type", args)


@tool(
    name="browser_select",
    description="Choose an option in a dropdown in the browser, by the dropdown's number from browser_read.",
    input_schema={
        "type": "object",
        "properties": {"ref": {"type": "integer", "minimum": 1}, "option": {"type": "string", "description": "The option's text."}, "tab": _TAB},
        "required": ["ref", "option"],
        "additionalProperties": False,
    },
    tier=CONFIRM, kind="control", own_trust_rules=True,
    escalate=_rule,
    describe=lambda a, c: f'Choose "{a.get("option")}" in the {_name(_element(a, c), a.get("ref"))} {_where(a, c)}',
)
@_guard
def browser_select(args: dict, ctx: ToolContext) -> ToolResult:
    return _act(ctx, "select", args)


@tool(
    name="browser_key",
    description="Press Enter, Escape or Tab in the browser, in whatever currently has the cursor.",
    input_schema={
        "type": "object",
        "properties": {"key": {"type": "string", "enum": ["Enter", "Escape", "Tab"]}, "tab": _TAB},
        "required": ["key"],
        "additionalProperties": False,
    },
    tier=CONFIRM, kind="control", own_trust_rules=True,
    escalate=_rule,
    describe=lambda a, c: f"Press {a.get('key')} {_where(a, c)}",
)
@_guard
def browser_key(args: dict, ctx: ToolContext) -> ToolResult:
    return _act(ctx, "key", args)


@tool(
    name="browser_close",
    description="Close a tab in the user's browser.",
    input_schema={"type": "object", "properties": {"tab": _TAB}, "additionalProperties": False},
    tier=CONFIRM, kind="control", own_trust_rules=True,
    escalate=_rule,
    describe=lambda a, c: f"Close the tab {_where(a, c)}",
)
@_guard
def browser_close(args: dict, ctx: ToolContext) -> ToolResult:
    bridge = _bridge(ctx)
    tab = args.get("tab", bridge.working_tab)
    done = bridge.call("close", {"tab": tab})
    bridge.pages.pop(done["closed"]["id"], None)
    if bridge.working_tab == done["closed"]["id"]:
        bridge.working_tab = None
    return ToolResult(f"Closed the tab \"{done['closed']['title'][:80]}\".")
