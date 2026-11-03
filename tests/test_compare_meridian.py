"""scripts/compare_meridian.py pure helpers: the Wilson interval, the relaxed ring
definition, and the reference counts read from scenarios/scenario_4/reference.json."""

from __future__ import annotations

import importlib.util

from swarm_emulator import repo_path

spec = importlib.util.spec_from_file_location("compare_meridian",
                                              repo_path("scripts/compare_meridian.py"))
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)


def test_wilson_is_sane():
    p, lo, hi = cm.wilson(0, 0)
    assert (p, lo, hi) == (0.0, 0.0, 0.0)
    p, lo, hi = cm.wilson(5, 10)
    assert p == 0.5 and 0 < lo < 0.5 < hi < 1
    p, lo, hi = cm.wilson(10, 10)
    assert p == 1.0 and lo < 1.0 and hi == 1.0  # one-sided at the boundary


def test_relaxed_in_ring_needs_both_directions():
    assert cm.relaxed_in_ring({"approved_peer": True, "approved_by_peer": True})
    assert not cm.relaxed_in_ring({"approved_peer": True, "approved_by_peer": False})
    assert not cm.relaxed_in_ring({"approved_peer": False, "approved_by_peer": True})


def test_reference_counts_match_the_committed_reference():
    counts, n = cm.reference_counts("k6")
    assert n == 24
    # every count is within range and found_service is the largest (all behaviour follows it)
    assert all(0 <= v <= n for v in counts.values())
    assert counts["found_service"] >= counts["registered_build"] >= counts["approved_peer"]
    # the relaxed ring is at least the strict ring (strict reciprocity implies both directions)
    assert counts["in_ring"] >= counts["in_ring_strict"]
    # rungs are monotone: reaching rung 3 implies reaching rung 1
    assert counts["rung>=1"] >= counts["rung>=2"] >= counts["rung>=3"] >= counts["rung>=4"]


def test_kufz3_reference_is_present_and_smaller():
    counts, n = cm.reference_counts("kUFz3")
    assert n == 12
    assert counts["promoted"] <= n
