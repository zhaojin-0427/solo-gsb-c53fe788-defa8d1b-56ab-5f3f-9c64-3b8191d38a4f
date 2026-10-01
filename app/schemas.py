"""请求数据模型与管网合法性校验。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MAX_NODES = 80
MAX_EDGES = 120
MAX_VALVES = 40
MAX_HOUSEHOLDS = 10**12  # 非负整数户数的上限，保证求解器数值安全


class NodeIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    x: float = 0.0
    y: float = 0.0
    type: Literal["source", "user"] = "user"
    households: int = Field(default=0, ge=0, le=MAX_HOUSEHOLDS)


class EdgeIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    u: str = Field(min_length=1, max_length=64)
    v: str = Field(min_length=1, max_length=64)
    valve: bool = False


class ScenarioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    nodes: list[NodeIn] = Field(max_length=MAX_NODES)
    edges: list[EdgeIn] = Field(max_length=MAX_EDGES)


class SolveIn(BaseModel):
    repair_edge_id: str = Field(min_length=1, max_length=64)
    must_supply: list[str] = Field(default_factory=list, max_length=MAX_NODES)


def validate_network(payload: ScenarioIn) -> list[str]:
    """返回错误信息列表，空列表表示合法。非法管网一律拒绝保存。"""
    errors: list[str] = []

    nodes = [n.model_dump() for n in payload.nodes]
    edges = [e.model_dump() for e in payload.edges]

    if not nodes:
        errors.append("管网至少需要一个节点。")
    if len(nodes) > MAX_NODES:
        errors.append(f"节点数 {len(nodes)} 超过上限 {MAX_NODES}。")
    if len(edges) > MAX_EDGES:
        errors.append(f"管段数 {len(edges)} 超过上限 {MAX_EDGES}。")

    node_ids = [n["id"].strip() for n in nodes]
    if any(not nid for nid in node_ids):
        errors.append("节点 ID 不能为空或纯空白。")
    dup_nodes = sorted({nid for nid in node_ids if node_ids.count(nid) > 1})
    if dup_nodes:
        errors.append(f"节点 ID 重复：{'、'.join(dup_nodes)}。")

    edge_ids = [e["id"].strip() for e in edges]
    if any(not eid for eid in edge_ids):
        errors.append("管段 ID 不能为空或纯空白。")
    dup_edges = sorted({eid for eid in edge_ids if edge_ids.count(eid) > 1})
    if dup_edges:
        errors.append(f"管段 ID 重复：{'、'.join(dup_edges)}。")

    node_id_set = set(node_ids)
    for e in edges:
        if e["u"] == e["v"]:
            errors.append(f"管段 {e['id']} 的两个端点相同（不允许自环）。")
        for ep in (e["u"], e["v"]):
            if ep not in node_id_set:
                errors.append(f"管段 {e['id']} 的端点 {ep} 不存在。")

    valve_count = sum(1 for e in edges if e["valve"])
    if valve_count > MAX_VALVES:
        errors.append(f"可关闭阀门数 {valve_count} 超过上限 {MAX_VALVES}。")

    for n in nodes:
        h = n["households"]
        if not isinstance(h, int) or h < 0:
            errors.append(f"节点 {n['id']} 的户数必须是非负整数。")

    return errors
