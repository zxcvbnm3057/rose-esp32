"""Unit tests for software signal-resolution glitch-merging (bridge/client.py).

The firmware always captures at finest resolution; the bridge client applies
the requested resolution in software by merging glitches (pulses narrower than
the resolution) into the preceding edge.  No hardware required.
"""

from ..src.client import apply_resolution, resolve_resolution_us, RESOLUTION_PRESETS


# ── resolve_resolution_us ────────────────────────────────────────────────

def test_resolve_none_is_exact():
    assert resolve_resolution_us(None) == 1


def test_resolve_preset_names():
    assert resolve_resolution_us("exact") == RESOLUTION_PRESETS["exact"]
    assert resolve_resolution_us("fine") == RESOLUTION_PRESETS["fine"]
    assert resolve_resolution_us("normal") == RESOLUTION_PRESETS["normal"]
    assert resolve_resolution_us("coarse") == RESOLUTION_PRESETS["coarse"]


def test_resolve_preset_case_insensitive():
    assert resolve_resolution_us("Normal") == RESOLUTION_PRESETS["normal"]
    assert resolve_resolution_us("  COARSE ") == RESOLUTION_PRESETS["coarse"]


def test_resolve_unknown_name_falls_back_to_exact():
    assert resolve_resolution_us("bogus") == 1


def test_resolve_int_microseconds():
    assert resolve_resolution_us(50) == 50
    assert resolve_resolution_us(0) == 1   # clamped to >=1
    assert resolve_resolution_us(-5) == 1


def test_resolve_bad_type_falls_back():
    assert resolve_resolution_us([1, 2]) == 1


# ── apply_resolution (glitch-merge, semantics B) ─────────────────────────

def test_resolution_exact_is_noop():
    edges = [(1, 100), (0, 3), (1, 50)]
    assert apply_resolution(edges, 1) == edges


def test_resolution_empty_list():
    assert apply_resolution([], 20) == []


def test_glitch_merged_into_previous_edge():
    # (0,3) is narrower than 10us -> dropped, its 3us folded into prev (1,100),
    # then the following (1,50) coalesces with the now-(1,103) same-level edge.
    edges = [(1, 100), (0, 3), (1, 50)]
    result = apply_resolution(edges, 10)
    assert result == [(1, 153)]


def test_glitch_preserves_total_elapsed_time():
    edges = [(1, 100), (0, 3), (1, 50)]
    total_in = sum(d for _, d in edges)
    result = apply_resolution(edges, 10)
    total_out = sum(d for _, d in result)
    assert total_out == total_in


def test_wide_pulses_kept_unchanged():
    edges = [(1, 100), (0, 200), (1, 300)]
    assert apply_resolution(edges, 50) == edges


def test_leading_glitch_folded_forward():
    # A glitch before any kept edge carries its duration onto the first kept edge.
    edges = [(1, 2), (0, 100)]
    result = apply_resolution(edges, 10)
    assert result == [(0, 102)]


def test_multiple_consecutive_glitches():
    # Two adjacent glitches both fold into the preceding kept edge.
    edges = [(1, 100), (0, 2), (1, 3), (0, 80)]
    result = apply_resolution(edges, 10)
    # (0,2)->folds into (1,100)=>(1,102); (1,3)->folds into (1,102)=>(1,105);
    # then (0,80) is wide -> kept as new edge.
    assert result == [(1, 105), (0, 80)]


def test_all_glitches_collapse_to_single_or_empty():
    # Every pulse is a glitch; with nothing wide enough to keep, the leading
    # carry has no kept edge to attach to -> empty result.
    edges = [(1, 2), (0, 3), (1, 1)]
    result = apply_resolution(edges, 10)
    assert result == []


def test_resolution_as_preset_name_via_resolve():
    edges = [(1, 100), (0, 3), (1, 50)]
    res = resolve_resolution_us("fine")  # 5us
    # (0,3) < 5 -> glitch merged; result coalesces to single edge.
    assert apply_resolution(edges, res) == [(1, 153)]
