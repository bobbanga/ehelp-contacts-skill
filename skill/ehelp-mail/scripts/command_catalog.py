from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSpec:
    name: str
    chat_entry: bool
    reads_mail: bool
    reads_wps: bool
    may_write: bool
    summary: str


COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec("doctor", False, False, False, False, "readonly diagnostic checklist"),
    CommandSpec("accounts", False, True, False, False, "list discovered accounts"),
    CommandSpec("contacts", False, True, False, False, "readonly contact candidates"),
    CommandSpec("update", False, True, False, True, "preview or update local contact ledger"),
    CommandSpec("annotate", False, False, False, True, "save human contact annotations locally"),
    CommandSpec("report", False, False, False, True, "export local HTML and Excel"),
)


def command_names() -> tuple[str, ...]:
    return tuple(item.name for item in COMMANDS)


def chat_entry_names() -> tuple[str, ...]:
    return tuple(item.name for item in COMMANDS if item.chat_entry)


def command_by_name(name: str) -> CommandSpec:
    for item in COMMANDS:
        if item.name == name:
            return item
    raise KeyError(name)


def agents_capability_phrase() -> str:
    names: list[str] = []
    for item in COMMANDS:
        names.append(f"`{item.name}`")
    return "、".join(names)


def registered_cli_names(parser: argparse.ArgumentParser) -> tuple[str, ...]:
    for action in parser._actions:
        if getattr(action, "dest", "") == "command" and getattr(action, "choices", None):
            return tuple(action.choices)
    raise RuntimeError("cli parser has no command subparsers")
