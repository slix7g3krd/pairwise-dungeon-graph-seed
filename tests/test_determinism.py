import gameplay.dungeon_graph_seed as mod


def test_seed_derive_is_explicit_integer_hash():
    a = mod.seed_derive(42, "room", 3)
    b = mod.seed_derive(42, "room", 3)
    c = mod.seed_derive(42, "room", 4)
    assert isinstance(a, int)
    assert a == b and a != c


def test_door_shared_edge_is_symmetric():
    fwd = mod.door_shared_edge((3, 7, 10, 2))
    rev = mod.door_shared_edge((10, 2, 3, 7))
    assert fwd == rev


def test_room_unload_releases_colliders():
    room = {"loaded": True, "colliders": [{"kind": "door"}, {"kind": "wall"}]}
    rec = mod.room_unload(room)
    assert rec["remaining"] == 0
    assert len(rec["released"]) == 2
    assert room["colliders"] == [] and room["loaded"] is False


def test_cancel_cleanup_removes_temp_nodes():
    graph = {
        "nodes": [{"id": 0}, {"id": 1, "temp": True}],
        "edges": [(0, 1)],
    }
    out = mod.cancel_cleanup(graph)
    assert out["removed"] == [1]
    assert graph["nodes"] == [{"id": 0}]
    assert graph["edges"] == []


def test_fixed_point_compare_quantizes():
    assert mod.fixed_point_compare(0.1 + 0.2, 0.3) == 0
    assert mod.fixed_point_compare(1.5, 1.4) == 1
    assert mod.fixed_point_compare(1.4, 1.5) == -1


def test_layout_is_deterministic_per_seed():
    assert mod.determinism(123) is True
    assert mod.layout(1) != mod.layout(2)


def test_audit_and_validation_pass():
    assert mod.audit(7)["ok"]
    assert mod.validation(7)["ok"]


def test_room_cache_has_no_leaks():
    assert mod.room_cache(9)["leaked"] == 0


def test_metrics_consistent():
    m = mod.metrics(5)
    assert m["rooms"] == 8
    assert m["doors"] == m["corridors"]
    assert m["colliders_leaked"] == 0
    assert m["deterministic"] is True
