"""Entry-point script that wraps the bundled native binary.

Registered in pyproject.toml as `[project.scripts] unbrowser = ...`, so
`pip install pyunbrowser` puts a real `unbrowser` command on $PATH that
agents and MCP hosts can use directly (e.g. `command: "unbrowser"` in
.mcp.json).

The wrapper keeps the native binary as the execution engine, but adds a
shell-friendly one-shot `navigate` command and a useful `--help` surface.
All other invocations are passed through to the binary unchanged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from . import find_binary


def _usage() -> None:
    print(
        """unbrowser

Usage:
  unbrowser navigate <url> [--exec-scripts] [--json]
  unbrowser policy-check <url> [<url>...]
  unbrowser [--profile <name>] [--policy=blocklist] [--mcp]

Examples:
  unbrowser navigate https://news.ycombinator.com --json
  unbrowser policy-check https://www.bbc.com/news
  printf '{\"id\":1,\"method\":\"navigate\",\"params\":{\"url\":\"https://news.ycombinator.com\"}}\n' | unbrowser
"""
    )


def _is_help_flag(arg: str) -> bool:
    return arg in {"-h", "--help"}


def _navigate(args: list[str]) -> None:
    if not args or _is_help_flag(args[0]):
        _usage()
        return

    url = args[0]
    exec_scripts = False
    passthrough: list[str] = []
    for arg in args[1:]:
        if arg == "--exec-scripts":
            exec_scripts = True
        elif arg == "--json":
            continue
        else:
            passthrough.append(arg)

    if any(arg == "--mcp" for arg in passthrough):
        raise SystemExit("unbrowser navigate does not support --mcp")

    binary = find_binary()
    proc = subprocess.Popen(
        [binary, *passthrough],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    request = {
        "id": 1,
        "method": "navigate",
        "params": {"url": url, "exec_scripts": exec_scripts},
    }
    proc.stdin.write(json.dumps(request) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        raise SystemExit("unbrowser navigate: binary produced no response")
    response = json.loads(line)
    if "error" in response:
        raise SystemExit(f"unbrowser navigate: {response['error']}")
    result = response.get("result")
    print(json.dumps(result))


def main() -> None:
    argv = sys.argv[1:]
    if not argv or _is_help_flag(argv[0]):
        _usage()
        return

    if argv[0] == "navigate":
        _navigate(argv[1:])
        return

    binary = find_binary()
    # Preserve the native binary behavior for every other command.
    os.execv(binary, ["unbrowser", *argv])


if __name__ == "__main__":
    main()
