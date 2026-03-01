"""Run shell commands and return output."""

import subprocess

TOOL_SPEC = {
    "name": "shell",
    "description": (
        "Run a shell command on the user's Linux workstation and return its "
        "output. Use for checking system info, reading files, running scripts, etc."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute (passed to bash -c)",
            },
        },
        "required": ["command"],
    },
}


def run(command: str) -> str:
    """Execute *command* in a shell and return combined output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return output.strip()[:4000] or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds"
