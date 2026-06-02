"""Deterministic calculator tool."""
from __future__ import annotations

from typing import Any

from backend.tool_errors import ToolExecutionError
from backend.tools.definitions import ToolContext, ToolDef
from backend.tools.source_metadata import static_source_metadata


def calculator(operation: str, values: list[int | float]) -> dict[str, Any]:
    """Run a bounded deterministic calculation."""
    if not isinstance(operation, str) or not operation:
        raise ToolExecutionError("operation must be a non-empty string")
    if not isinstance(values, list):
        raise ToolExecutionError("values must be a list of numbers")
    nums: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ToolExecutionError("values must contain only numbers")
        nums.append(float(value))

    op = operation.strip().lower()
    if op == "sum":
        if not nums:
            raise ToolExecutionError("sum requires at least one value")
        result = sum(nums)
    elif op == "average":
        if not nums:
            raise ToolExecutionError("average requires at least one value")
        result = sum(nums) / len(nums)
    elif op == "difference":
        if len(nums) < 2:
            raise ToolExecutionError("difference requires two values")
        result = nums[1] - nums[0]
    elif op == "ratio":
        if len(nums) < 2:
            raise ToolExecutionError("ratio requires two values")
        if nums[0] == 0:
            raise ToolExecutionError("ratio denominator must not be zero")
        result = nums[1] / nums[0]
    elif op == "percent_change":
        if len(nums) < 2:
            raise ToolExecutionError("percent_change requires two values")
        if nums[0] == 0:
            raise ToolExecutionError("percent_change starting value must not be zero")
        result = ((nums[1] - nums[0]) / nums[0]) * 100
    elif op == "cagr":
        if len(nums) < 3:
            raise ToolExecutionError("cagr requires [start_value, end_value, periods]")
        start, end, periods = nums[:3]
        if start <= 0 or end < 0 or periods <= 0:
            raise ToolExecutionError("cagr requires start > 0, end >= 0, and periods > 0")
        result = ((end / start) ** (1 / periods) - 1) * 100
    else:
        raise ToolExecutionError(f"unsupported operation: {operation}")

    return {
        "operation": op,
        "values": nums,
        "result": result,
    }


def _handle_calculator(arguments: dict[str, Any], ctx: ToolContext) -> Any:
    return calculator(arguments["operation"], arguments["values"])


def _calculator_metadata(
    arguments: dict[str, Any],
    out: Any,
    context: ToolContext | None = None,
) -> dict[str, Any]:
    return static_source_metadata(
        "calculated result",
        label="Calculation",
        kind="calculation",
    )


CALCULATOR_TOOL = ToolDef(
    name="calculator",
    description=(
        "Run deterministic numeric calculations. No arbitrary expression evaluation. "
        "Supported operations: sum, average, difference, ratio, percent_change, and "
        "cagr. Pass values as numbers; difference/ratio/percent_change use the first "
        "two values, and cagr uses [start_value, end_value, periods]."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["sum", "average", "difference", "ratio", "percent_change", "cagr"],
            },
            "values": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Numeric inputs for the selected operation.",
            },
        },
        "required": ["operation", "values"],
    },
    handler=_handle_calculator,
    source_metadata=_calculator_metadata,
)
