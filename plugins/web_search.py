"""Search the web via DuckDuckGo.

Requires: duckduckgo-search (pip install duckduckgo-search)
"""

from ddgs import DDGS

TOOL_SPEC = {
    "name": "web_search",
    "description": (
        "Search the web for current information. Returns titles, URLs, and "
        "snippets for the top results. Use fetch_url to read full articles."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query",
            },
        },
        "required": ["query"],
    },
}


def run(query: str) -> str:
    """Search DuckDuckGo and return formatted results."""
    results = DDGS().text(query, max_results=5)
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"**{r['title']}**")
        lines.append(r["href"])
        lines.append(r.get("body", ""))
        lines.append("")
    return "\n".join(lines).strip()
