import pytest
import gameplay.dungeon_graph_seed as mod

CASES = [
    ("seed_derive", (1,)),
    ("door_shared_edge", (1,)),
    ("room_unload", (1,)),
    ("cancel_cleanup", (1,)),
    ("fixed_point_compare", (1,)),
    ("determinism", (1,)),
    ("graph_validate", (1,)),
    ("validation", (1,)),
    ("audit", (1,)),
    ("fallback", (1,)),
    ("room_cache", (1,)),
    ("metrics", (1,)),
    ("layout", (1,)),
    ("loop_carve", (1,)),
    ("bounds", (1,)),
]

@pytest.mark.parametrize("fn_name,args", CASES)
def test_contract(fn_name, args):
    fn = getattr(mod, fn_name)
    assert fn(*args) is not None
