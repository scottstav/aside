"""CLI entry point — argparse-based interface to the aside daemon."""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

from aside.config import load_config, resolve_conversations_dir, resolve_socket_path, resolve_state_dir


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
        sock.shutdown(socket.SHUT_WR)
    finally:
        sock.close()


def _resolve_conv_id(conv_dir, prefix: str) -> str:
    """Resolve a conversation ID prefix to the full ID.

    Accepts full UUIDs or short prefixes (e.g. 7-char from ``ls``).
    Exits with an error if the prefix is ambiguous or not found.
    """
    exact = conv_dir / f"{prefix}.json"
    if exact.exists():
        return prefix

    matches = [p.stem for p in conv_dir.glob(f"{prefix}*.json")]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Error: ambiguous prefix '{prefix}' matches {len(matches)} conversations", file=sys.stderr)
        sys.exit(1)
    print(f"Error: conversation {prefix} not found", file=sys.stderr)
    sys.exit(1)


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

    # aside query [TEXT] [-c CONV_ID] [--new] [--mic]
    q = sub.add_parser("query", help="Send a query to the daemon")
    q.add_argument("text", nargs="?", default=None, help="Query text")
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
    q.add_argument(
        "--mic",
        action="store_true",
        default=False,
        help="One-shot voice capture",
    )

    # aside cancel
    sub.add_parser("cancel", help="Cancel the running query")

    # aside stop-tts
    sub.add_parser("stop-tts", help="Stop TTS playback")

    # aside status
    sub.add_parser("status", help="Print daemon status as JSON")

    # aside daemon
    sub.add_parser("daemon", help="Start the aside daemon (foreground)")

    # aside show CONVERSATION_ID
    show = sub.add_parser("show", help="Print a full conversation transcript")
    show.add_argument("conversation_id", help="Conversation ID to display")

    # aside open CONVERSATION_ID
    open_cmd = sub.add_parser("open", help="Export conversation to markdown and open it")
    open_cmd.add_argument("conversation_id", help="Conversation ID to export and open")

    # aside rm CONVERSATION_ID
    rm_cmd = sub.add_parser("rm", help="Delete a conversation")
    rm_cmd.add_argument("conversation_id", help="Conversation ID to delete")

    # aside reply CONVERSATION_ID [TEXT] [--gui] [--mic]
    reply = sub.add_parser("reply", help="Continue a conversation by ID")
    reply.add_argument("conversation_id", help="Conversation ID to continue")
    reply.add_argument("text", nargs="?", default=None, help="Reply text (optional)")
    reply.add_argument("--gui", action="store_true", default=False, help="Open GTK input popup")
    reply.add_argument("--mic", action="store_true", default=False, help="One-shot voice capture")

    # aside ls [-n LIMIT]
    ls = sub.add_parser("ls", help="List recent conversations")
    ls.add_argument(
        "-n", "--limit",
        type=int,
        default=20,
        help="Maximum number of conversations to list (default: 20)",
    )

    return parser


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_query(args: argparse.Namespace) -> None:
    """Send a query to the daemon."""
    # Validate mutual exclusion
    if args.text and args.mic:
        print("Error: text and --mic are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if not args.text and not args.mic:
        print("Error: must provide either text or --mic", file=sys.stderr)
        sys.exit(1)

    if args.mic:
        msg: dict = {"action": "query", "mic": True}
    else:
        msg = {"action": "query", "text": args.text}

    if args.new:
        msg["conversation_id"] = "__new__"
    elif args.conversation_id:
        msg["conversation_id"] = args.conversation_id
    else:
        msg["conversation_id"] = None

    _send(msg)


def _cmd_reply(args: argparse.Namespace) -> None:
    """Continue a conversation by ID."""
    # Validate mutual exclusion
    if args.text and args.mic:
        print("Error: text and --mic are mutually exclusive", file=sys.stderr)
        sys.exit(1)
    if args.gui and args.mic:
        print("Error: --gui and --mic are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    # Resolve prefix to full conversation ID
    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)
    full_id = _resolve_conv_id(conv_dir, args.conversation_id)

    if args.gui:
        subprocess.Popen(["aside-input", "-c", full_id])
    elif args.mic:
        _send({"action": "query", "conversation_id": full_id, "mic": True})
    elif args.text:
        _send({"action": "query", "text": args.text, "conversation_id": full_id})
    else:
        text = input(">>> ")
        _send({"action": "query", "text": text, "conversation_id": full_id})


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


def _relative_age(iso_str: str) -> str:
    """Convert an ISO 8601 timestamp to a short relative-age string."""
    try:
        created = datetime.fromisoformat(iso_str)
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - created
        seconds = int(delta.total_seconds())
    except (ValueError, TypeError):
        return "?"

    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 30:
        return f"{days}d"
    months = days // 30
    if months < 12:
        return f"{months}mo"
    years = days // 365
    return f"{years}y"


def _extract_user_preview(content) -> str:
    """Extract a text preview from user message content.

    Content can be a plain string or a list of content parts (multimodal).
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        return " ".join(parts)
    return ""


def _cmd_ls(args: argparse.Namespace) -> None:
    """List recent conversations."""
    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)

    if not conv_dir.is_dir():
        return

    from aside.state import ConversationStore

    store = ConversationStore(conv_dir)
    entries = store.list_recent(limit=args.limit)

    for conv_id, created, preview in entries:
        short_id = conv_id[:7]
        age = _relative_age(created)

        # list_recent already extracts str content but not multimodal;
        # re-extract if preview is empty (multimodal case)
        if not preview:
            path = conv_dir / f"{conv_id}.json"
            try:
                with open(path) as f:
                    conv = json.load(f)
                for msg in conv.get("messages", []):
                    if msg.get("role") == "user":
                        preview = _extract_user_preview(msg.get("content", ""))
                        break
            except (json.JSONDecodeError, OSError):
                pass

        # Truncate to 60 chars
        if len(preview) > 60:
            preview = preview[:60] + "..."

        print(f"{short_id}  {age:>8}  {preview}")


def _cmd_show(args: argparse.Namespace) -> None:
    """Print a full conversation transcript to stdout."""
    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)

    full_id = _resolve_conv_id(conv_dir, args.conversation_id)
    conv_path = conv_dir / f"{full_id}.json"

    with open(conv_path) as f:
        conv = json.load(f)

    # Build a lookup from tool_call id -> function name for resolving
    # tool messages that lack a "name" field.
    tool_call_names: dict[str, str] = {}

    for msg in conv.get("messages", []):
        role = msg.get("role", "")

        if role == "user":
            content = msg.get("content", "")
            text = _extract_user_preview(content)
            print(f"user: {text}")

        elif role == "assistant":
            # Collect tool_call names for later resolution
            for tc in msg.get("tool_calls", []):
                tc_id = tc.get("id", "")
                tc_name = tc.get("function", {}).get("name", "unknown")
                tool_call_names[tc_id] = tc_name
                print(f"assistant: [calling {tc_name}]")

            content = msg.get("content")
            if content:
                print(f"assistant: {content}")

        elif role == "tool":
            name = msg.get("name") or tool_call_names.get(msg.get("tool_call_id", ""), "unknown")
            content = msg.get("content", "")
            print(f"tool({name}): {content}")


def _cmd_open(args: argparse.Namespace) -> None:
    """Export conversation to markdown and open with xdg-open."""
    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)

    full_id = _resolve_conv_id(conv_dir, args.conversation_id)
    conv_path = conv_dir / f"{full_id}.json"

    with open(conv_path) as f:
        conv = json.load(f)

    conv_id = conv.get("id", full_id)
    lines = [f"# Conversation {conv_id[:8]}", ""]

    for msg in conv.get("messages", []):
        role = msg.get("role", "")

        if role == "user":
            lines.append("## User")
            lines.append("")
            content = msg.get("content", "")
            text = _extract_user_preview(content)
            lines.append(text)
            lines.append("")

        elif role == "assistant":
            content = msg.get("content")
            if content:
                lines.append("## Assistant")
                lines.append("")
                lines.append(content)
                lines.append("")

    md_text = "\n".join(lines)

    if shutil.which("xdg-open"):
        md_path = f"/tmp/aside-{conv_id[:8]}.md"
        with open(md_path, "w") as f:
            f.write(md_text)
        subprocess.Popen(["xdg-open", md_path])
    else:
        print(md_text)
        print("\n(xdg-open not found — printed transcript instead)", file=sys.stderr)


def _cmd_rm(args: argparse.Namespace) -> None:
    """Delete a conversation file."""
    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)

    full_id = _resolve_conv_id(conv_dir, args.conversation_id)
    conv_path = conv_dir / f"{full_id}.json"

    conv_path.unlink()
    print(f"Deleted {full_id[:7]}")


def _cmd_daemon(args: argparse.Namespace) -> None:
    """Start the aside daemon in the foreground."""
    from aside.daemon import main as daemon_main

    daemon_main()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_HANDLERS = {
    "query": _cmd_query,
    "reply": _cmd_reply,
    "cancel": _cmd_cancel,
    "stop-tts": _cmd_stop_tts,
    "status": _cmd_status,
    "ls": _cmd_ls,
    "show": _cmd_show,
    "open": _cmd_open,
    "rm": _cmd_rm,
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
