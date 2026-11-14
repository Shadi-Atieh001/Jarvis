"""The permission gate. Every tool call passes through decide() before it runs.

This is enforced here in code, not by asking the model to behave. The model
can request anything; only calls that pass the gate are executed.

Tiers:
  auto     run without asking
  confirm  show the user exactly what will happen and wait for "yes"
  blocked  never run

Modes ([permissions] mode in settings.toml):
  careful       each tool follows its own tier; risky calls (overwriting,
                working outside the workspace) ask
  trusted       everything runs without asking except deleting and sending.
                After a web page or outside file has been read, anything
                that changes, runs or controls something asks for the rest
                of that request.
  unrestricted  nothing asks
Blocked patterns, and anything a tool marks as blocked (such as typing a
payment card number), are refused in every mode.

A per-tool entry under [permissions.tools] overrides the mode for that tool.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import Settings
from .tools import AUTO, BLOCKED, CONFIRM, TIER_ORDER, Tool, ToolContext


MODES = ("careful", "trusted", "unrestricted")
# Approving a whole browser would approve every website in it, so browsers
# are never offered; websites are approved one by one through the extension.
BROWSERS = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "iexplore.exe")


def is_browser(app: str) -> bool:
    return app.lower().split("|")[0] in BROWSERS


def app_label(app: str) -> str:
    """'WhatsApp.exe' -> 'WhatsApp'; 'ApplicationFrameHost.exe|Calculator' -> 'Calculator'."""
    name = app.split("|")[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


@dataclass
class Decision:
    tier: str
    reason: str  # why this tier, shown to the user and logged
    description: str  # exactly what will happen
    # Set when the only reason for asking is that a website is not yet
    # approved: the window then offers "Yes, and always on this site".
    offer_site: str | None = None
    # The same for a desktop app: "Yes, and always in this app".
    offer_app: str | None = None


class PermissionGate:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._blocked = [re.compile(p, re.IGNORECASE) for p in settings.blocked_patterns]
        self.tainted = False  # untrusted content seen in the current request

    def new_request(self) -> None:
        self.tainted = False

    def note_untrusted(self) -> None:
        self.tainted = True

    def decide(self, tool: Tool, args: dict, ctx: ToolContext) -> Decision:
        description = self._describe(tool, args, ctx)
        mode = self.settings.permission_mode
        if mode not in MODES or not tool.kind:
            mode = "careful"  # unknown mode, or a tool that has not said what it does

        # 1. The starting tier.
        configured = self.settings.tool_tiers.get(tool.name)
        if configured:
            tier, reason = configured, f'{tool.name} is set to "{configured}" in settings.toml'
        elif mode == "careful":
            tier = tool.tier or self.settings.default_tier
            reason = f'{tool.name} is "{tier}" by default'
        elif mode == "trusted":
            tier = CONFIRM if tool.kind in ("delete", "send") else AUTO
            reason = f'"{tool.kind}" actions {"ask first" if tier == CONFIRM else "run without asking"} in trusted mode'
        else:  # unrestricted
            tier, reason = AUTO, "unrestricted mode"
        if tier not in TIER_ORDER:
            # A typo in settings.toml must fail safe, not open.
            tier, reason = CONFIRM, f"settings.toml has an unknown tier {tier!r}"

        offer_site = None
        # 2. The tool's own view of this particular call.
        if tool.escalate is not None:
            strict = True
            try:
                raised = tool.escalate(args, ctx)
                why = "this particular call is riskier than usual"
                if isinstance(raised, tuple):
                    strict = len(raised) > 2 and raised[2] == "strict"
                    if len(raised) > 3 and isinstance(raised[3], dict):
                        offer_site = raised[3].get("offer_site")
                    raised, why = raised[0], raised[1]
            except Exception as exc:  # a broken hook must fail safe
                raised, why = CONFIRM, f"could not assess the risk ({exc})"
            applies = (
                raised == BLOCKED
                or mode == "careful"
                or (mode == "trusted" and strict)
            )
            if applies and raised in TIER_ORDER and TIER_ORDER[raised] > TIER_ORDER[tier]:
                tier, reason = raised, why
            else:
                offer_site = None

        # 3. Untrusted content read earlier in this request.
        offer_app = None
        if self.tainted and self.settings.confirm_after_untrusted and tier == AUTO and not tool.own_trust_rules:
            if mode == "careful" and not tool.read_only:
                tier, reason = CONFIRM, "untrusted content was read earlier in this request"
            elif mode == "trusted" and tool.kind not in ("read", "launch"):
                # Mouse and keyboard actions name the app they would act on.
                # In an app you have approved, they go ahead.
                app = None
                if tool.target_app is not None:
                    try:
                        app = tool.target_app(args, ctx)
                    except Exception:
                        app = None
                if not (app and app.lower() in {a.lower() for a in self.settings.approved_apps}):
                    tier = CONFIRM
                    if app and not is_browser(app):
                        reason, offer_app = f"{app_label(app)} is not an approved app, and web or outside content was read earlier in this request", app
                    else:
                        reason = "a web page or outside file was read earlier in this request"

        # 4. Blocked patterns, in every mode.
        if tool.blockable_text is not None:
            text = tool.blockable_text(args, ctx)
            for pattern in self._blocked:
                if pattern.search(text):
                    tier = BLOCKED
                    reason = f"matches blocked pattern {pattern.pattern!r}"
                    break

        confirm = tier == CONFIRM
        return Decision(tier, reason, description, offer_site if confirm else None, offer_app if confirm else None)

    @staticmethod
    def _describe(tool: Tool, args: dict, ctx: ToolContext) -> str:
        if tool.describe is not None:
            try:
                return tool.describe(args, ctx)
            except Exception:
                pass
        return f"{tool.name} with:\n{json.dumps(args, indent=2, ensure_ascii=False)}"
