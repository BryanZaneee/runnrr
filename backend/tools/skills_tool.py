"""The `read_skill` tool — tier 2 of progressive disclosure.

The catalog in the system prompt gives the model one line per skill; this is how
it pulls the full procedure for the one it actually needs. The body comes back
as a tool result, which keeps it out of the cached prompt prefix. See
backend/skills.py for why that matters.
"""
from __future__ import annotations

from typing import Any

from backend.skills import SkillError, read_skill_body
from backend.tools.definitions import ToolContext, ToolDef


def _handler(args: dict[str, Any], ctx: ToolContext) -> Any:
    skills_root = getattr(ctx.profile, "skills_root", None) if ctx.profile else None
    try:
        return read_skill_body(args["skill_id"], skills_root)
    except SkillError as exc:
        # ToolExecutionError is what dispatch turns into is_error=True with the
        # message intact, so a wrong id becomes something the model can retry on
        # rather than an opaque failure.
        from backend.tool_errors import ToolExecutionError

        raise ToolExecutionError(str(exc)) from exc


def _metadata(args: dict[str, Any], output: Any, ctx: ToolContext) -> dict[str, Any]:
    name = (output or {}).get("name") if isinstance(output, dict) else None
    label = name or args.get("skill_id", "skill")
    return {
        "source_summary": f"followed the '{label}' procedure",
        "source_items": [],
        "source_count": 0,
        "hidden_count": 0,
    }


READ_SKILL_TOOL = ToolDef(
    name="read_skill",
    description=(
        "Get the full step-by-step instructions for one of the skills listed in "
        "the <skills> section of your system prompt. Call this before carrying "
        "out a task that matches a skill's description, then follow the steps it "
        "returns. Pass the skill id exactly as it appears in the list."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "skill_id": {
                "type": "string",
                "description": "The skill id from the <skills> list, e.g. 'refund-request'.",
            }
        },
        "required": ["skill_id"],
    },
    handler=_handler,
    source_metadata=_metadata,
)
