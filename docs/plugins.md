# Plugins

A plugin is a single Python file with two things: a `TOOL_SPEC` dict and a `run()` function.

## Example

```python
# plugins/hello.py

TOOL_SPEC = {
    "name": "hello",
    "description": "Say hello to someone",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Who to greet"},
        },
        "required": ["name"],
    },
}

def run(name: str) -> str:
    return f"Hello, {name}!"
```

## Installing plugins

Drop the file into `~/.local/lib/aside/plugins/` or any directory listed in `plugins.dirs` in your config. The daemon loads it on next startup.

## Spec format

The `TOOL_SPEC` follows the OpenAI function-calling schema. `run()` receives keyword arguments matching the parameters and returns a string (or a dict with `{"type": "image", "data": ..., "media_type": ...}` for images).

## Built-in tools

| Tool | Description |
|------|-------------|
| `clipboard` | Copy text or file URIs to the Wayland clipboard |
| `shell` | Run bash commands (30s timeout, output truncated to 4000 chars) |
| `memory` | Persistent key-value store for preferences and context across conversations |

## Example plugins (included in `plugins/`)

| Plugin | Description |
|--------|-------------|
| `screenshot` | Capture full screen or a region, send to LLM for visual analysis |
| `web_search` | Search DuckDuckGo, returns top 5 results |
| `fetch_url` | Fetch a URL and extract article text |
