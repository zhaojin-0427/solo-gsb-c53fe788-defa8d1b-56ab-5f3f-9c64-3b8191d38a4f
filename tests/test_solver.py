"""求解器核心逻辑测试：python3 -m tests.test_solver 或直接 python3 tests/test_solver.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.solver import (  # noqa: E402
    STATUS_INFEASIBLE,
    STATUS_OPTIMAL,
    compute_connectivity,
    solve_isolation,
)


def make_nodes():
    return [
        {"id": "S", "type": "source", "households": 0},
        {"id": "A", "type": "user", "households": 10},
        {"id": "X", "type": "user", "households": 0},
        {"id": "B", "type": "user", "households": 7},
    ]


def make_edges():
    # ER 为检修段；A 与水源 S 之间有两条路径：E3 直连、E2-E1 经 X
    return [
        {"id": "ER", "u": "A", "v": "B", "valve": False},
        {"id": "E1", "u": "S", "v": "X", "valve": True},
        {"id": "E2", "u": "X", "v": "A", "valve": True},
        {"id": "E3", "u": "S", "v": "A", "valve": True},
    ]


def test_lexicographic_valve_choice():
    """断供户数与关阀数相同时，选阀门 ID 升序列表最小者：{E1,E3} 优于 {E2,E3}。"""
    res = solve_isolation(make_nodes(), make_edges(), "ER", [])
    assert res.status == STATUS_OPTIMAL, res
    # 隔离 A 必须关 E3 + (E1 或 E2)；关 E1 时 X 断供但 0 户，断供户数相同、关阀数相同
    assert res.closed_valves == ["E1", "E3"], res.closed_valves
    assert res.valve_count == 2
    assert res.outage_households == 17  # A(10) + B(7)，X 为 0 户
    assert set(res.unsupplied) == {"A", "B", "X"}, res.unsupplied
    assert res.supplied == ["S"]
    print("ok: 字典序选阀 {E1,E3}")


def test_outage_priority_over_valve_count():
    """第一目标优先：宁可多关一个阀也要少断供。"""
    nodes = make_nodes()
    nodes[2]["households"] = 100  # X 变为 100 户
    res = solve_isolation(nodes, make_edges(), "ER", [])
    assert res.status == STATUS_OPTIMAL, res
    # 关 {E2,E3}：X 保持供水，断供只有 A+B=17；关 {E1,E3} 会断供 X(100)
    assert res.closed_valves == ["E2", "E3"], res.closed_valves
    assert res.outage_households == 17
    assert set(res.unsupplied) == {"A", "B"}
    print("ok: 断供户数优先于关阀数")


def test_infeasible_must_supply():
    """保供节点只经检修段与网络相连 -> 证明不可行。"""
    res = solve_isolation(make_nodes(), make_edges(), "ER", ["B"])
    assert res.status == STATUS_INFEASIBLE, res
    print("ok: 证明不可行")


def test_island_not_counted_as_supplied():
    """孤岛（无水源连通）不计为供水，其户数计入断供。"""
    nodes = make_nodes() + [{"id": "Z", "type": "user", "households": 50}]
    edges = make_edges() + [{"id": "E9", "u": "Z", "v": "B", "valve": False}]
    res = solve_isolation(nodes, edges, "ER", [])
    assert res.status == STATUS_OPTIMAL
    # Z 只与 B 相连，B 因检修被隔离 -> Z 是孤岛，50 户计入断供
    assert "Z" in res.unsupplied
    assert res.outage_households == 17 + 50
    print("ok: 孤岛不计为供水")


def test_must_supply_forces_valve_pattern():
    """保供约束会改变关阀方案。"""
    nodes = make_nodes()
    nodes.append({"id": "C", "type": "user", "households": 5})
    edges = make_edges() + [
        {"id": "E4", "u": "A", "v": "C", "valve": True},
        {"id": "E5", "u": "S", "v": "C", "valve": True},
    ]
    # C 必须保供：若只关 E5，C 经 A 连到 S，但 A 是检修端点必须断水 -> 不行；
    # 必须关 E4（切断 C-A），保留 E5 让 C 由 S 直供。
    res = solve_isolation(nodes, edges, "ER", ["C"])
    assert res.status == STATUS_OPTIMAL, res
    assert "C" in res.supplied
    assert "E4" in res.closed_valves
    assert "E5" not in res.closed_valves
    print("ok: 保供约束生效")


def test_no_valves_needed():
    """检修段两端本来就不接水源时，无需关阀。"""
    nodes = [
        {"id": "S", "type": "source", "households": 0},
        {"id": "A", "type": "user", "households": 3},
        {"id": "B", "type": "user", "households": 4},
    ]
    edges = [
        {"id": "ER", "u": "A", "v": "B", "valve": True},  # 检修段上的阀门不计入
        {"id": "E1", "u": "S", "v": "A", "valve": False},
    ]
    # 移除 ER 后 A 仍接 S -> 违反隔离；但 ER 自带阀门不算可关阀门，网络无阀可关 -> 不可行
    res = solve_isolation(nodes, edges, "ER", [])
    assert res.status == STATUS_INFEASIBLE, res

    edges2 = [
        {"id": "ER", "u": "A", "v": "B", "valve": False},
        {"id": "E1", "u": "S", "v": "A", "valve": True},
    ]
    res2 = solve_isolation(nodes, edges2, "ER", [])
    assert res2.status == STATUS_OPTIMAL
    assert res2.closed_valves == ["E1"]
    assert res2.outage_households == 7
    print("ok: 检修段自带阀门不计入关阀集合")


def test_connectivity_bfs():
    nodes = make_nodes()
    edges = make_edges()
    supplied = compute_connectivity(nodes, edges, ["E3"], "ER")
    # 关 E3、移除 ER：S-X-A 仍通，B 孤立
    assert supplied == {"S", "X", "A"}
    print("ok: BFS 连通性")


def test_unproven_path():
    """模拟某阶段超时未证明：结果应为 unproven，且方案本身真实可行。"""
    from ortools.sat.python import cp_model
    from app import solver as solver_mod

    original = cp_model.CpSolver.solve
    calls = {"n": 0}

    def fake_solve(self, model, **kwargs):
        calls["n"] += 1
        status = original(self, model, **kwargs)
        if calls["n"] == 2 and status == cp_model.OPTIMAL:
            return cp_model.FEASIBLE  # 假装第二阶段未能证明
        return status

    cp_model.CpSolver.solve = fake_solve
    try:
        res = solver_mod.solve_isolation(make_nodes(), make_edges(), "ER", [])
    finally:
        cp_model.CpSolver.solve = original

    assert res.status == solver_mod.STATUS_UNPROVEN, res.status
    assert res.closed_valves == ["E1", "E3"]
    supplied = compute_connectivity(make_nodes(), make_edges(), res.closed_valves, "ER")
    assert "A" not in supplied and "B" not in supplied
    print("ok: 未证最优路径")


if __name__ == "__main__":
    test_lexicographic_valve_choice()
    test_outage_priority_over_valve_count()
    test_infeasible_must_supply()
    test_island_not_counted_as_supplied()
    test_must_supply_forces_valve_pattern()
    test_no_valves_needed()
    test_connectivity_bfs()
    test_unproven_path()
    print("全部求解器测试通过")
