"""基于 OR-Tools CP-SAT 的供水检修隔离方案求解器。

判定语义（关闭阀门后，按剩余管段的真实连通性）：
- 检修段被整体移除，其两端节点不得接通任何水源；
- 保供节点必须接通至少一个水源；
- 与任何水源都不连通的孤岛一律记为断供，不计为供水。

优化目标（字典序）：
1. 断供总户数最小；
2. 关闭阀门数量最小；
3. 关闭阀门 ID 升序列表字典序最小。

求解预算 10 秒：
- 三个阶段全部证明最优           -> optimal   （最优）
- 有可行解但未能在预算内证明最优 -> unproven  （未证最优）
- 超时且没有任何可行解           -> not_found （未找到）
- 第一阶段即证明不可行           -> infeasible（无解）
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from ortools.sat.python import cp_model

TIME_LIMIT_SECONDS = 10.0

STATUS_OPTIMAL = "optimal"
STATUS_UNPROVEN = "unproven"
STATUS_NOT_FOUND = "not_found"
STATUS_INFEASIBLE = "infeasible"

_NATURAL_RE = re.compile(r"(\d+)")


def natural_key(s: str):
    """ID 升序的自然序比较键：数字段按数值、其余按字符（E2 < E10）。"""
    return tuple((0, int(t)) if t.isdigit() else (1, t) for t in _NATURAL_RE.split(s))


@dataclass
class SolveResult:
    status: str
    closed_valves: list[str] = field(default_factory=list)
    supplied: list[str] = field(default_factory=list)
    unsupplied: list[str] = field(default_factory=list)
    outage_households: int = 0
    valve_count: int = 0
    solve_time_ms: int = 0
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "closed_valves": self.closed_valves,
            "supplied": self.supplied,
            "unsupplied": self.unsupplied,
            "outage_households": self.outage_households,
            "valve_count": self.valve_count,
            "solve_time_ms": self.solve_time_ms,
            "message": self.message,
        }


def compute_connectivity(nodes: list[dict], edges: list[dict],
                         closed_edge_ids, repair_edge_id: str) -> set[str]:
    """移除检修段与已关阀门管段后，从全部水源出发 BFS，返回真实供水节点集合。"""
    adjacency: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    blocked = set(closed_edge_ids) | {repair_edge_id}
    for e in edges:
        if e["id"] in blocked:
            continue
        adjacency[e["u"]].append(e["v"])
        adjacency[e["v"]].append(e["u"])
    supplied: set[str] = set()
    stack = [n["id"] for n in nodes if n.get("type") == "source"]
    while stack:
        cur = stack.pop()
        if cur in supplied:
            continue
        supplied.add(cur)
        stack.extend(adjacency[cur])
    return supplied


def solve_isolation(nodes: list[dict], edges: list[dict], repair_edge_id: str,
                    must_supply_ids: list[str],
                    time_limit: float = TIME_LIMIT_SECONDS) -> SolveResult:
    started = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    def remaining() -> float:
        return max(time_limit - (time.monotonic() - started), 0.0)

    node_ids = [n["id"] for n in nodes]
    households = {n["id"]: int(n.get("households", 0)) for n in nodes}
    sources = {n["id"] for n in nodes if n.get("type") == "source"}
    must_supply = list(dict.fromkeys(must_supply_ids))

    repair_edge = next(e for e in edges if e["id"] == repair_edge_id)
    active_edges = [e for e in edges if e["id"] != repair_edge_id]
    valve_edges = [e for e in active_edges if e.get("valve")]
    valve_ids = sorted((e["id"] for e in valve_edges), key=natural_key)  # 阀门 ID 升序（自然序）

    model = cp_model.CpModel()
    n_nodes = max(len(node_ids), 1)

    # reach[n]=1 当且仅当 n 与某个水源连通，两个方向缺一不可：
    # (1) 连通 => 可达：沿未关闭管段传播（下面的 >= 约束）；
    # (2) 可达 => 连通：流量只能从水源发出，每个可达非水源节点净消耗 1 单位
    #     流量，且流量只能经过未关闭的管段（防止把孤岛伪报为供水）。
    reach = {nid: model.new_bool_var(f"reach_{i}") for i, nid in enumerate(node_ids)}
    open_var = {e["id"]: model.new_bool_var(f"open_{i}") for i, e in enumerate(valve_edges)}

    inflow: dict[str, list] = {nid: [] for nid in node_ids}
    outflow: dict[str, list] = {nid: [] for nid in node_ids}
    for i, e in enumerate(active_edges):
        f_uv = model.new_int_var(0, n_nodes, f"f_{i}_a")
        f_vu = model.new_int_var(0, n_nodes, f"f_{i}_b")
        inflow[e["v"]].append(f_uv)
        outflow[e["u"]].append(f_uv)
        inflow[e["u"]].append(f_vu)
        outflow[e["v"]].append(f_vu)
        ov = open_var.get(e["id"])
        if ov is not None:
            model.add(f_uv <= n_nodes * ov)
            model.add(f_vu <= n_nodes * ov)
            # 阀门打开时可达性沿管段双向传播；关闭时不传播
            model.add(reach[e["v"]] >= reach[e["u"]] - (1 - ov))
            model.add(reach[e["u"]] >= reach[e["v"]] - (1 - ov))
        else:
            # 无阀管段始终连通，两端可达性一致
            model.add(reach[e["u"]] == reach[e["v"]])
    for nid in node_ids:
        generation = n_nodes if nid in sources else 0
        model.add(sum(inflow[nid]) - sum(outflow[nid]) >= reach[nid] - generation)
    for nid in sources:
        model.add(reach[nid] == 1)

    # 检修段两端不得接通任何水源
    model.add(reach[repair_edge["u"]] == 0)
    model.add(reach[repair_edge["v"]] == 0)
    # 保供节点必须接通至少一个水源
    for nid in must_supply:
        model.add(reach[nid] == 1)

    outage_expr = cp_model.LinearExpr.sum(
        [households[nid] * (1 - reach[nid]) for nid in node_ids if households[nid] > 0])
    open_sum = cp_model.LinearExpr.sum([open_var[v] for v in valve_ids])

    def run_stage():
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max(remaining(), 0.001)
        status = solver.solve(model)
        return solver, status

    proven = True
    best_closed: list[str] | None = None

    # —— 阶段 1：最小化断供户数 ——
    model.minimize(outage_expr)
    solver, status = run_stage()
    if status == cp_model.INFEASIBLE:
        return SolveResult(
            status=STATUS_INFEASIBLE,
            solve_time_ms=elapsed_ms(),
            message="已证明不可行：不存在同时满足检修段隔离与保供要求的关阀方案。",
        )
    if status == cp_model.UNKNOWN:
        return SolveResult(
            status=STATUS_NOT_FOUND,
            solve_time_ms=elapsed_ms(),
            message=f"{int(time_limit)} 秒内未找到可行解（也未证明不可行）。",
        )
    if status != cp_model.OPTIMAL:
        proven = False
    best_closed = [v for v in valve_ids if solver.value(open_var[v]) == 0]
    outage_val = sum(households[nid] for nid in node_ids if solver.value(reach[nid]) == 0)
    model.add(outage_expr == outage_val)

    # —— 阶段 2：在断供户数不变的前提下，最小化关闭阀门数 ——
    if valve_ids:
        if remaining() > 0.01:
            model.minimize(len(valve_ids) - open_sum)
            solver, status = run_stage()
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                best_closed = [v for v in valve_ids if solver.value(open_var[v]) == 0]
                model.add(open_sum == len(valve_ids) - len(best_closed))
                if status != cp_model.OPTIMAL:
                    proven = False
            else:
                proven = False
        else:
            proven = False

        # —— 阶段 3：在前两项不变的前提下，阀门 ID 升序列表字典序最小 ——
        # 等长升序列表的字典序最小化 等价于 按 ID 升序最大化“是否关闭”的 0/1 向量，
        # 用 2 的幂作权重即可一次性求解（阀门数 <= 40，权重和在 int64 范围内）。
        if remaining() > 0.01:
            m = len(valve_ids)
            weights = [1 << (m - 1 - r) for r in range(m)]
            model.minimize(cp_model.LinearExpr.weighted_sum(
                [open_var[v] for v in valve_ids], weights))
            solver, status = run_stage()
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                best_closed = [v for v in valve_ids if solver.value(open_var[v]) == 0]
                if status != cp_model.OPTIMAL:
                    proven = False
            else:
                proven = False
        else:
            proven = False

    # 用真实连通性（BFS）复核最终方案，保证展示与目标值完全准确
    assert best_closed is not None
    supplied = compute_connectivity(nodes, edges, best_closed, repair_edge_id)
    unsupplied = [nid for nid in node_ids if nid not in supplied]
    outage = sum(households[nid] for nid in unsupplied)

    if proven:
        status_str = STATUS_OPTIMAL
        message = f"已在 {elapsed_ms() / 1000:.2f} 秒内证明最优。"
    else:
        status_str = STATUS_UNPROVEN
        message = f"{int(time_limit)} 秒内找到可行解，但未能证明最优。"

    return SolveResult(
        status=status_str,
        closed_valves=sorted(best_closed, key=natural_key),
        supplied=[nid for nid in node_ids if nid in supplied],
        unsupplied=unsupplied,
        outage_households=outage,
        valve_count=len(best_closed),
        solve_time_ms=elapsed_ms(),
        message=message,
    )
