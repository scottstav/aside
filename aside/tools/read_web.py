"""Read a web page and return its main readable text content.

Renders the page in headless Chromium (Playwright) so JavaScript-driven
sites work, then strips nav/ads/boilerplate with trafilatura.  Falls back
to a plain HTTP fetch when Playwright or its browser is unavailable.

Requires: trafilatura for extraction; playwright + ``playwright install
chromium`` for JavaScript-rendered pages (``pip install aside-assistant[web]``).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

log = logging.getLogger(__name__)

MAX_CHARS = 10_000
PAGE_LOAD_TIMEOUT_MS = 20_000
NETWORK_IDLE_TIMEOUT_MS = 4_000
# Headless Chromium's default UA advertises "HeadlessChrome", which many
# sites block outright — present as a normal desktop browser instead.
_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

TOOL_SPEC = {
    "name": "read_web",
    "description": (
        "Fetch a web page URL and return its readable text content -- the "
        "main article/page content a human would see in a browser, with "
        "navigation, ads and boilerplate stripped. Handles "
        "JavaScript-rendered pages. Use whenever the user shares a link or "
        "an answer requires reading a specific page."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The http(s) URL of the page to read.",
            },
        },
        "required": ["url"],
    },
}


def _render(url: str) -> tuple[str, str]:
    """Load *url* in headless Chromium and return (html, visible body text)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(user_agent=_UA)
            # Text is all we need — skip heavy resources.
            page.route(
                "**/*",
                lambda route: route.abort()
                if route.request.resource_type in ("image", "media", "font")
                else route.continue_(),
            )
            page.goto(url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS)
            try:
                page.wait_for_load_state(
                    "networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS
                )
            except Exception:
                pass  # page never settled — use whatever has rendered
            html = page.content()
            try:
                body_text = page.inner_text("body")
            except Exception:
                body_text = ""
            return html, body_text
        finally:
            browser.close()


def _fetch_plain(url: str) -> str | None:
    """Fetch *url* over plain HTTP (no JS) and return the HTML, or None."""
    import httpx

    resp = httpx.get(
        url,
        headers={"User-Agent": _UA},
        follow_redirects=True,
        timeout=PAGE_LOAD_TIMEOUT_MS / 1000,
    )
    if resp.status_code >= 400:
        log.info("read_web: plain fetch of %s returned HTTP %s", url, resp.status_code)
        return None
    return resp.text


def _extract(html: str, url: str, body_text: str = "") -> str | None:
    """Pull readable text out of *html*, falling back to raw body text."""
    import trafilatura

    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=True
    )
    if not text:
        text = trafilatura.extract(
            html, url=url, include_comments=False, favor_recall=True
        )
    if not text and body_text.strip():
        # JS apps whose DOM isn't article-shaped: use the page's visible text.
        text = re.sub(r"\n{3,}", "\n\n", body_text).strip()
    return text or None


def run(url: str) -> str:
    """Fetch *url* and return its clean readable text."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return f"Error: expected an http(s) URL, got {url!r}."

    try:
        import trafilatura  # noqa: F401
    except ImportError:
        return (
            "Error: read_web needs the 'trafilatura' package. "
            "Install with: pip install aside-assistant[web]"
        )

    body_text = ""
    render_error = None
    try:
        html, body_text = _render(url)
    except Exception as exc:
        first_line = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        render_error = first_line
        log.info(
            "read_web: browser render failed (%s) — falling back to plain fetch",
            first_line,
        )
        try:
            html = _fetch_plain(url)
        except Exception as fetch_exc:
            html = None
            render_error = f"{first_line}; plain fetch: {fetch_exc}"

    if not html:
        detail = f" ({render_error})" if render_error else ""
        return f"Error: could not fetch {url}{detail}"

    text = _extract(html, url, body_text)
    if not text:
        return f"Error: fetched {url} but could not extract readable text."

    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip() + "\n\n[... truncated]"
    return text
