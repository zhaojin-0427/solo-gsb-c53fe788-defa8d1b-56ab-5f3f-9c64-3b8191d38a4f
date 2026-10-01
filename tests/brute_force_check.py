"""随机小网络暴力对拍：python3 tests/brute_force_check.py [轮数]"""
import itertools
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.solver import STATUS_INFEASIBLE, STATUS_OPTIMAL, compute_connectivity, natural_key, solve_isolation  # noqa: E402


def brute_force(nodes, edges, repair_edge_id, must_supply):
    """枚举所有关阀子集，返回字典序最优 (断供户数, 关阀数, 升序ID列表) 或 None。"""
    repair = next(e for e in edges if e["id"] == repair_edge_id)
    valves = sorted((e["id"] for e in edges if e["valve"] and e["id"] != repair_edge_id),
                    key=natural_key)
    households = {n["id"]: int(n.get("households", 0)) for n in nodes}
    best = None
    for r in range(len(valves) + 1):
        for combo in itertools.combinations(valves, r):
            closed = set(combo)
            supplied = compute_connectivity(nodes, edges, closed, repair_edge_id)
            if repair["u"] in supplied or repair["v"] in supplied:
                continue
            if any(m not in supplied for m in must_supply):
                continue
            outage = sum(households[n["id"]] for n in nodes if n["id"] not in supplied)
            key = (outage, len(combo), list(combo))
            if best is None or key < best:
                best = key
    return best


def random_case(rng):
    n_nodes = rng.randint(3, 7)
    ids = [f"N{i}" for i in range(n_nodes)]
    nodes = []
    for i, nid in enumerate(ids):
        is_source = i < rng.randint(1, 2)
        nodes.append({
            "id": nid,
            "type": "source" if is_source else "user",
            "households": 0 if is_source else rng.randint(0, 30),
        })
    edges = []
    eid = 0
    for i in range(n_nodes):
        for j in range(i + 1, n_nodes):
            if rng.random() < 0.45:
                eid += 1
                edges.append({"id": f"E{eid}", "u": ids[i], "v": ids[j],
                              "valve": rng.random() < 0.5})
    if not edges:
        return None
    repair = rng.choice(edges)["id"]
    must = [n["id"] for n in nodes if n["type"] == "user" and rng.random() < 0.3]
    return nodes, edges, repair, must


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    rng = random.Random(20260930)
    checked = 0
    for t in range(rounds):
        case = random_case(rng)
        if case is None:
            continue
        nodes, edges, repair, must = case
        expected = brute_force(nodes, edges, repair, must)
        res = solve_isolation(nodes, edges, repair, must, time_limit=5.0)
        if expected is None:
            assert res.status == STATUS_INFEASIBLE, (case, res.status, res.closed_valves)
        else:
            assert res.status == STATUS_OPTIMAL, (case, res.status)
            got = (res.outage_households, res.valve_count, res.closed_valves)
            assert got == expected, (case, "expected", expected, "got", got)
            # 复核展示的连通性与目标值
            supplied = compute_connectivity(nodes, edges, res.closed_valves, repair)
            assert set(res.supplied) == supplied
            assert set(res.unsupplied) == {n["id"] for n in nodes} - supplied
        checked += 1
    print(f"对拍通过：{checked} 个随机用例与暴力枚举结果完全一致")


if __name__ == "__main__":
    main()
