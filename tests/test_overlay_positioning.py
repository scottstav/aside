"""Tests for aside.overlay.positioning — pure position/size logic."""

import pytest

from aside.overlay.positioning import (
    DIRECTIONS,
    MAX_DIMENSION,
    MIN_MAX_HEIGHT,
    MIN_WIDTH,
    SLOTS,
    normalize_position,
    step_position,
)


class TestConstants:
    def test_slots(self):
        assert SLOTS == (
            "top-left", "top-center", "top-right",
            "bottom-left", "bottom-center", "bottom-right",
        )

    def test_directions(self):
        assert DIRECTIONS == ("up", "down", "left", "right")

    def test_size_bounds(self):
        assert MIN_WIDTH == 250
        assert MIN_MAX_HEIGHT == 150
        assert MAX_DIMENSION == 4000


class TestNormalizePosition:
    def test_canonical_slots(self):
        assert normalize_position("top-left") == ("top", "left")
        assert normalize_position("top-center") == ("top", "center")
        assert normalize_position("top-right") == ("top", "right")
        assert normalize_position("bottom-left") == ("bottom", "left")
        assert normalize_position("bottom-center") == ("bottom", "center")
        assert normalize_position("bottom-right") == ("bottom", "right")

    def test_loose_strings_match_window_substring_semantics(self):
        # Same semantics as the anchoring block in OverlayWindow.__init__:
        # "bottom" substring -> bottom row, else top; "left"/"right"
        # substring -> that column, else center.
        assert normalize_position("top") == ("top", "center")
        assert normalize_position("bottom") == ("bottom", "center")
        assert normalize_position("") == ("top", "center")
        assert normalize_position("garbage") == ("top", "center")
        assert normalize_position("bottomleft") == ("bottom", "left")

    def test_left_wins_over_right_like_window_elif(self):
        # window.py checks "left" first, elif "right" — preserve that.
        assert normalize_position("left-right") == ("top", "left")


class TestStepPosition:
    # Exhaustive: 6 slots x 4 directions = 24 cases.
    CASES = {
        ("top-left", "up"): "top-left",          # clamp
        ("top-left", "down"): "bottom-left",
        ("top-left", "left"): "top-left",         # clamp
        ("top-left", "right"): "top-center",
        ("top-center", "up"): "top-center",       # clamp
        ("top-center", "down"): "bottom-center",
        ("top-center", "left"): "top-left",
        ("top-center", "right"): "top-right",
        ("top-right", "up"): "top-right",         # clamp
        ("top-right", "down"): "bottom-right",
        ("top-right", "left"): "top-center",
        ("top-right", "right"): "top-right",      # clamp
        ("bottom-left", "up"): "top-left",
        ("bottom-left", "down"): "bottom-left",   # clamp
        ("bottom-left", "left"): "bottom-left",   # clamp
        ("bottom-left", "right"): "bottom-center",
        ("bottom-center", "up"): "top-center",
        ("bottom-center", "down"): "bottom-center",  # clamp
        ("bottom-center", "left"): "bottom-left",
        ("bottom-center", "right"): "bottom-right",
        ("bottom-right", "up"): "top-right",
        ("bottom-right", "down"): "bottom-right",  # clamp
        ("bottom-right", "left"): "bottom-center",
        ("bottom-right", "right"): "bottom-right",  # clamp
    }

    def test_all_24_steps(self):
        for (current, direction), expected in self.CASES.items():
            assert step_position(current, direction) == expected, (
                f"step_position({current!r}, {direction!r})"
            )

    def test_loose_current_is_normalized(self):
        assert step_position("top", "down") == "bottom-center"

    def test_unknown_direction_raises(self):
        with pytest.raises(ValueError):
            step_position("top-center", "diagonal")


from aside.overlay.positioning import anchor_spec


class TestAnchorSpec:
    def test_top_center_anchors_top_only(self):
        assert anchor_spec("top-center") == {"top": "margin_top"}

    def test_bottom_center_reuses_margin_top_quirk(self):
        # Existing behavior (window.py bottom branch): the BOTTOM margin
        # is set from the margin_top config value. Preserved deliberately.
        assert anchor_spec("bottom-center") == {"bottom": "margin_top"}

    def test_corners(self):
        assert anchor_spec("top-left") == {"top": "margin_top", "left": "margin_left"}
        assert anchor_spec("top-right") == {"top": "margin_top", "right": "margin_right"}
        assert anchor_spec("bottom-left") == {"bottom": "margin_top", "left": "margin_left"}
        assert anchor_spec("bottom-right") == {"bottom": "margin_top", "right": "margin_right"}

    def test_loose_string(self):
        assert anchor_spec("bottom") == {"bottom": "margin_top"}


from aside.overlay.positioning import clamp_size, parse_size_spec


class TestParseSizeSpec:
    def test_relative_plus(self):
        assert parse_size_spec("+50", 400) == 450

    def test_relative_minus(self):
        assert parse_size_spec("-50", 400) == 350

    def test_absolute_string(self):
        assert parse_size_spec("450", 400) == 450

    def test_absolute_int(self):
        # JSON senders may pass a bare number.
        assert parse_size_spec(450, 400) == 450

    def test_whitespace_tolerated(self):
        assert parse_size_spec(" +50 ", 400) == 450

    def test_junk_raises(self):
        with pytest.raises(ValueError):
            parse_size_spec("wide", 400)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            parse_size_spec("", 400)

    def test_bool_raises(self):
        # True is an int subclass; reject it explicitly.
        with pytest.raises(ValueError):
            parse_size_spec(True, 400)


class TestClampSize:
    def test_below_floor(self):
        assert clamp_size(100, 250, 4000) == 250

    def test_above_ceiling(self):
        assert clamp_size(9999, 250, 4000) == 4000

    def test_in_range(self):
        assert clamp_size(400, 250, 4000) == 400
