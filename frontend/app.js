import {
  USER_NODE_ID,
  applyAgentEvent,
  comparisonRows,
  createInitialState,
  selectNode,
  statusPresentation,
  toggleCompareProduct,
} from "./state.js";

const svgNamespace = "http://www.w3.org/2000/svg";
const elements = {
  form: document.querySelector("#idea-form"),
  idea: document.querySelector("#idea"),
  targetUser: document.querySelector("#target-user"),
  problem: document.querySelector("#problem"),
  status: document.querySelector("#run-status"),
  activities: document.querySelector("#activity-list"),
  candidateCount: document.querySelector("#candidate-count"),
  coverageFill: document.querySelector("#coverage-fill"),
  mapTitle: document.querySelector("#map-title"),
  mapCaption: document.querySelector("#map-caption"),
  emptyMessage: document.querySelector("#empty-message"),
  nodeLayer: document.querySelector("#node-layer"),
  clusterLayer: document.querySelector("#cluster-layer"),
  focusRing: document.querySelector("#focus-ring"),
  focusGlow: document.querySelector("#focus-glow"),
  focusLabel: document.querySelector("#focus-label"),
  detail: document.querySelector("#detail-panel"),
  detailName: document.querySelector("#detail-name"),
  detailRelationship: document.querySelector("#detail-relationship"),
  detailFacts: document.querySelector("#detail-facts"),
  detailSources: document.querySelector("#detail-sources"),
  compareToggle: document.querySelector("#compare-toggle"),
  compareTray: document.querySelector("#compare-tray"),
  compareCount: document.querySelector("#compare-count"),
  compareEmpty: document.querySelector("#compare-empty"),
  compareTableWrap: document.querySelector("#compare-table-wrap"),
  closest: document.querySelector("#closest-rivals"),
  differentiation: document.querySelector("#differentiation"),
  opportunity: document.querySelector("#opportunity"),
};

let state = createInitialState();
let activeRequest = null;
const nodeElements = new Map();
const clusterElements = new Map();

function svgElement(tag, className) {
  const element = document.createElementNS(svgNamespace, tag);
  if (className) element.setAttribute("class", className);
  return element;
}

function mapPoint(node) {
  return { x: 80 + Number(node.x ?? 5) * 84, y: 70 + (10 - Number(node.y ?? 5)) * 56 };
}

function shortLabel(value, length = 25) {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function createNodeElement(nodeId) {
  const group = svgElement("g", "map-node");
  group.dataset.nodeId = nodeId;
  const halo = svgElement("circle", "node-halo");
  halo.setAttribute("r", "31");
  const core = svgElement("circle", "node-core");
  core.setAttribute("r", "7");
  const label = svgElement("text", "node-label");
  label.setAttribute("y", "28");
  const relation = svgElement("text", "node-relation");
  relation.setAttribute("y", "43");
  group.append(halo, core, label, relation);
  group.addEventListener("click", () => {
    const selected = state.nodes[group.dataset.nodeId];
    if (!selected || selected.node_type === "USER_IDEA") return;
    state = selectNode(state, group.dataset.nodeId);
    render();
  });
  return group;
}

function renderNodes() {
  const focusIds = new Set(state.focusRing.map((entry) => entry.product_id));
  const activeIds = new Set(Object.keys(state.nodes));
  for (const [nodeId, group] of nodeElements) {
    if (!activeIds.has(nodeId)) {
      group.remove();
      nodeElements.delete(nodeId);
    }
  }

  for (const [nodeId, node] of Object.entries(state.nodes)) {
    let group = nodeElements.get(nodeId);
    if (!group) {
      group = createNodeElement(nodeId);
      nodeElements.set(nodeId, group);
      elements.nodeLayer.append(group);
    }
    const isUser = node.node_type === "USER_IDEA";
    const isFocus = focusIds.has(node.product_id);
    group.setAttribute(
      "class",
      `map-node ${isUser ? "user" : "product"}${isFocus ? " focus" : ""}${state.selectedNodeId === nodeId ? " selected" : ""}`,
    );
    const point = mapPoint(node);
    group.setAttribute("transform", `translate(${point.x} ${point.y})`);
    group.querySelector(".node-halo").setAttribute("r", isUser ? "44" : "0");
    group.querySelector(".node-core").setAttribute("r", isUser ? "17" : isFocus ? "10" : "7");
    const label = group.querySelector(".node-label");
    const relation = group.querySelector(".node-relation");
    label.textContent = shortLabel(node.label);
    relation.textContent = isFocus ? node.relationship : "";
    if (isUser) {
      label.setAttribute("x", "0");
      label.setAttribute("y", "31");
      label.setAttribute("text-anchor", "middle");
      relation.setAttribute("x", "0");
    } else {
      const horizontal = Math.abs(point.x - 500) >= Math.abs(point.y - 350) * 0.72;
      if (horizontal) {
        const direction = point.x >= 500 ? 1 : -1;
        label.setAttribute("x", String(direction * 17));
        label.setAttribute("y", "2");
        label.setAttribute("text-anchor", direction > 0 ? "start" : "end");
        relation.setAttribute("x", String(direction * 17));
        relation.setAttribute("y", "16");
        relation.setAttribute("text-anchor", direction > 0 ? "start" : "end");
      } else {
        const below = point.y >= 350;
        label.setAttribute("x", "0");
        label.setAttribute("y", below ? "29" : "-18");
        label.setAttribute("text-anchor", "middle");
        relation.setAttribute("x", "0");
        relation.setAttribute("y", below ? "43" : "-31");
        relation.setAttribute("text-anchor", "middle");
      }
    }
    group.setAttribute("role", isUser ? "img" : "button");
    group.setAttribute("aria-label", isUser ? `${node.label}, your product` : `Open ${node.label}`);
  }
}

function renderClusters() {
  const activeIds = new Set(Object.keys(state.clusters));
  for (const [clusterId, label] of clusterElements) {
    if (!activeIds.has(clusterId)) {
      label.remove();
      clusterElements.delete(clusterId);
    }
  }
  for (const [clusterId, cluster] of Object.entries(state.clusters)) {
    if (cluster.centroid_x == null || cluster.centroid_y == null) continue;
    let label = clusterElements.get(clusterId);
    if (!label) {
      label = svgElement("text", "cluster-label");
      clusterElements.set(clusterId, label);
      elements.clusterLayer.append(label);
    }
    const point = mapPoint({ x: cluster.centroid_x, y: cluster.centroid_y });
    label.setAttribute("x", String(point.x));
    label.setAttribute("y", String(Math.max(point.y - 33, 28)));
    label.textContent = shortLabel(cluster.name, 30);
  }
}

function renderFocusRing() {
  const focusNodes = state.focusRing
    .map((entry) => Object.values(state.nodes).find((node) => node.product_id === entry.product_id))
    .filter(Boolean);
  if (!focusNodes.length) {
    for (const element of [elements.focusRing, elements.focusGlow, elements.focusLabel]) {
      element.style.opacity = "0";
    }
    return;
  }
  const radius = Math.min(
    305,
    Math.max(
      112,
      ...focusNodes.map((node) => {
        const point = mapPoint(node);
        return Math.hypot(point.x - 500, point.y - 350) + 34;
      }),
    ),
  );
  elements.focusRing.setAttribute("r", String(radius));
  elements.focusGlow.setAttribute("r", String(radius));
  elements.focusLabel.setAttribute("y", String(350 - radius - 11));
  for (const element of [elements.focusRing, elements.focusGlow, elements.focusLabel]) {
    element.style.opacity = "1";
  }
}

function addFact(label, value) {
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value || "Not yet known";
  elements.detailFacts.append(term, description);
}

function renderDetail() {
  const node = state.nodes[state.selectedNodeId];
  const profile = node?.product_id ? state.profiles[node.product_id] : null;
  elements.detail.classList.toggle("open", Boolean(node));
  elements.detail.setAttribute("aria-hidden", String(!node));
  if (!node) return;
  const facts = profile?.structured_facts || {};
  const semantic = profile?.semantic_analysis || {};
  elements.detailName.textContent = profile?.name || node.label;
  elements.detailRelationship.textContent = `${node.relationship || "UNKNOWN"} · ${Math.round((node.similarity_to_user || 0) * 100)}% feature match`;
  elements.detailFacts.replaceChildren();
  addFact("Category", facts.product_category);
  addFact("Target customer", (facts.target_users || []).join(", "));
  addFact("Primary use case", facts.primary_use_case);
  addFact("Positioning", facts.positioning || semantic.positioning);
  addFact("Main differentiator", (semantic.differentiators || [])[0]);
  addFact("Why it is close", semantic.relevance_to_brief);
  elements.detailSources.replaceChildren();
  for (const source of profile?.source_urls || []) {
    const link = document.createElement("a");
    link.href = source;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = new URL(source).hostname;
    elements.detailSources.append(link);
  }
  const selected = state.compareProductIds.includes(node.product_id);
  elements.compareToggle.textContent = selected ? "Remove from compare" : "Add to compare";
  elements.compareToggle.disabled = !profile || (!selected && state.compareProductIds.length >= 4);
}

function renderInterpretationList(container, items) {
  container.replaceChildren();
  if (!items?.length) {
    const empty = document.createElement("p");
    empty.className = "placeholder";
    empty.textContent = "Insights will appear as the map develops.";
    container.append(empty);
    return;
  }
  const list = document.createElement("ul");
  for (const item of items.slice(0, 3)) {
    const row = document.createElement("li");
    row.textContent = item;
    list.append(row);
  }
  container.append(list);
}

function renderComparison() {
  const rows = comparisonRows(state);
  elements.compareCount.textContent = String(rows.length);
  elements.compareTray.classList.toggle("open", rows.length > 0);
  elements.compareEmpty.hidden = rows.length >= 2;
  elements.compareEmpty.textContent = rows.length
    ? "Add one more product to compare."
    : "Open a product and add 2–4 nodes to compare.";
  elements.compareTableWrap.replaceChildren();
  if (rows.length < 2) return;

  const dimensions = [
    ["Target customer", "targetCustomer"],
    ["Workflow", "workflow"],
    ["Capabilities", "capabilities"],
    ["Positioning", "positioning"],
    ["Pricing signal", "pricing"],
    ["Main overlap", "overlap"],
    ["Main differentiation", "differentiation"],
    ["Takeaway", "takeaway"],
  ];
  const table = document.createElement("table");
  table.className = "compare-table";
  const head = document.createElement("tr");
  head.append(document.createElement("th"));
  for (const row of rows) {
    const heading = document.createElement("th");
    heading.textContent = row.name;
    head.append(heading);
  }
  table.append(head);
  for (const [label, key] of dimensions) {
    const line = document.createElement("tr");
    const heading = document.createElement("th");
    heading.textContent = label;
    line.append(heading);
    for (const row of rows) {
      const cell = document.createElement("td");
      cell.textContent = row[key];
      line.append(cell);
    }
    table.append(line);
  }
  elements.compareTableWrap.append(table);
}

function render() {
  const status = statusPresentation(state);
  elements.status.textContent = status.label;
  elements.status.dataset.tone = status.tone;
  elements.activities.replaceChildren();
  for (const activity of state.activities) {
    const item = document.createElement("li");
    item.textContent = activity;
    elements.activities.append(item);
  }
  const count = state.researchSummary?.passed ?? Object.keys(state.profiles).length;
  elements.candidateCount.textContent = String(count);
  elements.coverageFill.style.width = `${Math.min(100, count * 14)}%`;
  elements.mapTitle.textContent = state.idea;
  elements.mapCaption.textContent = state.focusRing.length
    ? `${state.focusRing.length} products currently define your closest competitive set.`
    : "The center is fixed. Validated competitors will appear around your idea.";
  elements.emptyMessage.classList.toggle("hidden", Object.keys(state.nodes).length > 1);
  renderClusters();
  renderFocusRing();
  renderNodes();
  renderDetail();
  renderComparison();
  renderInterpretationList(elements.closest, state.presentation.closest_rivals);
  renderInterpretationList(elements.differentiation, state.presentation.your_differentiation);
  renderInterpretationList(elements.opportunity, state.presentation.opportunity_around_you);
}

async function consumeEventStream(response) {
  if (!response.ok || !response.body) throw new Error("RivalMap stream unavailable");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const data = frame
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (!data) continue;
      state = applyAgentEvent(state, JSON.parse(data));
      render();
    }
    if (done) break;
  }
}

elements.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  activeRequest?.abort();
  activeRequest = new AbortController();
  state = createInitialState(elements.idea.value.trim());
  render();
  try {
    const response = await fetch("/api/v1/runs/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        idea: elements.idea.value.trim(),
        target_user: elements.targetUser.value.trim() || null,
        problem: elements.problem.value.trim() || null,
      }),
      signal: activeRequest.signal,
    });
    await consumeEventStream(response);
  } catch (error) {
    if (error.name === "AbortError") return;
    state = applyAgentEvent(state, { event: "run_failed", run_status: "FAILED" });
    render();
  }
});

document.querySelector("#close-detail").addEventListener("click", () => {
  state = selectNode(state, null);
  render();
});
elements.compareToggle.addEventListener("click", () => {
  const node = state.nodes[state.selectedNodeId];
  if (!node?.product_id) return;
  state = toggleCompareProduct(state, node.product_id);
  render();
});
document.querySelector("#clear-compare").addEventListener("click", () => {
  state = { ...state, compareProductIds: [] };
  render();
});

render();
