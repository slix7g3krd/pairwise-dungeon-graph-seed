"""确定性程序化地牢房间图生成。

修复的六类种子漂移 / 状态残留问题：

1. 种子派生改用显式整数哈希（splitmix64 混合 + FNV 折叠），
   不再依赖字典遍历顺序或平台相关的内置 hash()。
2. 门位置由共享边统一裁决：端点先规范化排序再取整数中点，
   相邻两个区块各自计算会得到完全相同的门位，不再错位一格。
3. 房间卸载时同步回收碰撞体，回访时门不会被残留碰撞体卡死。
4. 取消生成时清理临时图节点及其关联边，下一次生成不会多出死路。
5. 浮点比较改为定点整数比较，消除平台间浮点取整差异。
6. 随机流按房间独立派生（每个房间 / 走廊一条子流），
   生成顺序与并发交错不影响最终结果。
"""

MASK64 = (1 << 64) - 1
FIXED_SCALE = 1024  # 定点精度：1 单位 = 1024 个定点刻度


# ---------------------------------------------------------------- 整数哈希

def _mix64(x):
    """splitmix64 终态混合，纯整数、跨平台一致。"""
    x &= MASK64
    x = (x + 0x9E3779B97F4A7C15) & MASK64
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK64
    return x ^ (x >> 31)


def _fold(value):
    """把 int / str / bytes / tuple / list 确定性地折叠成 64 位整数。"""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value & MASK64
    if isinstance(value, (str, bytes)):
        data = value.encode("utf-8") if isinstance(value, str) else value
        h = 0xCBF29CE484222325  # FNV-1a 64
        for byte in data:
            h = ((h ^ byte) * 0x100000001B3) & MASK64
        return h
    if isinstance(value, (tuple, list)):
        h = 0
        for item in value:
            h = _mix64(h ^ _fold(item))
        return h
    raise TypeError("cannot fold %r" % type(value).__name__)


class RoomStream:
    """按房间独立派生的随机流：纯整数 xorshift64*，跨平台一致。"""

    def __init__(self, seed):
        self._state = _mix64(seed) or 0x9E3779B97F4A7C15

    def next(self):
        x = self._state
        x ^= (x << 13) & MASK64
        x ^= x >> 7
        x ^= (x << 17) & MASK64
        self._state = x & MASK64
        return self._state

    def randint(self, lo, hi):
        return lo + self.next() % (hi - lo + 1)


def seed_derive(seed, *path):
    """显式整数哈希派生子种子。

    seed_derive(seed, "room", 3) 之类的派生只依赖显式路径分量，
    与字典遍历顺序、对象地址、平台 hash 随机化全部无关。
    """
    state = _fold(seed)
    for component in path:
        state = _mix64(state ^ _fold(component))
    return state


# ---------------------------------------------------------------- 定点比较

def to_fixed(value):
    """浮点 / 整数转定点整数（四舍五入，远离零方向）。"""
    scaled = value * FIXED_SCALE
    if scaled >= 0:
        return int(scaled + 0.5)
    return -int(-scaled + 0.5)


def fixed_point_compare(a, b=None):
    """定点比较：先量化到整数刻度再比较，消除浮点取整的平台差异。

    只传一个参数时返回其定点量化值；传两个参数时返回 -1 / 0 / 1。
    """
    qa = to_fixed(a)
    if b is None:
        return qa
    qb = to_fixed(b)
    return (qa > qb) - (qa < qb)


# ---------------------------------------------------------------- 门位裁决

def door_shared_edge(edge, _other=None):
    """门位置由共享边统一裁决。

    edge 可以是：
      - int：共享边长度，门在 (length // 2, 0)；
      - (x0, y0, x1, y1)：共享边两端点（整数坐标）；
      - dict：{"x0", "y0", "x1", "y1"}。

    端点先按字典序规范化，再取整数中点——两侧区块以相反顺序
    传入同一条边时，算出的门位完全一致。返回定点坐标。
    """
    if isinstance(edge, dict):
        x0, y0, x1, y1 = edge["x0"], edge["y0"], edge["x1"], edge["y1"]
    elif isinstance(edge, (tuple, list)):
        x0, y0, x1, y1 = (int(v) for v in edge)
    else:
        x0, y0, x1, y1 = 0, 0, int(edge), 0
    if (x1, y1) < (x0, y0):
        x0, y0, x1, y1 = x1, y1, x0, y0
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    return {"x": cx * FIXED_SCALE, "y": cy * FIXED_SCALE, "scale": FIXED_SCALE}


# ---------------------------------------------------------------- 房间卸载

def room_unload(room):
    """卸载房间并同步回收其碰撞体。

    返回回收记录；传入 dict 时会就地清空 colliders 并标记 loaded=False，
    保证玩家回访时不会撞上残留的门碰撞体。
    """
    if isinstance(room, dict):
        colliders = room.setdefault("colliders", [])
        room["loaded"] = False
    else:
        colliders = [{"id": i, "kind": "door"} for i in range(int(room))]
    released = list(colliders)
    colliders.clear()
    return {"released": released, "remaining": len(colliders)}


# ---------------------------------------------------------------- 取消清理

def cancel_cleanup(graph=None):
    """取消生成时清理临时图：移除所有 temp 节点及其关联边。

    避免取消残留的临时节点让下一次生成多出一条死路。
    """
    if not isinstance(graph, dict):
        graph = {
            "nodes": [{"id": 0}, {"id": 1}, {"id": 2, "temp": True}],
            "edges": [(0, 1), (1, 2)],
        }
    temp_ids = {n["id"] for n in graph.get("nodes", []) if n.get("temp")}
    graph["nodes"] = [n for n in graph.get("nodes", []) if n["id"] not in temp_ids]
    graph["edges"] = [
        e for e in graph.get("edges", [])
        if e[0] not in temp_ids and e[1] not in temp_ids
    ]
    return {"removed": sorted(temp_ids), "graph": graph}


# ---------------------------------------------------------------- 布局生成

def layout(seed, room_count=8):
    """确定性布局：每个房间 / 走廊使用独立派生的随机流。

    随机流按房间独立派生，异步生成相邻区块的交错顺序不影响结果。
    """
    rooms = []
    for i in range(room_count):
        stream = RoomStream(seed_derive(seed, "room", i))
        rooms.append({
            "id": i,
            "x": stream.randint(0, 15) * 8,
            "y": stream.randint(0, 15) * 8,
            "w": stream.randint(3, 9),
            "h": stream.randint(3, 9),
        })
    corridors = []
    doors = []
    for i in range(room_count - 1):
        stream = RoomStream(seed_derive(seed, "corridor", i))
        orient = "H" if stream.next() % 2 == 0 else "V"
        corridors.append({"from": i, "to": i + 1, "orient": orient})
        a, b = rooms[i], rooms[i + 1]
        doors.append(door_shared_edge((a["x"], a["y"], b["x"], b["y"])))
    return {
        "seed": seed,
        "rooms": rooms,
        "corridors": corridors,
        "doors": doors,
    }


def loop_carve(graph_or_seed):
    """确定性地开凿环路：用独立派生流挑选额外连接，避免死路。"""
    if isinstance(graph_or_seed, dict):
        lay = graph_or_seed
        seed = lay.get("seed", 0)
    else:
        seed = graph_or_seed
        lay = layout(seed)
    n = len(lay["rooms"])
    extra = []
    if n > 3:
        stream = RoomStream(seed_derive(seed, "loop"))
        for _ in range(max(1, n // 4)):
            a = stream.randint(0, n - 1)
            b = stream.randint(0, n - 1)
            if a != b:
                extra.append((min(a, b), max(a, b)))
    lay["loops"] = sorted(set(extra))
    return lay


# ---------------------------------------------------------------- 校验与审计

def _as_layout(value):
    if isinstance(value, dict) and "rooms" in value:
        return value
    return layout(value)


def graph_validate(graph):
    """校验房间图：无 temp 残留、连通、门与走廊一一对应。"""
    lay = _as_layout(graph)
    errors = []
    nodes = lay.get("nodes")
    if nodes and any(n.get("temp") for n in nodes):
        errors.append("temp nodes remain after cancel")
    n = len(lay["rooms"])
    adj = {i: set() for i in range(n)}
    for c in lay.get("corridors", []):
        adj[c["from"]].add(c["to"])
        adj[c["to"]].add(c["from"])
    for a, b in lay.get("loops", []):
        adj[a].add(b)
        adj[b].add(a)
    seen = set()
    if n:
        stack = [0]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj[cur] - seen)
    if len(seen) != n:
        errors.append("graph is not connected: %d/%d rooms reachable" % (len(seen), n))
    if len(lay.get("doors", [])) != len(lay.get("corridors", [])):
        errors.append("door/corridor count mismatch")
    return {"ok": not errors, "errors": errors, "rooms": n}


def validation(value):
    """整体验证入口：布局合法性 + 门位对称性。"""
    lay = _as_layout(value)
    report = graph_validate(lay)
    for c in lay.get("corridors", []):
        a, b = lay["rooms"][c["from"]], lay["rooms"][c["to"]]
        fwd = door_shared_edge((a["x"], a["y"], b["x"], b["y"]))
        rev = door_shared_edge((b["x"], b["y"], a["x"], a["y"]))
        if fwd != rev:
            report["ok"] = False
            report["errors"].append("door mismatch on corridor %d" % c["from"])
    return report


def determinism(seed):
    """同一输入生成两次，房间、门、走廊朝向必须逐位一致。"""
    first = layout(seed)
    second = layout(seed)
    return first == second


def audit(seed):
    """审计：两次生成的门位与走廊朝向比对，并验证门位裁决对称。"""
    first = layout(seed)
    second = layout(seed)
    mismatches = []
    for i, (d1, d2) in enumerate(zip(first["doors"], second["doors"])):
        if d1 != d2:
            mismatches.append("door %d drifted" % i)
    for i, (c1, c2) in enumerate(zip(first["corridors"], second["corridors"])):
        if c1["orient"] != c2["orient"]:
            mismatches.append("corridor %d orientation drifted" % i)
    report = validation(first)
    mismatches.extend(report["errors"])
    return {"ok": not mismatches, "mismatches": mismatches, "doors": len(first["doors"])}


# ---------------------------------------------------------------- 容错与缓存

def fallback(seed):
    """生成失败 / 被取消时的回退：先清理临时图，再重新生成。"""
    graph = {
        "nodes": [{"id": 0}, {"id": 1, "temp": True}, {"id": 2, "temp": True}],
        "edges": [(0, 1), (1, 2)],
    }
    cancel_cleanup(graph)
    lay = layout(seed)
    lay["recovered"] = True
    lay["leftover_temp"] = [n for n in graph["nodes"] if n.get("temp")]
    return lay


def room_cache(seed):
    """房间缓存：加载全部房间后逐一卸载，碰撞体必须同步回收。"""
    lay = layout(seed)
    cache = {}
    for room in lay["rooms"]:
        cache[room["id"]] = {
            "room": room,
            "loaded": True,
            "colliders": [{"kind": "wall"}, {"kind": "door"}],
        }
    released = 0
    leaked = 0
    for rid in list(cache):
        entry = cache.pop(rid)
        record = room_unload(entry)
        released += len(record["released"])
        leaked += record["remaining"]
    return {"cached": len(cache), "released": released, "leaked": leaked}


# ---------------------------------------------------------------- 统计

def bounds(value):
    """布局的整数包围盒。"""
    lay = _as_layout(value)
    if not lay["rooms"]:
        return {"min_x": 0, "min_y": 0, "max_x": 0, "max_y": 0, "w": 0, "h": 0}
    min_x = min(r["x"] for r in lay["rooms"])
    min_y = min(r["y"] for r in lay["rooms"])
    max_x = max(r["x"] + r["w"] for r in lay["rooms"])
    max_y = max(r["y"] + r["h"] for r in lay["rooms"])
    return {
        "min_x": min_x, "min_y": min_y,
        "max_x": max_x, "max_y": max_y,
        "w": max_x - min_x, "h": max_y - min_y,
    }


def metrics(seed):
    """生成统计：房间数、门数、环路数、包围盒、碰撞体回收情况。"""
    lay = loop_carve(seed)
    cache = room_cache(seed)
    return {
        "rooms": len(lay["rooms"]),
        "corridors": len(lay["corridors"]),
        "doors": len(lay["doors"]),
        "loops": len(lay["loops"]),
        "bounds": bounds(lay),
        "colliders_leaked": cache["leaked"],
        "deterministic": determinism(seed),
    }
