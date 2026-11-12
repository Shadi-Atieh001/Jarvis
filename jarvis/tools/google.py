"""Gmail and Google Calendar, through Google's own interfaces (not by
clicking in a browser). Connect once with:  python -m jarvis connect google

Email contents are untrusted data, like web pages: reading mail "taints"
the request, so in trusted mode JARVIS asks before acting on what it read.
Sending always asks, with the complete message shown.
"""

from __future__ import annotations

import base64
import re
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import parseaddr

from jarvis.core.tools import AUTO, CONFIRM, ToolContext, ToolResult, tool
from jarvis.integrations import oauth
from jarvis.core.secrets import SecretsUnavailable
from jarvis.integrations.oauth import GOOGLE, ApiError, NotConnected
from jarvis.tools.web import page_text

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
CALENDAR = "https://www.googleapis.com/calendar/v3/calendars/primary"
MAX_BODY = 12_000


def _guard(func):
    """Turn connection problems into a message the model can relay."""

    def wrapper(args: dict, ctx: ToolContext):
        try:
            return func(args, ctx)
        except (NotConnected, ApiError, SecretsUnavailable) as exc:
            return ToolResult(str(exc), is_error=True)

    wrapper.__name__ = func.__name__
    wrapper.__module__ = func.__module__
    return wrapper


# ------------------------------------------------------------------ Gmail


def _header(message: dict, name: str) -> str:
    for h in message.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def message_text(payload: dict) -> str:
    """The readable body of a message: plain text if there is any, else the
    HTML version with its markup removed."""
    plain, rich = [], []

    def walk(part: dict) -> None:
        mime, data = part.get("mimeType", ""), part.get("body", {}).get("data")
        if part.get("filename"):
            return  # an attachment
        if data and mime == "text/plain":
            plain.append(_decode(data))
        elif data and mime == "text/html":
            rich.append(_decode(data))
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    if plain:
        return "\n".join(plain).strip()
    return page_text("\n".join(rich))[1] if rich else ""


def _attachments(payload: dict) -> list[str]:
    names = []

    def walk(part: dict) -> None:
        if part.get("filename"):
            names.append(part["filename"])
        for child in part.get("parts", []) or []:
            walk(child)

    walk(payload)
    return names


@tool(
    name="gmail_search",
    description=(
        "Search the user's Gmail and list matching messages (newest first) with sender, subject, date and a "
        "snippet. Uses Gmail's search syntax, e.g. 'is:unread', 'from:anna', 'subject:invoice newer_than:7d'. "
        "An empty query lists the latest mail in the inbox."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query. Default: 'in:inbox'."},
            "count": {"type": "integer", "minimum": 1, "maximum": 25, "description": "How many. Default 10."},
        },
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Search Gmail for: {a.get('query') or 'in:inbox'}",
)
@_guard
def gmail_search(args: dict, ctx: ToolContext) -> ToolResult:
    query = args.get("query") or "in:inbox"
    listing = oauth.call(GOOGLE, "GET", f"{GMAIL}/messages", {"q": query, "maxResults": args.get("count", 10)}) or {}
    rows = []
    for item in listing.get("messages", []):
        ctx.kill.check()
        m = oauth.call(
            GOOGLE, "GET", f"{GMAIL}/messages/{item['id']}",
            {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
        )
        unread = " (unread)" if "UNREAD" in m.get("labelIds", []) else ""
        rows.append(
            f"id {m['id']}{unread}\n  From: {_header(m, 'From')}\n  Subject: {_header(m, 'Subject')}\n"
            f"  Date: {_header(m, 'Date')}\n  {m.get('snippet', '')}"
        )
    if not rows:
        return ToolResult(f"No messages match {query!r}.")
    return ToolResult("\n".join(rows), untrusted_source=f"Gmail search: {query}", taints=True)


@tool(
    name="gmail_read",
    description="Read one email in full, by the id shown in gmail_search.",
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Read email {a['id']}",
)
@_guard
def gmail_read(args: dict, ctx: ToolContext) -> ToolResult:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args["id"]):
        return ToolResult("That is not a message id.", is_error=True)
    m = oauth.call(GOOGLE, "GET", f"{GMAIL}/messages/{args['id']}", {"format": "full"})
    body = message_text(m.get("payload", {})) or "(no readable text)"
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY] + f"\n[... {len(body) - MAX_BODY} more characters not shown]"
    files = _attachments(m.get("payload", {}))
    text = (
        f"From: {_header(m, 'From')}\nTo: {_header(m, 'To')}\nDate: {_header(m, 'Date')}\n"
        f"Subject: {_header(m, 'Subject')}\n"
        + (f"Attachments: {', '.join(files)}\n" if files else "")
        + f"\n{body}"
    )
    return ToolResult(text, untrusted_source=f"email from {_header(m, 'From')}", taints=True)


def _addresses(value: str) -> list[str]:
    return [a.strip() for a in re.split(r"[;,]", value or "") if a.strip()]


def _build_email(args: dict) -> tuple[dict, str]:
    """Returns (the request body for Gmail, a readable preview)."""
    to, cc = _addresses(args.get("to", "")), _addresses(args.get("cc", ""))
    subject, body = args.get("subject", ""), args["body"]
    request: dict = {}
    extra_headers = {}
    if args.get("reply_to_id"):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", args["reply_to_id"]):
            raise ValueError("reply_to_id is not a message id.")
        original = oauth.call(
            GOOGLE, "GET", f"{GMAIL}/messages/{args['reply_to_id']}",
            {"format": "metadata", "metadataHeaders": ["From", "Reply-To", "Subject", "Message-ID", "References"]},
        )
        if not to:
            to = [_header(original, "Reply-To") or _header(original, "From")]
        if not subject:
            old = _header(original, "Subject")
            subject = old if old.lower().startswith("re:") else f"Re: {old}"
        message_id = _header(original, "Message-ID")
        if message_id:
            extra_headers = {"In-Reply-To": message_id, "References": f"{_header(original, 'References')} {message_id}".strip()}
        request["threadId"] = original.get("threadId")
    if not to:
        raise ValueError("Who is it to?")
    for address in to + cc:
        if "@" not in parseaddr(address)[1]:
            raise ValueError(f"{address!r} is not an email address.")
    if any("\n" in v or "\r" in v for v in [subject, *to, *cc]):
        raise ValueError("Addresses and the subject must each be a single line.")

    email = EmailMessage()
    email["To"] = ", ".join(to)
    if cc:
        email["Cc"] = ", ".join(cc)
    email["Subject"] = subject
    for name, value in extra_headers.items():
        email[name] = value
    email.set_content(body)
    request["raw"] = base64.urlsafe_b64encode(email.as_bytes()).decode()
    preview = f"To: {', '.join(to)}\n" + (f"Cc: {', '.join(cc)}\n" if cc else "") + f"Subject: {subject}\n\n{body}"
    return request, preview


_EMAIL_FIELDS = {
    "to": {"type": "string", "description": "Recipient address(es), comma-separated. Optional when replying."},
    "cc": {"type": "string", "description": "Cc address(es), comma-separated."},
    "subject": {"type": "string"},
    "body": {"type": "string", "description": "The message, as plain text."},
    "reply_to_id": {"type": "string", "description": "Id of an email (from gmail_search) to reply to, in its thread."},
}


def _describe_email(action: str):
    def describe(args: dict, ctx: ToolContext) -> str:
        try:
            return f"{action}:\n\n{_build_email(args)[1]}"
        except (ValueError, NotConnected, ApiError, SecretsUnavailable) as exc:
            return f"{action} (cannot be prepared: {exc})"

    return describe


@tool(
    name="gmail_send",
    description=(
        "Send an email from the user's Gmail. The user is shown the complete message and must approve before it "
        "goes. To reply within a thread, pass reply_to_id."
    ),
    input_schema={"type": "object", "properties": _EMAIL_FIELDS, "required": ["body"], "additionalProperties": False},
    tier=CONFIRM,
    kind="send",
    describe=_describe_email("Send this email"),
)
@_guard
def gmail_send(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        request, preview = _build_email(args)
    except ValueError as exc:
        return ToolResult(str(exc), is_error=True)
    sent = oauth.call(GOOGLE, "POST", f"{GMAIL}/messages/send", body=request)
    return ToolResult(f"Sent (id {sent.get('id')}).\n{preview.splitlines()[0]}")


@tool(
    name="gmail_draft",
    description="Save an email as a draft in the user's Gmail without sending it, for them to review and send.",
    input_schema={"type": "object", "properties": _EMAIL_FIELDS, "required": ["body"], "additionalProperties": False},
    tier=AUTO,
    kind="write",
    describe=_describe_email("Save this email as a draft"),
)
@_guard
def gmail_draft(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        request, preview = _build_email(args)
    except ValueError as exc:
        return ToolResult(str(exc), is_error=True)
    oauth.call(GOOGLE, "POST", f"{GMAIL}/drafts", body={"message": request})
    return ToolResult(f"Saved to Drafts.\n{preview.splitlines()[0]}")


# --------------------------------------------------------------- Calendar


def parse_when(value: str) -> datetime:
    """'2026-11-13T15:00' -> a datetime in the computer's own time zone."""
    moment = datetime.fromisoformat(value.strip())
    return moment if moment.tzinfo else moment.astimezone()


def _event_line(event: dict) -> str:
    start, end = event.get("start", {}), event.get("end", {})
    if "date" in start:
        when = f"{start['date']} (all day)"
    else:
        s = datetime.fromisoformat(start["dateTime"])
        e = datetime.fromisoformat(end["dateTime"]) if end.get("dateTime") else None
        when = s.strftime("%a %d %b %H:%M") + (e.strftime("-%H:%M") if e else "")
    line = f"{when}  {event.get('summary', '(no title)')}"
    if event.get("location"):
        line += f"  @ {event['location']}"
    return f"{line}  [id {event.get('id')}]"


@tool(
    name="calendar_events",
    description=(
        "List events on the user's Google Calendar between two times. Defaults to the next 7 days. "
        "Times are ISO format in the user's local time, e.g. 2026-11-13T09:00."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "start": {"type": "string", "description": "From when. Default: now."},
            "end": {"type": "string", "description": "Until when. Default: 7 days after start."},
            "query": {"type": "string", "description": "Only events containing this text."},
        },
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: "Look at the calendar",
)
@_guard
def calendar_events(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        start = parse_when(args["start"]) if args.get("start") else datetime.now().astimezone()
        end = parse_when(args["end"]) if args.get("end") else start + timedelta(days=7)
    except ValueError:
        return ToolResult("Times must look like 2026-11-13T09:00.", is_error=True)
    data = oauth.call(
        GOOGLE, "GET", f"{CALENDAR}/events",
        {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
         "orderBy": "startTime", "maxResults": 50, "q": args.get("query")},
    ) or {}
    events = data.get("items", [])
    if not events:
        return ToolResult("Nothing is scheduled in that period.")
    # Event titles can be written by other people (invitations), so this is data.
    return ToolResult("\n".join(_event_line(e) for e in events), untrusted_source="Google Calendar", taints=True)


def _event_body(args: dict) -> dict:
    start = parse_when(args["start"])
    end = parse_when(args["end"]) if args.get("end") else start + timedelta(hours=1)
    if end <= start:
        raise ValueError("The event must end after it starts.")
    body = {
        "summary": args["title"],
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
    }
    for source, target in (("location", "location"), ("notes", "description")):
        if args.get(source):
            body[target] = args[source]
    guests = _addresses(args.get("guests", ""))
    for guest in guests:
        if "@" not in guest:
            raise ValueError(f"{guest!r} is not an email address.")
    if guests:
        body["attendees"] = [{"email": g} for g in guests]
    return body


def _describe_event(args: dict, ctx: ToolContext) -> str:
    try:
        body = _event_body(args)
    except (ValueError, KeyError) as exc:
        return f"Add a calendar event (cannot be prepared: {exc})"
    start, end = datetime.fromisoformat(body["start"]["dateTime"]), datetime.fromisoformat(body["end"]["dateTime"])
    text = f"Add to the calendar: {body['summary']}\n  {start.strftime('%A %d %B %Y, %H:%M')} to {end.strftime('%H:%M')}"
    if body.get("location"):
        text += f"\n  Where: {body['location']}"
    if body.get("attendees"):
        text += "\n  INVITATIONS WILL BE EMAILED TO: " + ", ".join(a["email"] for a in body["attendees"])
    return text


@tool(
    name="calendar_create",
    description=(
        "Add an event to the user's Google Calendar. Times are ISO format in the user's local time, e.g. "
        "2026-11-13T15:00. If 'guests' is given, Google emails them invitations, and the user is asked to approve first."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start": {"type": "string"},
            "end": {"type": "string", "description": "Default: one hour after start."},
            "location": {"type": "string"},
            "notes": {"type": "string"},
            "guests": {"type": "string", "description": "Email addresses to invite, comma-separated."},
        },
        "required": ["title", "start"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="write",
    # Inviting people sends email on the user's behalf, so it always asks.
    escalate=lambda a, c: (CONFIRM, "it emails invitations to other people", "strict") if a.get("guests") else None,
    describe=_describe_event,
)
@_guard
def calendar_create(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        body = _event_body(args)
    except ValueError as exc:
        return ToolResult(str(exc), is_error=True)
    params = {"sendUpdates": "all"} if body.get("attendees") else None
    event = oauth.call(GOOGLE, "POST", f"{CALENDAR}/events", params, body)
    return ToolResult(f"Added: {_event_line(event)}")


@tool(
    name="calendar_delete",
    description="Delete an event from the user's Google Calendar, by the id shown in calendar_events.",
    input_schema={
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
        "additionalProperties": False,
    },
    tier=CONFIRM,
    kind="delete",
    describe=lambda a, c: f"Delete the calendar event with id {a['id']}",
)
@_guard
def calendar_delete(args: dict, ctx: ToolContext) -> ToolResult:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args["id"]):
        return ToolResult("That is not an event id.", is_error=True)
    oauth.call(GOOGLE, "DELETE", f"{CALENDAR}/events/{args['id']}")
    return ToolResult("Event deleted.")
