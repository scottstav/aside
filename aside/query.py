"""Query pipeline: send text to an LLM, stream response, run tools, speak.

Uses LiteLLM for model-agnostic API calls (OpenAI, Anthropic, etc.).
All functions are self-contained helpers with no daemon/socket dependencies.
Called by the aside daemon and CLI.
"""

from __future__ import annotations

import json
import logging
import socket
import subprocess
import threading
from datetime import datetime
from pathlib import Path

import litellm

from aside.config import resolve_socket_path
from aside.plugins import run_tool
from aside.sentence_buffer import SentenceBuffer

log = logging.getLogger("aside")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_TOKENS = 4096

# Sentinel for explicit "start a new conversation"
NEW_CONVERSATION = object()


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are an unobtrusive assistant living on a Linux power user's desktop \
(Arch Linux, Hyprland/Wayland, Emacs). You run as a small overlay — not a chatbot, \
not a conversation partner. Think of yourself as a HUD element: answer the question, \
then get out of the way.

Today is {today_long} ({today_iso}, {weekday}).

CONCISENESS IS YOUR #1 PRIORITY. Give the shortest useful answer possible. \
1-2 sentences is the target. No preamble, no hedging, no "Great question!", \
no sign-offs, no unnecessary context. Jump straight to the answer. \
If someone asks "how do I use X in Y?", respond with the direct answer — \
not background, not history, not alternatives they didn't ask about. \
Only give longer responses when the user explicitly asks for detail or elaboration.

You have tools. Use them proactively when they help answer the question.\
"""


def _build_system_prompt(extra: str = "") -> str:
    """Render the system prompt with today's date.

    *extra* is appended verbatim after the template (e.g. user-supplied
    additions from config).
    """
    now = datetime.now()
    text = _SYSTEM_PROMPT_TEMPLATE.format(
        today_long=now.strftime("%d %B %Y"),
        today_iso=now.strftime("%Y-%m-%d"),
        weekday=now.strftime("%A"),
    )
    if extra:
        text += "\n\n" + extra.strip()
    return text


# ---------------------------------------------------------------------------
# Message building (OpenAI / LiteLLM format)
# ---------------------------------------------------------------------------


def _build_messages(
    text: str,
    history: list[dict],
    system_prompt: str,
    image: str | None = None,
    file: str | None = None,
) -> list[dict]:
    """Build an OpenAI-format messages list for LiteLLM.

    Parameters
    ----------
    text:
        The user's current message text.
    history:
        Prior messages in OpenAI format (``[{"role": ..., "content": ...}, ...]``).
    system_prompt:
        Placed as the first ``{"role": "system", ...}`` message.
    image:
        Optional base64-encoded PNG image to attach to the user message.
    file:
        Optional file path string.  Prepended as context to *text*.
    """
    messages: list[dict] = []

    # System message first.
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Prior conversation history.
    messages.extend(history)

    # Current user message.
    if file:
        text = (
            f"[Attached file: {file}]\n"
            "When you produce an output file, copy it to the clipboard "
            "using the clipboard tool's file parameter.\n\n" + text
        )

    if image:
        user_content = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image}",
                },
            },
            {"type": "text", "text": text},
        ]
    else:
        user_content = text  # type: ignore[assignment]

    messages.append({"role": "user", "content": user_content})
    return messages


# ---------------------------------------------------------------------------
# Tool-call accumulation from streaming chunks
# ---------------------------------------------------------------------------


def _getval(obj, key: str, default=""):
    """Get a value from either a dict or an attribute-based object."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _accumulate_tool_calls(
    existing: dict[int, dict],
    delta_tool_calls: list,
) -> None:
    """Merge incremental ``delta.tool_calls`` into *existing*.

    LiteLLM / OpenAI stream tool calls incrementally:
    - The first chunk for an index carries ``function.name``.
    - Subsequent chunks append to ``function.arguments``.

    *existing* is keyed by tool-call index and mutated in place.
    """
    for tc in delta_tool_calls:
        idx = _getval(tc, "index", 0)
        if idx not in existing:
            existing[idx] = {
                "id": _getval(tc, "id", "") or "",
                "name": "",
                "arguments": "",
            }
        entry = existing[idx]

        # Update id if non-empty (may arrive on first chunk).
        tc_id = _getval(tc, "id", "") or ""
        if tc_id:
            entry["id"] = tc_id

        fn = _getval(tc, "function", None)
        if fn is None:
            fn = {}

        fn_name = _getval(fn, "name", "") or ""
        fn_args = _getval(fn, "arguments", "") or ""

        if fn_name:
            entry["name"] = fn_name
        entry["arguments"] += fn_args


def _parse_tool_calls(accumulated: dict[int, dict]) -> list[dict]:
    """Convert accumulated tool-call fragments into finished dicts.

    Each returned dict has ``id``, ``name``, and ``arguments`` (parsed JSON).
    """
    results: list[dict] = []
    for _idx in sorted(accumulated):
        entry = accumulated[_idx]
        try:
            args = json.loads(entry["arguments"]) if entry["arguments"] else {}
        except json.JSONDecodeError:
            log.warning("Failed to parse tool arguments for %s: %s",
                        entry["name"], entry["arguments"][:200])
            args = {}
        results.append({
            "id": entry["id"],
            "name": entry["name"],
            "arguments": args,
        })
    return results


# ---------------------------------------------------------------------------
# Overlay IPC
# ---------------------------------------------------------------------------


def _connect_overlay() -> socket.socket | None:
    """Connect to the aside-overlay Unix socket.  Returns socket or None."""
    sock_path = resolve_socket_path("aside-overlay.sock")
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(str(sock_path))
        return sock
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        return None


def _overlay_send(sock: socket.socket | None, msg: dict) -> None:
    """Send a JSON-line command to the overlay.  Swallows errors."""
    if sock is None:
        return
    try:
        sock.sendall((json.dumps(msg) + "\n").encode("utf-8"))
    except (BrokenPipeError, OSError):
        pass


def _overlay_close(sock: socket.socket | None) -> None:
    """Close overlay socket, ignoring errors."""
    if sock is None:
        return
    try:
        sock.close()
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Error notification
# ---------------------------------------------------------------------------


def notify_error(message: str) -> None:
    """Fire-and-forget critical error notification via notify-send."""
    try:
        subprocess.Popen(
            ["notify-send", "-u", "critical", "-a", "Aside", "Aside", message],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Streaming API call
# ---------------------------------------------------------------------------


def stream_response(
    model: str,
    messages: list[dict],
    tools: list[dict],
    cancel_event: threading.Event | None,
    overlay_sock: socket.socket | None,
    tts,  # TTSPipeline | None
    sentence_buf: SentenceBuffer,
    speak_on: bool,
) -> tuple[str, list[dict], dict]:
    """Stream an LLM response via LiteLLM.

    Returns ``(accumulated_text, tool_calls, usage_dict)`` where:
    - *accumulated_text* is the full assistant text content.
    - *tool_calls* is a list of ``{"id": ..., "name": ..., "arguments": {...}}``.
    - *usage_dict* has ``model``, ``input_tokens``, ``output_tokens`` (may be
      zeroed if the provider doesn't report usage).
    """
    api_kwargs: dict = {
        "model": model,
        "messages": messages,
        "max_tokens": MAX_TOKENS,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        api_kwargs["tools"] = tools

    accumulated_text = ""
    accumulated_tool_calls: dict[int, dict] = {}
    usage = {"model": model, "input_tokens": 0, "output_tokens": 0}

    response_stream = litellm.completion(**api_kwargs)

    for chunk in response_stream:
        if cancel_event and cancel_event.is_set():
            _overlay_send(overlay_sock, {"cmd": "clear"})
            # Close the stream iterator if possible.
            if hasattr(response_stream, "close"):
                response_stream.close()
            return accumulated_text, [], usage

        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            # Usage-only final chunk (no choices).
            if hasattr(chunk, "usage") and chunk.usage is not None:
                usage["input_tokens"] = getattr(chunk.usage, "prompt_tokens", 0) or 0
                usage["output_tokens"] = getattr(chunk.usage, "completion_tokens", 0) or 0
                usage["model"] = getattr(chunk, "model", model) or model
            continue

        delta = choice.delta

        # Text content.
        if delta and delta.content:
            accumulated_text += delta.content

            if speak_on and tts is not None:
                for sentence in sentence_buf.add(delta.content):
                    tts.speak(sentence)

            _overlay_send(overlay_sock, {
                "cmd": "text",
                "data": delta.content,
            })

        # Tool calls (streamed incrementally).
        if delta and delta.tool_calls:
            _accumulate_tool_calls(accumulated_tool_calls, delta.tool_calls)

        # Usage from the last chunk (some providers put it on the final choice).
        if hasattr(chunk, "usage") and chunk.usage is not None:
            usage["input_tokens"] = getattr(chunk.usage, "prompt_tokens", 0) or 0
            usage["output_tokens"] = getattr(chunk.usage, "completion_tokens", 0) or 0
            usage["model"] = getattr(chunk, "model", model) or model

    # Flush remaining TTS.
    if speak_on and tts is not None:
        for sentence in sentence_buf.flush():
            tts.speak(sentence)

    tool_calls = _parse_tool_calls(accumulated_tool_calls)
    return accumulated_text, tool_calls, usage


# ---------------------------------------------------------------------------
# Main query pipeline
# ---------------------------------------------------------------------------


def send_query(
    text: str,
    conversation_id,
    config: dict,
    store,          # ConversationStore
    status,         # StatusState
    usage_log,      # UsageLog
    cancel_event: threading.Event | None = None,
    image: str | None = None,
    file: str | None = None,
    tts=None,       # TTSPipeline | None
    plugin_dirs: list[Path] | None = None,
    tools: list[dict] | None = None,
) -> str | None:
    """Send text to an LLM.  The single entry point for all query paths.

    Parameters
    ----------
    text:
        The user's message.
    conversation_id:
        - ``None`` -> auto-detect (most recent within threshold)
        - ``NEW_CONVERSATION`` -> explicit fresh conversation
        - ``"uuid-string"`` -> continue that specific conversation
    config:
        Full config dict (from ``load_config``).
    store:
        A ``ConversationStore`` instance.
    status:
        A ``StatusState`` instance (for status bar updates).
    usage_log:
        A ``UsageLog`` instance.
    cancel_event:
        Optional event to signal cancellation.
    image:
        Optional base64-encoded PNG.
    file:
        Optional file path string for file context.
    tts:
        Optional ``TTSPipeline`` instance.
    plugin_dirs:
        Directories to scan for tool plugins.
    tools:
        Pre-loaded tool definitions (OpenAI format).  If ``None``, no tools.

    Returns the conversation id, or ``None`` if cancelled before any streaming.
    """
    # ------------------------------------------------------------------
    # Resolve conversation
    # ------------------------------------------------------------------
    if conversation_id is NEW_CONVERSATION:
        conv = store.get_or_create()
    elif conversation_id is not None:
        conv = store.get_or_create(conversation_id)
    else:
        resolved = store.auto_resolve()
        conv = store.get_or_create(resolved) if resolved else store.get_or_create()

    model = config.get("model", {}).get("name", "anthropic/claude-sonnet-4-6")
    system_extra = config.get("model", {}).get("system_prompt", "")
    system_prompt = _build_system_prompt(extra=system_extra)

    # ------------------------------------------------------------------
    # TTS setup
    # ------------------------------------------------------------------
    speak_on = False
    if tts is not None:
        status.reload_speak_enabled()
        speak_on = status.speak_enabled
    if speak_on and tts is not None:
        tts.start()
        status.set_status("speaking")
    else:
        status.set_status("thinking")

    # ------------------------------------------------------------------
    # Build initial user message and add to conversation
    # ------------------------------------------------------------------
    if file:
        user_text = (
            f"[Attached file: {file}]\n"
            "When you produce an output file, copy it to the clipboard "
            "using the clipboard tool's file parameter.\n\n" + text
        )
    else:
        user_text = text

    if image:
        user_content = [
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image}"},
            },
            {"type": "text", "text": user_text},
        ]
    else:
        user_content = user_text  # type: ignore[assignment]

    conv["messages"].append({"role": "user", "content": user_content})
    store.write_transcript(conv)

    # ------------------------------------------------------------------
    # Streaming loop with tool execution
    # ------------------------------------------------------------------
    full_text = ""
    overlay_sock = _connect_overlay()
    _overlay_send(overlay_sock, {"cmd": "open", "mode": "agent", "conv_id": conv["id"]})
    sentence_buf = SentenceBuffer()
    session_tokens = 0
    dirs = plugin_dirs or []

    try:
        while True:
            # Build the messages list fresh each iteration (system + history).
            messages = _build_messages(
                text="",  # text is already in conv["messages"]
                history=conv["messages"],
                system_prompt=system_prompt,
                image=None,  # image is already in conv["messages"]
            )
            # Remove the empty trailing user message that _build_messages appends.
            messages.pop()

            resp_text, tool_calls, usage = stream_response(
                model=model,
                messages=messages,
                tools=tools or [],
                cancel_event=cancel_event,
                overlay_sock=overlay_sock,
                tts=tts,
                sentence_buf=sentence_buf,
                speak_on=speak_on,
            )

            # Cancelled.
            if cancel_event and cancel_event.is_set() and not resp_text and not tool_calls:
                break

            full_text += resp_text

            # Log usage.
            usage_log.log(usage["model"], usage["input_tokens"], usage["output_tokens"])
            session_tokens += usage["input_tokens"] + usage["output_tokens"]
            status.update_usage(session_tokens)

            # Build assistant message for conversation history.
            assistant_msg: dict = {"role": "assistant", "content": resp_text or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ]
                # OpenAI format: when there are tool_calls, content can be null.
                if not resp_text:
                    assistant_msg["content"] = None
            conv["messages"].append(assistant_msg)
            store.write_transcript(conv)

            if not tool_calls or (cancel_event and cancel_event.is_set()):
                break

            # Execute tools.
            for tc in tool_calls:
                if cancel_event and cancel_event.is_set():
                    break
                log.info("Executing tool: %s", tc["name"])
                status.set_status("tool_use", tool_name=tc["name"])
                result = run_tool(tc["name"], tc["arguments"], dirs)

                # Format tool result for conversation history.
                if isinstance(result, dict) and result.get("type") == "image":
                    result_content = json.dumps(result)
                else:
                    result_content = str(result)

                conv["messages"].append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_content,
                })

            # Update overlay with tool execution info.
            tool_names = " \u2192 ".join(tc["name"] for tc in tool_calls)
            if full_text:
                full_text += "\n\n"
            full_text += f"{tool_names}\n\n"
            _overlay_send(overlay_sock, {"cmd": "replace", "data": full_text})
            if speak_on and tts is not None and tts._running:
                status.set_status("speaking")
            else:
                status.set_status("thinking")

        # Save conversation.
        store.save(conv)
        store.save_last(conv["id"])

        # Wait for TTS.
        if tts is not None and tts._running:
            if cancel_event and cancel_event.is_set():
                tts.stop()
            else:
                tts.finish()
                tts.wait_done(120)
                tts.stop()

        log.info("Conversation %s complete (%d messages)",
                 conv["id"][:8], len(conv["messages"]))

        # Fade out overlay.
        _overlay_send(overlay_sock, {"cmd": "done"})
        _overlay_close(overlay_sock)

        return conv["id"]

    except litellm.exceptions.AuthenticationError as e:
        log.error("Authentication error: %s", e)
        _overlay_send(overlay_sock, {"cmd": "clear"})
        _overlay_close(overlay_sock)
        notify_error("API key missing or invalid — check env vars")
        if tts is not None:
            tts.stop()
        store.save(conv)
        return conv["id"]
    except litellm.exceptions.APIError as e:
        log.error("API error: %s", e)
        _overlay_send(overlay_sock, {"cmd": "clear"})
        _overlay_close(overlay_sock)
        notify_error(f"API error: {e}")
        if tts is not None:
            tts.stop()
        store.save(conv)
        return conv["id"]
    except Exception:
        log.exception("Unexpected error during query")
        _overlay_send(overlay_sock, {"cmd": "clear"})
        _overlay_close(overlay_sock)
        notify_error("Unexpected error (check logs)")
        if tts is not None:
            tts.stop()
        store.save(conv)
        return conv["id"]
    finally:
        status.set_status("idle")
