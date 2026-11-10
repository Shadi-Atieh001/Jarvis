"""The permission gate. Every tool call passes through decide() before it runs.

This is enforced here in code, not by asking the model to behave. The model
can request anything; only calls that pass the gate are executed.

Tiers:
  auto     run without asking
  confirm  show the user exactly what will happen and wait for "yes"
  blocked  never run

How the tier for one call is worked out:
  1. Start from settings.toml ([permissions.tools]), else the tool's own
     default, else [permissions] default.
  2. The tool's escalate() hook may raise it (e.g. overwriting a file).
  3. If untrusted content was read earlier in this request, anything that
     is not read-only is raised to confirm.
  4. If the command/code matches a blocked pattern, it is blocked.
A step can only make the result stricter, never looser.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from .config import Settings
from .tools import AUTO, BLOCKED, CONFIRM, TIER_ORDER, Tool, ToolContext


@dataclass
class Decision:
    tier: str
    reason: str  # why this tier, shown to the user and logged
    description: str  # exactly what will happen


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

        configured = self.settings.tool_tiers.get(tool.name)
        tier = configured or tool.tier or self.settings.default_tier
        if configured:
            reason = f'{tool.name} is set to "{tier}" in settings.toml'
        else:
            reason = f'{tool.name} is "{tier}" by default'
        if tier not in TIER_ORDER:
            # A typo in settings.toml must fail safe, not open.
            tier, reason = CONFIRM, f"settings.toml has an unknown tier {tier!r}"

        if tool.escalate is not None:
            try:
                raised = tool.escalate(args, ctx)
                why = "this particular call is riskier than usual"
                if isinstance(raised, tuple):  # (tier, explanation)
                    raised, why = raised
            except Exception as exc:  # a broken hook must fail safe
                raised, why = CONFIRM, f"could not assess the risk ({exc})"
            if raised in TIER_ORDER and TIER_ORDER[raised] > TIER_ORDER[tier]:
                tier, reason = raised, why

        if (
            self.tainted
            and self.settings.confirm_after_untrusted
            and not tool.read_only
            and tier == AUTO
        ):
            tier, reason = CONFIRM, "untrusted content was read earlier in this request"

        if tool.blockable_text is not None:
            text = tool.blockable_text(args, ctx)
            for pattern in self._blocked:
                if pattern.search(text):
                    tier = BLOCKED
                    reason = f"matches blocked pattern {pattern.pattern!r}"
                    break

        return Decision(tier, reason, description)

    @staticmethod
    def _describe(tool: Tool, args: dict, ctx: ToolContext) -> str:
        if tool.describe is not None:
            try:
                return tool.describe(args, ctx)
            except Exception:
                pass
        return f"{tool.name} with:\n{json.dumps(args, indent=2, ensure_ascii=False)}"
