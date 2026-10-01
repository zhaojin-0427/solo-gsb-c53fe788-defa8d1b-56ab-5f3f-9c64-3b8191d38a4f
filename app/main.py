"""供水检修隔离方案台 —— FastAPI 入口。

API 一览：
- GET    /api/scenarios              场景列表
- POST   /api/scenarios              新建场景（校验管网，非法则 422）
- GET    /api/scenarios/{id}         场景详情 + 最新方案
- PUT    /api/scenarios/{id}         更新场景（旧方案作废）
- DELETE /api/scenarios/{id}         删除场景及其方案
- POST   /api/scenarios/{id}/solve   求解检修隔离方案并保存
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db
from .schemas import ScenarioIn, SolveIn, validate_network
from .solver import solve_isolation

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="供水检修隔离方案台", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(_, exc: RequestValidationError):
    """把 pydantic 校验错误转成可读的中文提示列表。"""
    msgs = []
    for err in exc.errors():
        loc = " / ".join(str(x) for x in err["loc"] if x != "body")
        msgs.append(f"字段 {loc}：{err['msg']}" if loc else err["msg"])
    return JSONResponse(status_code=422, content={"detail": msgs})


@app.get("/api/scenarios")
def list_scenarios() -> list[dict]:
    return db.list_scenarios()


@app.post("/api/scenarios", status_code=201)
def create_scenario(payload: ScenarioIn) -> dict:
    errors = validate_network(payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    nodes = [n.model_dump() for n in payload.nodes]
    edges = [e.model_dump() for e in payload.edges]
    scenario_id = db.create_scenario(payload.name, nodes, edges)
    return {"id": scenario_id}


@app.get("/api/scenarios/{scenario_id}")
def get_scenario(scenario_id: int) -> dict:
    scenario = db.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="场景不存在。")
    scenario["solution"] = db.latest_solution(scenario_id)
    return scenario


@app.put("/api/scenarios/{scenario_id}")
def update_scenario(scenario_id: int, payload: ScenarioIn) -> dict:
    errors = validate_network(payload)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    nodes = [n.model_dump() for n in payload.nodes]
    edges = [e.model_dump() for e in payload.edges]
    if not db.update_scenario(scenario_id, payload.name, nodes, edges):
        raise HTTPException(status_code=404, detail="场景不存在。")
    return {"ok": True}


@app.delete("/api/scenarios/{scenario_id}")
def delete_scenario(scenario_id: int) -> dict:
    if not db.delete_scenario(scenario_id):
        raise HTTPException(status_code=404, detail="场景不存在。")
    return {"ok": True}


@app.post("/api/scenarios/{scenario_id}/solve", status_code=201)
def solve_scenario(scenario_id: int, payload: SolveIn) -> dict:
    scenario = db.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="场景不存在。")
    nodes, edges = scenario["nodes"], scenario["edges"]

    edge_ids = {e["id"] for e in edges}
    if payload.repair_edge_id not in edge_ids:
        raise HTTPException(
            status_code=422,
            detail=f"待检修管段 {payload.repair_edge_id} 不存在于该场景中。",
        )
    node_ids = {n["id"] for n in nodes}
    must_supply = list(dict.fromkeys(payload.must_supply))
    missing = [m for m in must_supply if m not in node_ids]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"保供节点不存在：{'、'.join(missing)}。",
        )

    result = solve_isolation(nodes, edges, payload.repair_edge_id, must_supply)
    return db.save_solution(scenario_id, payload.repair_edge_id, must_supply, result)


# 静态页面（画布前端），放在 API 路由之后挂载
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
