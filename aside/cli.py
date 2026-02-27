"""CLI entry point — argparse-based interface to the aside daemon."""

from __future__ import annotations

import argparse
import json
import socket
import sys
from pathlib import Path

from aside.config import load_config, resolve_socket_path, resolve_state_dir


# ---------------------------------------------------------------------------
# Socket helper
# ---------------------------------------------------------------------------


def _send(msg: dict) -> None:
    """Connect to the daemon socket, send a JSON message, and close.

    Prints an error and exits with code 1 if the daemon is not running.
    """
    sock_path = resolve_socket_path("aside.sock")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(sock_path))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        print("Error: aside daemon is not running", file=sys.stderr)
        sys.exit(1)

    try:
        sock.sendall(json.dumps(msg).encode("utf-8"))
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="aside",
        description="Wayland-native LLM desktop assistant",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    # aside query "text" [-c CONV_ID] [--new]
    q = sub.add_parser("query", help="Send a query to the daemon")
    q.add_argument("text", help="Query text")
    q.add_argument(
        "-c", "--conversation-id",
        dest="conversation_id",
        default=None,
        help="Continue a specific conversation",
    )
    q.add_argument(
        "--new",
        action="store_true",
        default=False,
        help="Force a new conversation",
    )

    # aside cancel
    sub.add_parser("cancel", help="Cancel the running query")

    # aside stop-tts
    sub.add_parser("stop-tts", help="Stop TTS playback")

    # aside status
    sub.add_parser("status", help="Print daemon status as JSON")

    # aside daemon
    sub.add_parser("daemon", help="Start the aside daemon (foreground)")

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_query(args: argparse.Namespace) -> None:
    """Send a query to the daemon."""
    msg: dict = {"action": "query", "text": args.text}

    if args.new:
        msg["conversation_id"] = "__new__"
    elif args.conversation_id:
        msg["conversation_id"] = args.conversation_id
    else:
        msg["conversation_id"] = None

    _send(msg)


def _cmd_cancel(args: argparse.Namespace) -> None:
    """Cancel the running query."""
    _send({"action": "cancel"})


def _cmd_stop_tts(args: argparse.Namespace) -> None:
    """Stop TTS playback."""
    _send({"action": "stop_tts"})


def _cmd_status(args: argparse.Namespace) -> None:
    """Read and print status.json directly (no daemon needed)."""
    cfg = load_config()
    state_dir = resolve_state_dir(cfg)
    status_file = state_dir / "status.json"

    if not status_file.exists():
        print("Error: status file not found (daemon not running?)", file=sys.stderr)
        sys.exit(1)

    data = json.loads(status_file.read_text())
    print(json.dumps(data, indent=2))


def _cmd_daemon(args: argparse.Namespace) -> None:
    """Start the aside daemon in the foreground."""
    from aside.daemon import main as daemon_main

    daemon_main()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_HANDLERS = {
    "query": _cmd_query,
    "cancel": _cmd_cancel,
    "stop-tts": _cmd_stop_tts,
    "status": _cmd_status,
    "daemon": _cmd_daemon,
}


def main() -> None:
    """CLI entry point registered as ``aside`` in pyproject.toml."""
    parser = _build_parser()
    args = parser.parse_args()
    handler = _HANDLERS.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
