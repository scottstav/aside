"""Tests for the read_web built-in tool."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from aside.plugins import clear_cache, load_tools
from aside.tools import read_web

# A realistic article page: nav/header/footer/aside boilerplate around a
# multi-paragraph article body. trafilatura should keep the article and
# drop the chrome.
ARTICLE_HTML = """\
<html>
<head><title>Why Falcons Dive So Fast</title></head>
<body>
<header>
  <nav>
    <a href="/">Site Navigation Home</a>
    <a href="/subscribe">Subscribe Now Special Offer</a>
    <a href="/login">Log In</a>
  </nav>
</header>
<aside class="ad">Buy premium binoculars today! Limited time discount.</aside>
<article>
  <h1>Why Falcons Dive So Fast</h1>
  <p>The peregrine falcon reaches speeds above three hundred kilometres per
  hour during its hunting stoop, making it the fastest animal on the planet.
  Researchers have long wondered how the bird survives the aerodynamic
  stresses involved in such a dive.</p>
  <p>New wind-tunnel studies show that the falcon's body assumes a teardrop
  shape that delays flow separation, while stiff feathers along the shoulders
  pop up to act like the vortex generators found on aircraft wings.</p>
  <p>High-speed cameras also revealed that falcons adjust their dive angle
  continuously, trading a little speed for a guidance strategy that keeps the
  fleeing prey locked in the same part of their visual field.</p>
  <p>The findings could inform the design of small autonomous aircraft that
  must remain controllable during steep, fast descents in gusty conditions.</p>
</article>
<footer>Copyright 2026 Example News. All rights reserved. Privacy policy.</footer>
</body>
</html>
"""

# A JS-app shell: nothing extractable in the HTML, content only exists as
# rendered text.
SPA_SHELL_HTML = "<html><body><div id='root'></div></body></html>"
SPA_BODY_TEXT = "Quarterly Dashboard\n\nRevenue: $5.2M\nChurn: 2.1%\n"


class TestToolSpec:
    def test_name(self):
        assert read_web.TOOL_SPEC["name"] == "read_web"

    def test_url_required(self):
        params = read_web.TOOL_SPEC["parameters"]
        assert params["required"] == ["url"]
        assert "url" in params["properties"]

    def test_has_description(self):
        assert read_web.TOOL_SPEC["description"].strip()

    def test_loads_via_plugin_system(self):
        """The built-in tools dir must expose read_web through load_tools."""
        clear_cache()
        try:
            builtin_dir = Path(read_web.__file__).parent
            tools = load_tools([builtin_dir])
            names = {t["function"]["name"] for t in tools}
            assert "read_web" in names
        finally:
            clear_cache()


class TestUrlValidation:
    @pytest.mark.parametrize(
        "bad", ["file:///etc/passwd", "ftp://example.com/x", "not a url", ""]
    )
    def test_rejects_non_http_urls(self, bad):
        result = read_web.run(bad)
        assert result.startswith("Error:")
        assert "http" in result

    def test_missing_trafilatura_reports_install_hint(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "trafilatura", None)
        result = read_web.run("https://example.com/")
        assert result.startswith("Error:")
        assert "trafilatura" in result


class TestExtraction:
    @pytest.fixture(autouse=True)
    def _needs_trafilatura(self):
        pytest.importorskip("trafilatura")

    def test_extracts_article_and_strips_boilerplate(self, monkeypatch):
        monkeypatch.setattr(read_web, "_render", lambda url: (ARTICLE_HTML, ""))
        result = read_web.run("https://example.com/falcons")
        assert "teardrop" in result
        assert "vortex generators" in result
        assert "Site Navigation" not in result
        assert "premium binoculars" not in result
        assert "Privacy policy" not in result

    def test_falls_back_to_plain_fetch_when_render_fails(self, monkeypatch):
        def boom(url):
            raise RuntimeError("Executable doesn't exist")

        monkeypatch.setattr(read_web, "_render", boom)
        monkeypatch.setattr(read_web, "_fetch_plain", lambda url: ARTICLE_HTML)
        result = read_web.run("https://example.com/falcons")
        assert "teardrop" in result

    def test_error_when_render_and_fetch_both_fail(self, monkeypatch):
        def boom(url):
            raise RuntimeError("no browser")

        monkeypatch.setattr(read_web, "_render", boom)
        monkeypatch.setattr(read_web, "_fetch_plain", lambda url: None)
        result = read_web.run("https://example.com/x")
        assert result.startswith("Error:")

    def test_spa_falls_back_to_visible_body_text(self, monkeypatch):
        monkeypatch.setattr(
            read_web, "_render", lambda url: (SPA_SHELL_HTML, SPA_BODY_TEXT)
        )
        result = read_web.run("https://app.example.com/")
        assert "Quarterly Dashboard" in result
        assert "Revenue: $5.2M" in result

    def test_error_when_nothing_extractable(self, monkeypatch):
        monkeypatch.setattr(read_web, "_render", lambda url: (SPA_SHELL_HTML, ""))
        result = read_web.run("https://example.com/empty")
        assert result.startswith("Error:")

    def test_long_content_is_truncated(self, monkeypatch):
        monkeypatch.setattr(read_web, "_render", lambda url: (ARTICLE_HTML, ""))
        monkeypatch.setattr(read_web, "_extract", lambda html, url, body: "x" * 50_000)
        result = read_web.run("https://example.com/long")
        assert len(result) < 50_000
        assert result.endswith("[... truncated]")
