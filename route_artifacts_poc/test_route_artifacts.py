"""
test_route_artifacts.py

Unit tests for the route-artifacts POC (route_artifacts.py). Pure logic, no
video/OCR: positions are fed in as plain km numbers, exactly the boundary the
module is designed around.

Covers the behaviours the feature depends on:
  - fire ONCE, only when the rider's position reaches an artifact's anchor;
  - a backwards OCR flicker never re-fires or skips;
  - artifacts already behind the session's start aren't "discovered";
  - persistence survives a store reopen (the whole point of the feature);
  - FIFO prune bounds storage while keeping ids unique.
"""

import pytest

from route_artifacts import ArtifactDiscoverer, ArtifactStore

ROUTE = "test-route"


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(str(tmp_path / "store.json"))


def _drop(store, pos, text="note", author="a"):
    return store.drop(ROUTE, pos, text, author=author)


# ---- discovery ------------------------------------------------------------

def test_fires_once_when_position_reaches_anchor(store):
    _drop(store, 5.80, "hi")
    disc = ArtifactDiscoverer(store.artifacts_for(ROUTE))

    # baseline start behind the anchor; nothing yet
    assert disc.advance(5.64) == []
    # not there yet
    assert disc.advance(5.75) == []
    # cross it -> fires exactly once
    fired = disc.advance(5.81)
    assert [a.payload for a in fired] == ["hi"]
    # passing further never re-fires
    assert disc.advance(5.90) == []


def test_multiple_anchors_fire_in_position_order(store):
    # dropped out of order; discovery should still fire by position along route
    _drop(store, 5.88, "second")
    _drop(store, 5.72, "first")
    disc = ArtifactDiscoverer(store.artifacts_for(ROUTE))

    got = []
    for km in [5.64, 5.70, 5.75, 5.85, 5.90]:   # 5.64 baselines the start
        got += [a.payload for a in disc.advance(km)]
    assert got == ["first", "second"]


def test_backward_flicker_does_not_refire_or_skip(store):
    _drop(store, 5.80, "x")
    disc = ArtifactDiscoverer(store.artifacts_for(ROUTE))
    disc.advance(5.64)                # baseline
    assert [a.payload for a in disc.advance(5.81)] == ["x"]  # crossed
    assert disc.advance(5.70) == []   # OCR flicker backwards -> ignored
    assert disc.advance(5.85) == []   # already fired, not repeated


def test_none_positions_are_ignored(store):
    _drop(store, 5.80, "x")
    disc = ArtifactDiscoverer(store.artifacts_for(ROUTE))
    assert disc.advance(None) == []   # unreadable before baseline
    disc.advance(5.64)                # baseline
    assert disc.advance(None) == []   # unreadable mid-ride
    assert [a.payload for a in disc.advance(5.81)] == ["x"]


def test_artifact_behind_start_not_discovered(store):
    _drop(store, 5.50, "behind")      # behind where this session starts
    _drop(store, 5.80, "ahead")
    disc = ArtifactDiscoverer(store.artifacts_for(ROUTE))
    got = []
    for km in [5.64, 5.70, 5.85]:     # start at 5.64, already past 5.50
        got += [a.payload for a in disc.advance(km)]
    assert got == ["ahead"]


def test_trigger_radius_fires_early(store):
    _drop(store, 5.80, "x")
    disc = ArtifactDiscoverer(store.artifacts_for(ROUTE), trigger_radius_km=0.05)
    disc.advance(5.64)                            # baseline
    assert [a.payload for a in disc.advance(5.76)] == ["x"]  # within 0.05 of 5.80


# ---- persistence ----------------------------------------------------------

def test_persistence_survives_reopen(tmp_path):
    path = str(tmp_path / "store.json")
    s1 = ArtifactStore(path)
    s1.drop(ROUTE, 5.72, "kept", author="alice")
    s1.save()

    s2 = ArtifactStore(path)          # brand new instance from disk
    arts = s2.artifacts_for(ROUTE)
    assert len(arts) == 1
    assert arts[0].payload == "kept"
    assert arts[0].author == "alice"


def test_audio_memory_kind_and_payload_persist(tmp_path):
    # an audio memory is just kind="audio" + payload=<clip reference>; the
    # feature relies on both surviving a reopen so a later session can play it.
    path = str(tmp_path / "store.json")
    s1 = ArtifactStore(path)
    s1.drop(ROUTE, 0.62, "clips/memory_alice.wav", author="alice", kind="audio")
    s1.save()

    art = ArtifactStore(path).artifacts_for(ROUTE)[0]
    assert art.kind == "audio"
    assert art.payload == "clips/memory_alice.wav"
    assert art.author == "alice"


def test_ids_unique_across_reopen(tmp_path):
    path = str(tmp_path / "store.json")
    s1 = ArtifactStore(path); s1.drop(ROUTE, 5.7, "a", author="x"); s1.save()
    s2 = ArtifactStore(path); s2.drop(ROUTE, 5.8, "b", author="y"); s2.save()
    ids = [a.id for a in ArtifactStore(path).artifacts_for(ROUTE)]
    assert len(ids) == len(set(ids)) == 2


def test_route_namespacing(store):
    store.drop("route-a", 5.7, "a", author="x")
    store.drop("route-b", 5.7, "b", author="y")
    assert [a.payload for a in store.artifacts_for("route-a")] == ["a"]
    assert [a.payload for a in store.artifacts_for("route-b")] == ["b"]


# ---- pruning --------------------------------------------------------------

def test_prune_keeps_newest_fifo(store):
    for i in range(5):
        _drop(store, 5.60 + i * 0.05, f"note{i}")   # note0 oldest
    removed = store.prune(ROUTE, max_count=3)
    assert removed == 2
    kept = sorted(a.payload for a in store.artifacts_for(ROUTE))
    assert kept == ["note2", "note3", "note4"]       # oldest two dropped


def test_prune_noop_under_limit(store):
    _drop(store, 5.7, "only")
    assert store.prune(ROUTE, max_count=3) == 0
    assert len(store.artifacts_for(ROUTE)) == 1
