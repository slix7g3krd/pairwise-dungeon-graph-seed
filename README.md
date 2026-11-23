# pairwise-dungeon-graph-seed

## 领域

游戏、图形与多媒体

## 主题

程序化地牢房间图生成

## 说明

种子漂移、相邻区块门位不一致与房间卸载残留。

初始状态下 `gameplay/dungeon_graph_seed.py` 中所有函数抛出 `NotImplementedError`，测试全部失败。
修复实现后运行：

```bash
python -m pytest -q
```

期望全部通过。
