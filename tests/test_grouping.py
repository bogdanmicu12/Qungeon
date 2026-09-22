"""Runnable checks for the grouping system (QUN-3, QUN-4).

Pure Python: no pygame/unitary needed. Run with `python tests/test_grouping.py`.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.grouping_system import Group, GroupingSystem


class FakeObj:
    """Minimal stand-in for a QuantumObject (only needs a .group attr)."""
    def __init__(self):
        self.group = None


def test_group_states_default_is_len_safe():
    """QUN-3: a group whose pillar never got an effect must not crash
    correlation_update, which does `len(group.states)`."""
    group = Group()
    # Before the fix this was None and len(None) raised TypeError.
    assert len(group.states) == 0
    assert group.states == {}


def test_new_group_via_system_is_len_safe():
    """QUN-3: same guarantee for groups created through GroupingSystem.add."""
    gs = GroupingSystem()
    obj = FakeObj()
    group = gs.add(obj)
    assert len(group.states) == 0  # would TypeError on None


def test_reset_semantics():
    """QUN-4: clearing groups + count is what Game.clean_up relies on."""
    gs = GroupingSystem()
    gs.add(FakeObj())
    gs.add(FakeObj())
    gs.count = 5
    gs.groups.clear()
    gs.count = 0
    assert gs.groups == []
    assert gs.count == 0


if __name__ == "__main__":
    test_group_states_default_is_len_safe()
    test_new_group_via_system_is_len_safe()
    test_reset_semantics()
    print("grouping checks passed")
