"use strict";

/* ================= 状态 ================= */
const NODE_R = 15;
const MAX_NODES = 80, MAX_EDGES = 120, MAX_VALVES = 40;

const state = {
  scenarioId: null,
  nodes: [],            // {id, x, y, type: 'source'|'user', households}
  edges: [],            // {id, u, v, valve}
  tool: "select",
  selected: null,       // {kind: 'node'|'edge', id}
  edgeStart: null,      // 添加管段时的第一个端点
  repairEdgeId: null,   // 待检修管段
  mustSupply: new Set(),// 保供节点
  solution: null,       // 最近一次求解结果
  dragging: null,
  scenarios: [],
};

const canvas = document.getElementById("canvas");
const ctx = canvas.getContext("2d");
const hintEl = document.getElementById("hint");
const propBody = document.getElementById("propBody");
const resultBody = document.getElementById("resultBody");
const repairInfoEl = document.getElementById("repairInfo");
const scenarioListEl = document.getElementById("scenarioList");
const scenarioNameEl = document.getElementById("scenarioName");
const scenarioMetaEl = document.getElementById("scenarioMeta");
const solveBtn = document.getElementById("solveBtn");

const TOOL_HINTS = {
  select: "点击选择节点或管段；拖动可移动节点。",
  addSource: "点击画布空白处添加水源。",
  addUser: "点击画布空白处添加用水节点（默认 100 户，可在属性面板修改）。",
  addEdge: "依次点击两个节点，创建一条管段。",
  delete: "点击节点或管段将其删除（删除节点会连同其管段一起删除）。",
};

/* ================= 工具函数 ================= */
function findNode(id) { return state.nodes.find(n => n.id === id); }
function findEdge(id) { return state.edges.find(e => e.id === id); }

function autoId(prefix, taken) {
  let i = 1;
  while (taken.has(prefix + i)) i++;
  return prefix + i;
}
function nextNodeId() { return autoId("N", new Set(state.nodes.map(n => n.id))); }
function nextEdgeId() { return autoId("E", new Set(state.edges.map(e => e.id))); }

function pos(evt) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: (evt.clientX - rect.left) * (canvas.width / rect.width),
    y: (evt.clientY - rect.top) * (canvas.height / rect.height),
  };
}

function nodeAt(p) {
  for (let i = state.nodes.length - 1; i >= 0; i--) {
    const n = state.nodes[i];
    if (Math.hypot(n.x - p.x, n.y - p.y) <= NODE_R + 3) return n;
  }
  return null;
}

function distToSegment(p, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  let t = len2 ? ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

function edgeAt(p) {
  for (let i = state.edges.length - 1; i >= 0; i--) {
    const e = state.edges[i];
    const u = findNode(e.u), v = findNode(e.v);
    if (u && v && distToSegment(p, u, v) <= 7) return e;
  }
  return null;
}

/** 结构性修改后调用：旧方案失效 */
function touch() {
  state.solution = null;
  renderResult();
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = Array.isArray(j.detail) ? j.detail.join("\n") : (j.detail || detail);
    } catch (_) { /* ignore */ }
    throw new Error(detail);
  }
  return res.json();
}

/* ================= 画布绘制 ================= */
function draw() {
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // 网格
  ctx.strokeStyle = "#f0f4f8";
  ctx.lineWidth = 1;
  for (let x = 40; x < canvas.width; x += 40) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
  }
  for (let y = 40; y < canvas.height; y += 40) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
  }

  const closed = new Set(state.solution ? state.solution.closed_valves : []);

  // 管段
  for (const e of state.edges) {
    const u = findNode(e.u), v = findNode(e.v);
    if (!u || !v) continue;
    const isRepair = e.id === state.repairEdgeId;
    const isSelected = state.selected && state.selected.kind === "edge" && state.selected.id === e.id;

    ctx.beginPath();
    ctx.moveTo(u.x, u.y);
    ctx.lineTo(v.x, v.y);
    if (isRepair) {
      ctx.strokeStyle = "#ef6c00";
      ctx.lineWidth = 4;
      ctx.setLineDash([9, 6]);
    } else if (isSelected) {
      ctx.strokeStyle = "#1565c0";
      ctx.lineWidth = 4;
      ctx.setLineDash([]);
    } else {
      ctx.strokeStyle = "#90a4ae";
      ctx.lineWidth = 3;
      ctx.setLineDash([]);
    }
    ctx.stroke();
    ctx.setLineDash([]);

    const mx = (u.x + v.x) / 2, my = (u.y + v.y) / 2;

    // 阀门标记
    if (e.valve) {
      const isClosed = closed.has(e.id);
      ctx.save();
      ctx.translate(mx, my);
      ctx.rotate(Math.PI / 4);
      ctx.fillStyle = isClosed ? "#e53935" : "#ffffff";
      ctx.strokeStyle = isClosed ? "#b71c1c" : "#37474f";
      ctx.lineWidth = 2;
      ctx.fillRect(-8, -8, 16, 16);
      ctx.strokeRect(-8, -8, 16, 16);
      ctx.restore();
      if (isClosed) {
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2.5;
        ctx.beginPath();
        ctx.moveTo(mx - 4.5, my - 4.5); ctx.lineTo(mx + 4.5, my + 4.5);
        ctx.moveTo(mx + 4.5, my - 4.5); ctx.lineTo(mx - 4.5, my + 4.5);
        ctx.stroke();
      }
    }

    // 管段 ID 标签
    drawTag(e.id + (isRepair ? "（检修）" : ""), mx, my - 12, isRepair ? "#ef6c00" : "#546e7a");
  }

  // 添加管段时的起点高亮
  if (state.edgeStart) {
    const n = findNode(state.edgeStart);
    if (n) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, NODE_R + 5, 0, Math.PI * 2);
      ctx.strokeStyle = "#1565c0";
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }
  }

  // 节点
  const supplied = new Set(state.solution ? state.solution.supplied : []);
  const unsupplied = new Set(state.solution ? state.solution.unsupplied : []);
  for (const n of state.nodes) {
    let fill;
    if (n.type === "source") fill = "#1e88e5";
    else if (supplied.has(n.id)) fill = "#43a047";
    else if (unsupplied.has(n.id)) fill = "#e53935";
    else fill = "#90a4ae";

    // 保供节点：橙色外环
    if (state.mustSupply.has(n.id)) {
      ctx.beginPath();
      ctx.arc(n.x, n.y, NODE_R + 4, 0, Math.PI * 2);
      ctx.strokeStyle = "#ff8f00";
      ctx.lineWidth = 3;
      ctx.stroke();
    }

    ctx.beginPath();
    ctx.arc(n.x, n.y, NODE_R, 0, Math.PI * 2);
    ctx.fillStyle = fill;
    ctx.fill();
    const isSelected = state.selected && state.selected.kind === "node" && state.selected.id === n.id;
    ctx.strokeStyle = isSelected ? "#0d47a1" : "#ffffff";
    ctx.lineWidth = isSelected ? 3 : 2;
    ctx.stroke();

    // 节点内文字：水源“源”，用水节点显示户数
    ctx.fillStyle = "#ffffff";
    ctx.font = "bold 11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(n.type === "source" ? "源" : String(n.households), n.x, n.y);

    // ID 标签
    drawTag(n.id + (state.mustSupply.has(n.id) ? " ★保供" : ""), n.x, n.y + NODE_R + 11,
      state.mustSupply.has(n.id) ? "#ef6c00" : "#37474f");
  }
}

function drawTag(text, x, y, color) {
  ctx.font = "11px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const w = ctx.measureText(text).width + 8;
  ctx.fillStyle = "rgba(255,255,255,0.85)";
  ctx.fillRect(x - w / 2, y - 8, w, 16);
  ctx.fillStyle = color;
  ctx.fillText(text, x, y);
}

/* ================= 鼠标交互 ================= */
canvas.addEventListener("mousedown", (evt) => {
  const p = pos(evt);

  if (state.tool === "addSource" || state.tool === "addUser") {
    if (state.nodes.length >= MAX_NODES) { alert(`节点数已达上限 ${MAX_NODES}`); return; }
    if (nodeAt(p)) return;
    const type = state.tool === "addSource" ? "source" : "user";
    state.nodes.push({
      id: nextNodeId(),
      x: Math.round(p.x), y: Math.round(p.y),
      type, households: type === "user" ? 100 : 0,
    });
    touch(); draw();
    return;
  }

  if (state.tool === "addEdge") {
    const n = nodeAt(p);
    if (!n) { state.edgeStart = null; draw(); return; }
    if (!state.edgeStart) { state.edgeStart = n.id; draw(); return; }
    if (state.edgeStart === n.id) return;
    if (state.edges.length >= MAX_EDGES) { alert(`管段数已达上限 ${MAX_EDGES}`); state.edgeStart = null; draw(); return; }
    state.edges.push({ id: nextEdgeId(), u: state.edgeStart, v: n.id, valve: false });
    state.edgeStart = null;
    touch(); draw();
    return;
  }

  if (state.tool === "delete") {
    const n = nodeAt(p);
    if (n) { deleteNode(n.id); return; }
    const e = edgeAt(p);
    if (e) deleteEdge(e.id);
    return;
  }

  // select
  const n = nodeAt(p);
  if (n) {
    state.selected = { kind: "node", id: n.id };
    state.dragging = { id: n.id, dx: n.x - p.x, dy: n.y - p.y };
  } else {
    const e = edgeAt(p);
    state.selected = e ? { kind: "edge", id: e.id } : null;
  }
  draw(); renderProps();
});

canvas.addEventListener("mousemove", (evt) => {
  if (!state.dragging) return;
  const p = pos(evt);
  const n = findNode(state.dragging.id);
  if (!n) return;
  n.x = Math.round(Math.max(NODE_R, Math.min(canvas.width - NODE_R, p.x + state.dragging.dx)));
  n.y = Math.round(Math.max(NODE_R, Math.min(canvas.height - NODE_R, p.y + state.dragging.dy)));
  draw(); // 仅移动位置，不影响已求解方案
});

window.addEventListener("mouseup", () => { state.dragging = null; });

/* ================= 结构修改 ================= */
function deleteNode(id) {
  state.nodes = state.nodes.filter(n => n.id !== id);
  const removedEdges = state.edges.filter(e => e.u === id || e.v === id).map(e => e.id);
  state.edges = state.edges.filter(e => e.u !== id && e.v !== id);
  state.mustSupply.delete(id);
  if (removedEdges.includes(state.repairEdgeId)) state.repairEdgeId = null;
  if (state.selected && state.selected.kind === "node" && state.selected.id === id) state.selected = null;
  if (state.selected && state.selected.kind === "edge" && removedEdges.includes(state.selected.id)) state.selected = null;
  if (state.edgeStart === id) state.edgeStart = null;
  touch(); draw(); renderProps();
}

function deleteEdge(id) {
  state.edges = state.edges.filter(e => e.id !== id);
  if (state.repairEdgeId === id) state.repairEdgeId = null;
  if (state.selected && state.selected.kind === "edge" && state.selected.id === id) state.selected = null;
  touch(); draw(); renderProps();
}

function renameNode(oldId, newId) {
  const n = findNode(oldId);
  if (!n) return false;
  newId = newId.trim();
  if (!newId) { alert("节点 ID 不能为空"); return false; }
  if (newId !== oldId && findNode(newId)) { alert(`节点 ID ${newId} 已存在`); return false; }
  n.id = newId;
  for (const e of state.edges) {
    if (e.u === oldId) e.u = newId;
    if (e.v === oldId) e.v = newId;
  }
  if (state.mustSupply.has(oldId)) { state.mustSupply.delete(oldId); state.mustSupply.add(newId); }
  if (state.edgeStart === oldId) state.edgeStart = newId;
  state.selected = { kind: "node", id: newId };
  touch();
  return true;
}

function renameEdge(oldId, newId) {
  const e = findEdge(oldId);
  if (!e) return false;
  newId = newId.trim();
  if (!newId) { alert("管段 ID 不能为空"); return false; }
  if (newId !== oldId && findEdge(newId)) { alert(`管段 ID ${newId} 已存在`); return false; }
  e.id = newId;
  if (state.repairEdgeId === oldId) state.repairEdgeId = newId;
  state.selected = { kind: "edge", id: newId };
  touch();
  return true;
}

/* ================= 属性面板 ================= */
function renderProps() {
  const sel = state.selected;
  if (!sel) {
    propBody.innerHTML = '<p class="muted">未选中对象。点击画布中的节点或管段查看、编辑属性。</p>';
    updateRepairInfo();
    return;
  }

  if (sel.kind === "node") {
    const n = findNode(sel.id);
    if (!n) { state.selected = null; renderProps(); return; }
    propBody.innerHTML = `
      <label class="field"><span>节点 ID</span><input type="text" id="pNodeId" value="${escapeHtml(n.id)}" maxlength="64"></label>
      <label class="field"><span>类型</span>
        <select id="pNodeType">
          <option value="user" ${n.type === "user" ? "selected" : ""}>用水节点</option>
          <option value="source" ${n.type === "source" ? "selected" : ""}>水源</option>
        </select></label>
      <label class="field"><span>户数（非负整数）</span>
        <input type="number" id="pNodeHouseholds" min="0" step="1" value="${n.households}" ${n.type === "source" ? "disabled" : ""}></label>
      <label class="check"><input type="checkbox" id="pNodeMust" ${state.mustSupply.has(n.id) ? "checked" : ""}> 必须保供</label>
      <button id="pNodeDelete" class="danger">删除节点</button>`;

    document.getElementById("pNodeId").addEventListener("change", (ev) => {
      if (!renameNode(n.id, ev.target.value)) ev.target.value = n.id;
      draw(); renderProps();
    });
    document.getElementById("pNodeType").addEventListener("change", (ev) => {
      n.type = ev.target.value;
      if (n.type === "source") n.households = 0;
      touch(); draw(); renderProps();
    });
    document.getElementById("pNodeHouseholds").addEventListener("change", (ev) => {
      const v = Math.floor(Number(ev.target.value));
      if (!Number.isFinite(v) || v < 0) { alert("户数必须是非负整数"); ev.target.value = n.households; return; }
      n.households = v;
      touch(); draw();
    });
    document.getElementById("pNodeMust").addEventListener("change", (ev) => {
      if (ev.target.checked) state.mustSupply.add(n.id); else state.mustSupply.delete(n.id);
      touch(); draw(); updateRepairInfo();
    });
    document.getElementById("pNodeDelete").addEventListener("click", () => deleteNode(n.id));
  } else {
    const e = findEdge(sel.id);
    if (!e) { state.selected = null; renderProps(); return; }
    propBody.innerHTML = `
      <label class="field"><span>管段 ID</span><input type="text" id="pEdgeId" value="${escapeHtml(e.id)}" maxlength="64"></label>
      <p class="small muted">端点：${escapeHtml(e.u)} ↔ ${escapeHtml(e.v)}</p>
      <label class="check"><input type="checkbox" id="pEdgeValve" ${e.valve ? "checked" : ""}> 可关闭阀门</label>
      <label class="check"><input type="checkbox" id="pEdgeRepair" ${state.repairEdgeId === e.id ? "checked" : ""}> 待检修管段</label>
      <button id="pEdgeDelete" class="danger">删除管段</button>`;

    document.getElementById("pEdgeId").addEventListener("change", (ev) => {
      if (!renameEdge(e.id, ev.target.value)) ev.target.value = e.id;
      draw(); renderProps();
    });
    document.getElementById("pEdgeValve").addEventListener("change", (ev) => {
      const count = state.edges.filter(x => x.valve).length;
      if (ev.target.checked && count >= MAX_VALVES) {
        alert(`阀门数已达上限 ${MAX_VALVES}`);
        ev.target.checked = false;
        return;
      }
      e.valve = ev.target.checked;
      touch(); draw();
    });
    document.getElementById("pEdgeRepair").addEventListener("change", (ev) => {
      state.repairEdgeId = ev.target.checked ? e.id : (state.repairEdgeId === e.id ? null : state.repairEdgeId);
      touch(); draw(); renderProps();
    });
    document.getElementById("pEdgeDelete").addEventListener("click", () => deleteEdge(e.id));
  }
  updateRepairInfo();
}

function updateRepairInfo() {
  const ms = [...state.mustSupply].join("、") || "无";
  repairInfoEl.textContent = `检修段：${state.repairEdgeId || "未选择"}；保供节点：${ms}`;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ================= 方案展示 ================= */
const STATUS_VIEW = {
  optimal:   { text: "最优（10 秒内已证明）", cls: "ok" },
  unproven:  { text: "可行（未证明最优）", cls: "warn" },
  not_found: { text: "未找到可行解", cls: "idle" },
  infeasible:{ text: "无解（已证明不可行）", cls: "bad" },
};

function renderResult() {
  const sol = state.solution;
  if (!sol) {
    resultBody.innerHTML = '<p class="muted">尚未求解。</p>';
    return;
  }
  const v = STATUS_VIEW[sol.status] || { text: sol.status, cls: "idle" };
  let html = `<span class="badge ${v.cls}">${v.text}</span>`;
  html += `<dl class="kv">
    <dt>断供户数</dt><dd>${sol.outage_households}</dd>
    <dt>关闭阀门数</dt><dd>${sol.valve_count}</dd>
    <dt>关闭阀门</dt><dd>${sol.closed_valves.length ? escapeHtml(sol.closed_valves.join("、")) : "无"}</dd>
    <dt>供水节点</dt><dd>${sol.supplied.length} 个</dd>
    <dt>断供节点</dt><dd>${sol.unsupplied.length} 个${sol.unsupplied.length ? "（" + escapeHtml(sol.unsupplied.join("、")) + "）" : ""}</dd>
    <dt>求解耗时</dt><dd>${sol.solve_time_ms} ms</dd>
    <dt>说明</dt><dd>${escapeHtml(sol.message || "")}</dd>
  </dl>`;
  resultBody.innerHTML = html;
}

/* ================= 场景管理 ================= */
async function refreshScenarioList() {
  state.scenarios = await api("GET", "/api/scenarios");
  scenarioListEl.innerHTML = "";
  for (const s of state.scenarios) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = `#${s.id} ${s.name}（${s.node_count}节点/${s.edge_count}管段${s.has_solution ? "/有方案" : ""}）`;
    if (s.id === state.scenarioId) opt.selected = true;
    scenarioListEl.appendChild(opt);
  }
}

function clientValidate() {
  const errs = [];
  const nodeIds = state.nodes.map(n => n.id);
  const edgeIds = state.edges.map(e => e.id);
  if (new Set(nodeIds).size !== nodeIds.length) errs.push("节点 ID 存在重复");
  if (new Set(edgeIds).size !== edgeIds.length) errs.push("管段 ID 存在重复");
  if (state.nodes.length > MAX_NODES) errs.push(`节点数超过上限 ${MAX_NODES}`);
  if (state.edges.length > MAX_EDGES) errs.push(`管段数超过上限 ${MAX_EDGES}`);
  if (state.edges.filter(e => e.valve).length > MAX_VALVES) errs.push(`阀门数超过上限 ${MAX_VALVES}`);
  const idSet = new Set(nodeIds);
  for (const e of state.edges) {
    if (!idSet.has(e.u) || !idSet.has(e.v)) errs.push(`管段 ${e.id} 的端点不存在`);
  }
  return errs;
}

async function saveScenario() {
  const errs = clientValidate();
  if (errs.length) { alert("管网不合法：\n" + errs.join("\n")); return false; }
  const payload = {
    name: scenarioNameEl.value.trim() || "未命名场景",
    nodes: state.nodes,
    edges: state.edges,
  };
  try {
    if (state.scenarioId) {
      await api("PUT", `/api/scenarios/${state.scenarioId}`, payload);
    } else {
      const r = await api("POST", "/api/scenarios", payload);
      state.scenarioId = r.id;
    }
    localStorage.setItem("lastScenarioId", String(state.scenarioId));
    await refreshScenarioList();
    updateMeta();
    return true;
  } catch (e) {
    alert("保存失败：\n" + e.message);
    return false;
  }
}

async function loadScenario(id) {
  const data = await api("GET", `/api/scenarios/${id}`);
  state.scenarioId = data.id;
  state.nodes = data.nodes;
  state.edges = data.edges;
  state.solution = data.solution;
  if (data.solution) {
    state.repairEdgeId = data.solution.repair_edge_id;
    state.mustSupply = new Set(data.solution.must_supply);
  } else {
    state.repairEdgeId = null;
    state.mustSupply = new Set();
  }
  state.selected = null;
  state.edgeStart = null;
  scenarioNameEl.value = data.name;
  localStorage.setItem("lastScenarioId", String(id));
  await refreshScenarioList();
  updateMeta();
  draw(); renderProps(); renderResult();
}

function updateMeta() {
  scenarioMetaEl.textContent = state.scenarioId
    ? `当前场景 #${state.scenarioId}，共 ${state.nodes.length} 节点 / ${state.edges.length} 管段 / ${state.edges.filter(e => e.valve).length} 阀门`
    : "未保存的新场景";
}

function newScenario() {
  state.scenarioId = null;
  state.nodes = [];
  state.edges = [];
  state.selected = null;
  state.edgeStart = null;
  state.repairEdgeId = null;
  state.mustSupply = new Set();
  state.solution = null;
  scenarioNameEl.value = "";
  localStorage.removeItem("lastScenarioId");
  updateMeta();
  draw(); renderProps(); renderResult();
}

/* ================= 示例管网 ================= */
function loadSample() {
  const sample = {
    name: "示例管网",
    nodes: [
      { id: "S1", x: 90, y: 110, type: "source", households: 0 },
      { id: "S2", x: 90, y: 510, type: "source", households: 0 },
      { id: "N1", x: 250, y: 90, type: "user", households: 120 },
      { id: "N2", x: 250, y: 300, type: "user", households: 80 },
      { id: "N3", x: 250, y: 510, type: "user", households: 60 },
      { id: "N4", x: 450, y: 190, type: "user", households: 200 },
      { id: "N5", x: 450, y: 420, type: "user", households: 150 },
      { id: "N6", x: 650, y: 110, type: "user", households: 90 },
      { id: "N7", x: 650, y: 320, type: "user", households: 110 },
      { id: "N8", x: 840, y: 210, type: "user", households: 70 },
    ],
    edges: [
      { id: "E1", u: "S1", v: "N1", valve: false },
      { id: "E2", u: "S2", v: "N3", valve: false },
      { id: "E3", u: "N1", v: "N2", valve: true },
      { id: "E4", u: "N2", v: "N3", valve: true },
      { id: "E5", u: "N1", v: "N4", valve: false },
      { id: "E6", u: "N2", v: "N4", valve: true },
      { id: "E7", u: "N2", v: "N5", valve: false },
      { id: "E8", u: "N3", v: "N5", valve: true },
      { id: "E9", u: "N4", v: "N5", valve: true },
      { id: "E10", u: "N4", v: "N6", valve: false },
      { id: "E11", u: "N5", v: "N7", valve: true },
      { id: "E12", u: "N6", v: "N7", valve: false },
      { id: "E13", u: "N6", v: "N8", valve: true },
      { id: "E14", u: "N7", v: "N8", valve: false },
    ],
  };
  state.scenarioId = null;
  state.nodes = sample.nodes;
  state.edges = sample.edges;
  state.selected = null;
  state.edgeStart = null;
  state.repairEdgeId = "E7";
  state.mustSupply = new Set(["N8"]);
  state.solution = null;
  scenarioNameEl.value = sample.name;
  updateMeta();
  draw(); renderProps(); renderResult();
}

/* ================= 求解 ================= */
async function solve() {
  if (!state.repairEdgeId) {
    alert("请先选择一条待检修管段：\n用“选择 / 移动”工具点击一条管段，在属性面板勾选“待检修管段”。");
    return;
  }
  if (!findEdge(state.repairEdgeId)) {
    alert("待检修管段已不存在，请重新选择。");
    state.repairEdgeId = null;
    renderProps();
    return;
  }
  solveBtn.disabled = true;
  solveBtn.textContent = "求解中…（最长 10 秒）";
  try {
    const saved = await saveScenario();
    if (!saved) return;
    const sol = await api("POST", `/api/scenarios/${state.scenarioId}/solve`, {
      repair_edge_id: state.repairEdgeId,
      must_supply: [...state.mustSupply],
    });
    state.solution = sol;
    renderResult();
    draw();
  } catch (e) {
    alert("求解失败：\n" + e.message);
  } finally {
    solveBtn.disabled = false;
    solveBtn.textContent = "保存并求解";
  }
}

/* ================= 事件绑定与初始化 ================= */
document.getElementById("toolbar").addEventListener("click", (evt) => {
  const btn = evt.target.closest("button.tool");
  if (!btn) return;
  state.tool = btn.dataset.tool;
  state.edgeStart = null;
  document.querySelectorAll("#toolbar .tool").forEach(b => b.classList.toggle("active", b === btn));
  hintEl.textContent = TOOL_HINTS[state.tool];
  draw();
});

document.getElementById("saveScenarioBtn").addEventListener("click", saveScenario);
document.getElementById("newScenarioBtn").addEventListener("click", newScenario);
document.getElementById("loadSampleBtn").addEventListener("click", loadSample);
document.getElementById("loadScenarioBtn").addEventListener("click", async () => {
  const id = Number(scenarioListEl.value);
  if (!id) { alert("没有可加载的场景"); return; }
  try { await loadScenario(id); } catch (e) { alert("加载失败：\n" + e.message); }
});
document.getElementById("deleteScenarioBtn").addEventListener("click", async () => {
  const id = Number(scenarioListEl.value);
  if (!id) { alert("没有可删除的场景"); return; }
  if (!confirm(`确定删除场景 #${id} 及其全部方案？`)) return;
  try {
    await api("DELETE", `/api/scenarios/${id}`);
    if (state.scenarioId === id) newScenario();
    await refreshScenarioList();
  } catch (e) { alert("删除失败：\n" + e.message); }
});
solveBtn.addEventListener("click", solve);

(async function init() {
  hintEl.textContent = TOOL_HINTS.select;
  try {
    await refreshScenarioList();
    const last = Number(localStorage.getItem("lastScenarioId"));
    if (last && state.scenarios.some(s => s.id === last)) {
      await loadScenario(last);
    } else if (state.scenarios.length) {
      await loadScenario(state.scenarios[0].id);
    } else {
      loadSample();
    }
  } catch (e) {
    console.error(e);
    loadSample();
  }
  updateMeta();
  draw(); renderProps(); renderResult();
})();
