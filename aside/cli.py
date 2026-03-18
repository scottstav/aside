"""CLI entry point — argparse-based interface to the aside daemon."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from aside.config import load_config, load_excluded_models, resolve_archive_dir, resolve_conversations_dir, resolve_excluded_models_path, resolve_socket_path, resolve_state_dir


# ---------------------------------------------------------------------------
# Socket helper
# ---------------------------------------------------------------------------


def _send_overlay(msg: dict) -> None:
    """Connect to the overlay socket, send a JSON message, and close.

    Prints an error and exits with code 1 if the overlay is not running.
    """
    sock_path = resolve_socket_path("aside-overlay.sock")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(sock_path))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        print("Error: aside overlay is not running", file=sys.stderr)
        sys.exit(1)

    try:
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
    finally:
        sock.close()


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
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)
    finally:
        sock.close()


def _send_recv(msg: dict) -> dict:
    """Send JSON to the daemon and return the JSON response.

    Like _send, but waits for a response before closing.
    """
    sock_path = resolve_socket_path("aside.sock")

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(str(sock_path))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        print("Error: aside daemon is not running", file=sys.stderr)
        sys.exit(1)

    try:
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
        sock.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data)

        return json.loads(b"".join(chunks).decode("utf-8"))
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


def _resolve_last_conv(conv_dir) -> str:
    """Return the last conversation ID from last.json, or exit with error.

    Uses the same last.json file the daemon writes after each query,
    mirroring the ``conversation_id: None`` resolution in ``aside query``.
    """
    last_file = conv_dir.parent / "last.json"
    try:
        data = json.loads(last_file.read_text())
        conv_id = data.get("conversation_id")
        if conv_id:
            return conv_id
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    print("Error: no recent conversation found", file=sys.stderr)
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

    # aside toggle-tts
    sub.add_parser("toggle-tts", help="Toggle TTS on/off for next query")

    # aside enable-tts
    sub.add_parser("enable-tts", help="Install piper-tts and voice model (requires sudo)")

    # aside disable-tts
    sub.add_parser("disable-tts", help="Uninstall piper-tts (requires sudo)")

    # aside enable-stt
    sub.add_parser("enable-stt", help="Install speech-to-text packages (requires sudo)")

    # aside disable-stt
    sub.add_parser("disable-stt", help="Uninstall speech-to-text packages (requires sudo)")

    # aside status
    sub.add_parser("status", help="Print daemon status as JSON")

    # aside daemon
    sub.add_parser("daemon", help="Start the aside daemon (foreground)")

    # aside show [CONVERSATION_ID]
    show = sub.add_parser("show", help="Print a full conversation transcript")
    show.add_argument("conversation_id", nargs="?", default=None, help="Conversation ID (default: most recent)")

    # aside open [CONVERSATION_ID]
    open_cmd = sub.add_parser("open", help="Export conversation to markdown and open it")
    open_cmd.add_argument("conversation_id", nargs="?", default=None, help="Conversation ID (default: most recent)")

    # aside rm CONVERSATION_ID
    rm_cmd = sub.add_parser("rm", help="Delete a conversation")
    rm_cmd.add_argument("conversation_id", help="Conversation ID to delete")

    # aside input
    sub.add_parser("input", help="Open the conversation picker overlay")

    # aside view [CONVERSATION_ID]
    view_cmd = sub.add_parser("view", help="View a conversation in the overlay")
    view_cmd.add_argument("conversation_id", nargs="?", default=None, help="Conversation ID (default: most recent)")

    # aside reply [CONVERSATION_ID] [TEXT] [--mic]
    reply = sub.add_parser("reply", help="Continue a conversation by ID")
    reply.add_argument("conversation_id", nargs="?", default=None, help="Conversation ID (default: most recent)")
    reply.add_argument("text", nargs="?", default=None, help="Reply text (optional)")
    reply.add_argument("--mic", action="store_true", default=False, help="One-shot voice capture")

    # aside ls [-n LIMIT]
    ls = sub.add_parser("ls", help="List recent conversations")
    ls.add_argument(
        "-n", "--limit",
        type=int,
        default=20,
        help="Maximum number of conversations to list (default: 20)",
    )

    # aside set-key PROVIDER [KEY]
    sk = sub.add_parser("set-key", help="Store an API key in the system keyring")
    sk.add_argument("provider", help="Provider name (anthropic, openai, etc.)")
    sk.add_argument("key", nargs="?", default=None, help="API key (reads stdin if omitted)")

    # aside get-key PROVIDER
    gk = sub.add_parser("get-key", help="Show a stored API key (masked)")
    gk.add_argument("provider", help="Provider name (anthropic, openai, etc.)")

    # aside models
    sub.add_parser("models", help="List available models (filtered by API keys)")

    # aside model set NAME
    # aside model exclude NAME
    model_cmd = sub.add_parser("model", help="Manage the active model")
    model_sub = model_cmd.add_subparsers(dest="model_action")
    model_sub.required = True
    model_set = model_sub.add_parser("set", help="Switch the active model (runtime)")
    model_set.add_argument("name", help="Model name (e.g. gemini/gemini-2.5-pro)")
    model_exclude = model_sub.add_parser("exclude", help="Exclude a model from the picker")
    model_exclude.add_argument("name", help="Model name to exclude (e.g. gemini/gemini-pro)")

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


def _cmd_input(args: argparse.Namespace) -> None:
    """Open the conversation picker overlay."""
    _send_overlay({"cmd": "input"})


def _cmd_view(args: argparse.Namespace) -> None:
    """View a conversation in the overlay."""
    if args.conversation_id:
        cfg = load_config()
        conv_dir = resolve_conversations_dir(cfg)
        full_id = _resolve_conv_id(conv_dir, args.conversation_id)
        _send_overlay({"cmd": "convo", "conversation_id": full_id})
    else:
        # Let the overlay decide — it knows the in-memory conversation
        _send_overlay({"cmd": "convo"})


def _cmd_reply(args: argparse.Namespace) -> None:
    """Continue a conversation by ID."""
    # Validate mutual exclusion
    if args.text and args.mic:
        print("Error: text and --mic are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    # Resolve conversation ID (fall back to most recent)
    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)
    if args.conversation_id:
        full_id = _resolve_conv_id(conv_dir, args.conversation_id)
    else:
        full_id = _resolve_last_conv(conv_dir)

    if args.mic:
        _send({"action": "query", "conversation_id": full_id, "mic": True})
    elif args.text:
        _send({"action": "query", "text": args.text, "conversation_id": full_id})
    else:
        _send_overlay({"cmd": "convo", "conversation_id": full_id})


def _cmd_cancel(args: argparse.Namespace) -> None:
    """Cancel the running query."""
    _send({"action": "cancel"})


def _cmd_stop_tts(args: argparse.Namespace) -> None:
    """Stop TTS playback."""
    _send({"action": "stop_tts"})


def _cmd_toggle_tts(args: argparse.Namespace) -> None:
    """Toggle TTS on/off for next query."""
    _send({"action": "toggle_tts"})


_VOICE_MODEL_DIR = Path("/usr/share/piper-voices/en/en_US/lessac/medium")
_VOICE_MODEL_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium"
_VOICE_MODEL_FILES = ("en_US-lessac-medium.onnx", "en_US-lessac-medium.onnx.json")
_PIP_CMD = [sys.executable, "-m", "pip"]


def _check_venv_writable() -> None:
    """Exit with a helpful message if the venv isn't writable."""
    venv_dir = Path(sys.executable).resolve().parents[1]
    if not os.access(venv_dir, os.W_OK):
        print(f"Error: {venv_dir} is not writable. Re-run with sudo.", file=sys.stderr)
        sys.exit(1)


def _cmd_enable_tts(args: argparse.Namespace) -> None:
    """Install piper-tts into the aside venv and download voice model."""
    _check_venv_writable()

    # Install piper-tts + sounddevice (playback)
    print("Installing piper-tts...")
    ret = subprocess.run([*_PIP_CMD, "install", "piper-tts", "sounddevice"], check=False)
    if ret.returncode != 0:
        print("Error: pip install piper-tts failed", file=sys.stderr)
        sys.exit(1)

    # Download voice model
    _VOICE_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    for filename in _VOICE_MODEL_FILES:
        dest = _VOICE_MODEL_DIR / filename
        if dest.exists():
            print(f"  {filename} already exists, skipping")
            continue
        url = f"{_VOICE_MODEL_BASE_URL}/{filename}"
        print(f"  Downloading {filename}...")
        ret = subprocess.run(
            ["curl", "-fSL", "-o", str(dest), url],
            check=False,
        )
        if ret.returncode != 0:
            print(f"Error: failed to download {filename}", file=sys.stderr)
            sys.exit(1)

    print("TTS enabled. Restart the daemon: systemctl --user restart aside-daemon")


def _cmd_disable_tts(args: argparse.Namespace) -> None:
    """Uninstall piper-tts from the aside venv."""
    _check_venv_writable()

    print("Uninstalling piper-tts...")
    subprocess.run([*_PIP_CMD, "uninstall", "-y", "piper-tts", "sounddevice"], check=False)
    print("TTS disabled. Restart the daemon: systemctl --user restart aside-daemon")


_STT_PIP_PACKAGES = ["faster-whisper", "webrtcvad-wheels"]


def _cmd_enable_stt(args: argparse.Namespace) -> None:
    """Install STT packages into the aside venv."""
    _check_venv_writable()

    # Check for numpy — it's needed by faster-whisper but best installed via
    # the system package manager so it can use optimised BLAS libraries.
    try:
        import numpy as _  # noqa: F401
    except ImportError:
        print("Error: numpy is required but not installed.", file=sys.stderr)
        print("Install it with your system package manager:", file=sys.stderr)
        print("  Arch:   sudo pacman -S python-numpy", file=sys.stderr)
        print("  Fedora: sudo dnf install python3-numpy", file=sys.stderr)
        print("  Ubuntu: sudo apt install python3-numpy", file=sys.stderr)
        sys.exit(1)

    print("Installing STT packages...")
    ret = subprocess.run([*_PIP_CMD, "install", *_STT_PIP_PACKAGES], check=False)
    if ret.returncode != 0:
        print("Error: pip install failed", file=sys.stderr)
        sys.exit(1)

    print("STT enabled. Restart the daemon: systemctl --user restart aside-daemon")


def _cmd_disable_stt(args: argparse.Namespace) -> None:
    """Uninstall STT packages from the aside venv."""
    _check_venv_writable()

    print("Uninstalling STT packages...")
    subprocess.run([*_PIP_CMD, "uninstall", "-y", "faster-whisper", "webrtcvad-wheels"], check=False)
    print("STT disabled. Restart the daemon: systemctl --user restart aside-daemon")


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

    if args.conversation_id:
        full_id = _resolve_conv_id(conv_dir, args.conversation_id)
    else:
        full_id = _resolve_last_conv(conv_dir)
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
    from aside.state import ConversationStore

    cfg = load_config()
    conv_dir = resolve_conversations_dir(cfg)
    archive_dir = resolve_archive_dir(cfg)

    if args.conversation_id:
        full_id = _resolve_conv_id(conv_dir, args.conversation_id)
    else:
        full_id = _resolve_last_conv(conv_dir)

    store = ConversationStore(conv_dir, archive_dir=archive_dir)
    conv = store.get_or_create(full_id)
    store.write_transcript(conv)

    md_path = str(store.transcript_path(full_id))

    if shutil.which("xdg-open"):
        subprocess.Popen(["xdg-open", md_path])
    else:
        print(open(md_path).read())
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


def _cmd_set_key(args: argparse.Namespace) -> None:
    """Store an API key in the system keyring."""
    import aside.keyring

    key = args.key
    if key is None:
        key = sys.stdin.read().strip()
    if not key:
        print("Error: no key provided", file=sys.stderr)
        sys.exit(1)

    backend = aside.keyring.set_key(args.provider, key)
    print(f"Stored {args.provider} key in {backend}")


def _cmd_get_key(args: argparse.Namespace) -> None:
    """Show a stored API key (masked)."""
    import os
    import aside.keyring

    # Check env first, then keyring
    env_var = aside.keyring._PROVIDER_TO_ENV.get(
        args.provider, f"{args.provider.upper()}_API_KEY"
    )
    key = os.environ.get(env_var) or aside.keyring.get_key(args.provider)

    if key:
        # Mask: show first 4 and last 4 chars
        if len(key) > 10:
            masked = key[:4] + "..." + key[-4:]
        else:
            masked = key[:2] + "..." + key[-2:]
        print(f"{args.provider}: {masked}")
    else:
        print(f"{args.provider}: not found")


def _cmd_models(args: argparse.Namespace) -> None:
    """List available models grouped by provider."""
    import aside.models

    exclude = load_excluded_models()
    models = aside.models.available_models(exclude=exclude)
    if not models:
        print("No models available (no API keys found)")
        return

    # Try to get current model from daemon
    try:
        resp = _send_recv({"action": "get_model"})
        current = resp.get("model", "")
    except SystemExit:
        # Daemon not running, read from config
        cfg = load_config()
        current = cfg.get("model", {}).get("name", "")

    for provider in sorted(models):
        print(provider)
        for name in models[provider]:
            marker = "*" if name == current else " "
            print(f"  {marker} {name}")
        print()


def _cmd_model_exclude(name: str) -> None:
    """Add a model to the excluded-models file."""
    exclude_path = resolve_excluded_models_path()
    existing = load_excluded_models()
    if name in existing:
        print(f"{name} is already excluded")
        return

    exclude_path.parent.mkdir(parents=True, exist_ok=True)
    with open(exclude_path, "a") as fh:
        fh.write(name + "\n")
    print(f"Excluded {name}")


def _cmd_model(args: argparse.Namespace) -> None:
    """Model subcommand dispatcher."""
    if args.model_action == "set":
        _send({"action": "set_model", "model": args.name})
        print(f"Model set to {args.name}")
    elif args.model_action == "exclude":
        _cmd_model_exclude(args.name)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_HANDLERS = {
    "query": _cmd_query,
    "input": _cmd_input,
    "view": _cmd_view,
    "reply": _cmd_reply,
    "cancel": _cmd_cancel,
    "stop-tts": _cmd_stop_tts,
    "toggle-tts": _cmd_toggle_tts,
    "enable-tts": _cmd_enable_tts,
    "disable-tts": _cmd_disable_tts,
    "enable-stt": _cmd_enable_stt,
    "disable-stt": _cmd_disable_stt,
    "status": _cmd_status,
    "ls": _cmd_ls,
    "show": _cmd_show,
    "open": _cmd_open,
    "rm": _cmd_rm,
    "daemon": _cmd_daemon,
    "set-key": _cmd_set_key,
    "get-key": _cmd_get_key,
    "models": _cmd_models,
    "model": _cmd_model,
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
