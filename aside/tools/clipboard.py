"""Copy text or a file to the Wayland clipboard."""

import subprocess

TOOL_SPEC = {
    "name": "clipboard",
    "description": (
        "Copy text or a file to the user's clipboard via wl-copy. Use when "
        "the user asks you to copy something, when providing code/text they'll "
        "want to paste, or when you produce an output file the user will want "
        "to paste somewhere."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to copy to clipboard",
            },
            "file": {
                "type": "string",
                "description": (
                    "Absolute path to a file to copy to clipboard as a file "
                    "URI (for pasting into apps like Slack/Discord)"
                ),
            },
        },
    },
}


def run(text: str | None = None, file: str | None = None) -> str:
    """Copy *text* or *file* to the Wayland clipboard."""
    if file:
        uri = f"file://{file}"
        subprocess.run(["wl-copy", "-t", "text/uri-list", uri], check=True)
        return f"Copied file {file} to clipboard."
    elif text:
        subprocess.run(["wl-copy", text], check=True)
        return f"Copied {len(text)} characters to clipboard."
    else:
        return "Error: provide either 'text' or 'file'."
