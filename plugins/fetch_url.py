"""Fetch and extract article text from a URL.

Requires: trafilatura (pip install trafilatura)
"""

import trafilatura

TOOL_SPEC = {
    "name": "fetch_url",
    "description": (
        "Fetch a web page and extract its main text content. Use after "
        "web_search to read full articles."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch",
            },
        },
        "required": ["url"],
    },
}


def run(url: str) -> str:
    """Fetch *url* and extract main text content."""
    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return f"Failed to fetch {url}"
    text = trafilatura.extract(downloaded)
    if not text:
        return f"Could not extract text from {url}"
    return text[:6000]
