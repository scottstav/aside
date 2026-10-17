"""Live smoke test: real queries through aside's own streaming code.

dev/release.sh runs this before anything is published, using the litellm
that is about to ship. The unit tests mock litellm.completion, so this is
the only check that catches a litellm upgrade changing stream chunks,
tool-call deltas or usage reporting. Uses the model from your aside config
and its key from the environment or keyring.
"""
from __future__ import annotations

import sys

import litellm

from aside.config import load_config
from aside.keyring import ensure_key_for_model
from aside.query import stream_response
from aside.sentence_buffer import SentenceBuffer

litellm.suppress_debug_info = True

TOOL = {
    "type": "function",
    "function": {
        "name": "get_time",
        "description": "Return the current local time.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}


def ask(model: str, prompt: str, tools: list[dict]):
    return stream_response(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        tools=tools,
        cancel_event=None,
        overlay_sock=None,
        tts=None,
        sentence_buf=SentenceBuffer(),
        speak_on=False,
        timeout=60,
    )


def main() -> int:
    model = load_config().get("model", {}).get("name", "anthropic/claude-sonnet-4-6")
    if not ensure_key_for_model(model):
        print(f"smoke: no API key for {model} in the environment or keyring")
        return 1

    try:
        text, _, usage = ask(model, "Reply with the single word: ok", [])
        if not text.strip() or not usage.get("output_tokens"):
            print(f"smoke: empty reply or no usage from {model}: {text!r} {usage}")
            return 1

        for _ in range(2):  # a model occasionally answers in text instead
            _, calls, _ = ask(model, "Call the get_time tool now. Do not reply in text.", [TOOL])
            if calls and calls[0].get("name") == "get_time":
                break
        else:
            print(f"smoke: {model} never produced a parsed get_time tool call")
            return 1
    except Exception as e:  # any provider or litellm failure fails the gate
        first = (str(e).splitlines() or [""])[0][:300]
        print(f"smoke: {model}: {type(e).__name__}: {first}")
        return 1

    print(f"smoke ok: {model} streamed text and a tool call")
    return 0


if __name__ == "__main__":
    sys.exit(main())
