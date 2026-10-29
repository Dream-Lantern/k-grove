"""Local schema/authentication-boundary example, not a running MCP server."""
import json
from dataclasses import dataclass
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA = json.loads(Path(__file__).with_name("task_status.schema.json").read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA)


@dataclass(frozen=True)
class Principal:
    # Supplied by the authenticated server session, never by model arguments.
    allowed_task_ids: frozenset[str]


def get_task_status(arguments, principal):
    VALIDATOR.validate(arguments)
    task_id = arguments["task_id"]
    if task_id not in principal.allowed_task_ids:
        raise PermissionError("task access denied")
    # Synthetic data only. No network, database or external side effects.
    return {
        "task_id": task_id,
        "status": "RUNNING",
        "detail": arguments.get("detail", "summary"),
        "log_limit": arguments.get("log_limit", 10),
    }
