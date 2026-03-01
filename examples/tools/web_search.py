"""Search the web via DuckDuckGo (no external dependencies)."""

import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser

TOOL_SPEC = {
    "name": "web_search",
    "description": (
        "Search the web for current information. Returns titles, URLs, and "
        "snippets for the top results."
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

_LITE_URL = "https://lite.duckduckgo.com/lite/"
_HEADERS = {"User-Agent": "aside/0.1"}


class _LiteParser(HTMLParser):
    """Parse DuckDuckGo Lite result rows into (title, url, snippet) tuples."""

    def __init__(self):
        super().__init__()
        self.results: list[dict] = []
        self._in_link = False
        self._in_snippet = False
        self._cur: dict = {}
        self._text = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("class") == "result-link":
            self._in_link = True
            self._cur = {"url": a.get("href", ""), "title": "", "snippet": ""}
            self._text = ""
        if tag == "td" and a.get("class") == "result-snippet":
            self._in_snippet = True
            self._text = ""

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
            self._cur["title"] = self._text.strip()
        if tag == "td" and self._in_snippet:
            self._in_snippet = False
            self._cur["snippet"] = self._text.strip()
            if self._cur.get("url"):
                self.results.append(self._cur)
            self._cur = {}

    def handle_data(self, data):
        if self._in_link or self._in_snippet:
            self._text += data


def _search(query: str, max_results: int = 5) -> list[dict]:
    """Fetch DuckDuckGo Lite results for *query*."""
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(_LITE_URL, data=data, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    parser = _LiteParser()
    parser.feed(html)
    return parser.results[:max_results]


def run(query: str) -> str:
    """Search DuckDuckGo and return formatted results."""
    try:
        results = _search(query)
    except Exception as e:
        return f"Search failed: {e}"
    if not results:
        return "No results found."
    lines = []
    for r in results:
        lines.append(f"**{r['title']}**")
        lines.append(r["url"])
        if r["snippet"]:
            lines.append(r["snippet"])
        lines.append("")
    return "\n".join(lines).strip()
