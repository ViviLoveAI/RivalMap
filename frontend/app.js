import {
  USER_NODE_ID,
  applyAgentEvent,
  answerFramingQuestion,
  comparisonModel,
  comparisonRows,
  concisePresentationInsight,
  currentPresentationData,
  productDetailModel,
  createFramingState,
  createInitialState,
  focusZoneState,
  framingQuestion,
  layoutMapLabels,
  softClusterTerritoryPath,
  selectNode,
  statusPresentation,
  toggleCompareProduct,
} from "./state.js";
import { buildPresentationSvg, exportFilename } from "./export.js";

const svgNamespace = "http://www.w3.org/2000/svg";
const elements = {
  briefTitle: document.querySelector("#brief-title"),
  briefContext: document.querySelector("#brief-context"),
  framingCard: document.querySelector("#framing-card"),
  framingForm: document.querySelector("#framing-form"),
  framingQuestion: document.querySelector("#framing-question"),
  framingAnswer: document.querySelector("#framing-answer"),
  framingProgress: [...document.querySelectorAll(".framing-progress span")],
  researchRunning: document.querySelector("#research-running"),
  skipQuestion: document.querySelector("#skip-question"),
  demoMode: document.querySelector("#demo-mode"),
  newMap: document.querySelector("#new-map"),
  exportSvg: document.querySelector("#export-svg"),
  exportPng: document.querySelector("#export-png"),
  presentationExportSvg: document.querySelector("#presentation-export-svg"),
  presentationExportPng: document.querySelector("#presentation-export-png"),
  exportToast: document.querySelector("#export-toast"),
  presentationMode: document.querySelector("#presentation-mode"),
  exitPresentation: document.querySelector("#exit-presentation"),
  presentationFooter: document.querySelector("#presentation-footer"),
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
  focusLayer: document.querySelector("#focus-layer"),
  replayFocus: document.querySelector("#replay-focus"),
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
  compareSynthesis: document.querySelector("#compare-synthesis"),
  closest: document.querySelector("#closest-rivals"),
  differentiation: document.querySelector("#differentiation"),
  opportunity: document.querySelector("#opportunity"),
};

let state = createInitialState();
let framing = createFramingState();
let activeRequest = null;
let activeRunId = null;
const nodeElements = new Map();
const clusterElements = new Map();
let revealedFocusState = "empty";
let focusSpotlightPlayed = false;
let focusSpotlightActive = false;
let focusSpotlightTimers = [];

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
  const star = svgElement("path", "user-star");
  star.setAttribute("d", "M0 -18 C2 -6 6 -2 18 0 C6 2 2 6 0 18 C-2 6 -6 2 -18 0 C-6 -2 -2 -6 0 -18Z");
  const userCaption = svgElement("text", "user-caption");
  userCaption.setAttribute("y", "31");
  userCaption.textContent = "YOUR IDEA";
  const label = svgElement("text", "node-label");
  label.setAttribute("y", "28");
  const relation = svgElement("text", "node-relation");
  relation.setAttribute("y", "43");
  group.append(halo, core, star, userCaption, label, relation);
  group.addEventListener("click", () => {
    const selected = state.nodes[group.dataset.nodeId];
    if (!selected || selected.node_type === "USER_IDEA") return;
    state = selectNode(state, group.dataset.nodeId);
    render();
  });
  group.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); group.dispatchEvent(new MouseEvent("click")); }
  });
  group.append(svgElement("title"));
  return group;
}

function renderNodes() {
  const focusIds = new Set(state.focusRing.map((entry) => entry.product_id));
  const focusRanks = new Map(state.focusRing.map((entry) => [entry.product_id, entry.rank]));
  const activeIds = new Set(Object.keys(state.nodes));
  for (const [nodeId, group] of nodeElements) {
    if (!activeIds.has(nodeId)) {
      group.remove();
      nodeElements.delete(nodeId);
    }
  }

  const renderItems = Object.entries(state.nodes).map(([nodeId, node]) => {
    const isUser = node.node_type === "USER_IDEA";
    const isFocus = focusIds.has(node.product_id);
    const relevant = ["DIRECT", "ADJACENT", "ALTERNATIVE"].includes(node.relationship);
    return {
      nodeId,
      node,
      point: mapPoint(node),
      isUser,
      isFocus,
      label: shortLabel(node.label, isFocus || isUser ? 30 : 23),
      priority: isUser || isFocus ? 1 : relevant ? 2 : 3,
      focusRank: focusRanks.get(node.product_id),
      hasRelation: isFocus && Boolean(node.relationship),
    };
  });
  const labelLayouts = layoutMapLabels(renderItems);

  for (const { nodeId, node, point, isUser, isFocus, label: displayLabel, priority } of renderItems) {
    let group = nodeElements.get(nodeId);
    if (!group) {
      group = createNodeElement(nodeId);
      nodeElements.set(nodeId, group);
      elements.nodeLayer.append(group);
    }
    const labelLayout = labelLayouts[nodeId];
    group.setAttribute(
      "class",
      `map-node ${isUser ? "user" : "product"} label-priority-${priority}${isFocus ? " focus" : ""}${labelLayout?.hidden ? " label-hidden" : ""}${state.selectedNodeId === nodeId ? " selected" : ""}`,
    );
    group.setAttribute("transform", `translate(${point.x} ${point.y})`);
    group.querySelector(".node-halo").setAttribute("r", isUser ? "48" : "0");
    group.querySelector(".node-core").setAttribute("r", isUser ? "0" : isFocus ? "10" : priority === 2 ? "7" : "6");
    const label = group.querySelector(".node-label");
    const relation = group.querySelector(".node-relation");
    label.textContent = displayLabel;
    relation.textContent = isFocus ? node.relationship : "";
    label.setAttribute("x", String(labelLayout?.x ?? 0));
    label.setAttribute("y", String(labelLayout?.y ?? 0));
    label.setAttribute("text-anchor", labelLayout?.anchor ?? "middle");
    relation.setAttribute("x", String(labelLayout?.x ?? 0));
    relation.setAttribute("y", String(labelLayout?.relationY ?? 0));
    relation.setAttribute("text-anchor", labelLayout?.anchor ?? "middle");
    group.setAttribute("role", isUser ? "img" : "button");
    if (!isUser) group.setAttribute("tabindex", "0");
    group.setAttribute("aria-label", isUser ? `${node.label}, your product` : `Open ${node.label}`);
    const detail = productDetailModel(state, node);
    group.querySelector("title").textContent = [node.label, detail.relationship, detail.rows.find(row => row.label === "Category")?.text, isUser ? "Your idea" : "Click to inspect"].filter(Boolean).join(" · ");
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
    let group = clusterElements.get(clusterId);
    if (!group) {
      group = svgElement("g", "cluster-territory");
      group.append(svgElement("path", "cluster-region"), svgElement("text", "cluster-label"));
      clusterElements.set(clusterId, group);
      elements.clusterLayer.append(group);
    }
    const point = mapPoint({ x: cluster.centroid_x, y: cluster.centroid_y });
    const label = group.querySelector(".cluster-label");
    const region = group.querySelector(".cluster-region");
    label.setAttribute("x", String(point.x));
    label.setAttribute("y", String(Math.max(point.y - 33, 28)));
    const uncategorized = cluster.normalized_label === "uncategorized";
    label.textContent = uncategorized ? "" : shortLabel(cluster.name, 30);
    group.classList.toggle("uncategorized", uncategorized);
    if (uncategorized) {
      region.removeAttribute("d");
    } else {
      const radius = Math.min(145, Math.max(65, (cluster.region_radius || 1.1) * 38));
      region.setAttribute("d", softClusterTerritoryPath(point, radius, clusterId));
    }
  }
}

function renderFocusRing() {
  const focusNodes = state.focusRing
    .map((entry) => Object.values(state.nodes).find((node) => node.product_id === entry.product_id))
    .filter(Boolean);
  const zone = focusZoneState(state);
  const desiredState = zone.kind;
  elements.focusLayer.dataset.state = desiredState;
  if (!focusNodes.length) {
    focusSpotlightTimers.forEach(clearTimeout);
    focusSpotlightTimers = [];
    focusSpotlightActive = false;
    revealedFocusState = "empty";
    elements.focusLayer.classList.remove("revealed", "drawing", "field-visible", "label-visible");
    elements.focusRing.removeAttribute("d");
    elements.focusGlow.removeAttribute("d");
    elements.replayFocus.hidden = true;
    return;
  }
  const contour = focusContourPath(focusNodes.map(mapPoint), desiredState);
  elements.focusRing.setAttribute("d", contour.path);
  elements.focusGlow.setAttribute("d", contour.path);
  elements.focusLabel.setAttribute("x", String(contour.labelX));
  elements.focusLabel.setAttribute("y", String(contour.labelY));
  elements.focusLabel.textContent = zone.label;
  elements.replayFocus.hidden = !state.initialReadyReached;
  if (state.initialReadyReached && !focusSpotlightPlayed) {
    playFocusSpotlight(desiredState);
  } else if (!focusSpotlightActive) {
    elements.focusLayer.classList.add("revealed");
  }
}

function focusContourPath(points, stateKind) {
  const padding = stateKind === "emerging" ? 48 : 58;
  if (points.length === 1) {
    const { x, y } = points[0];
    return {
      path: `M ${x - padding} ${y} A ${padding} ${padding * .72} 0 1 0 ${x + padding} ${y} A ${padding} ${padding * .72} 0 1 0 ${x - padding} ${y} Z`,
      labelX: x,
      labelY: y - padding * .9,
    };
  }
  if (points.length === 2) {
    const minX = Math.min(...points.map((point) => point.x)) - padding;
    const maxX = Math.max(...points.map((point) => point.x)) + padding;
    const minY = Math.min(...points.map((point) => point.y)) - padding;
    const maxY = Math.max(...points.map((point) => point.y)) + padding;
    const radius = Math.min(padding, (maxY - minY) / 2);
    return {
      path: `M ${minX + radius} ${minY} H ${maxX - radius} Q ${maxX} ${minY} ${maxX} ${minY + radius} V ${maxY - radius} Q ${maxX} ${maxY} ${maxX - radius} ${maxY} H ${minX + radius} Q ${minX} ${maxY} ${minX} ${maxY - radius} V ${minY + radius} Q ${minX} ${minY} ${minX + radius} ${minY} Z`,
      labelX: (minX + maxX) / 2,
      labelY: minY - 12,
    };
  }
  const center = {
    x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
    y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
  };
  const expanded = points.map((point) => {
    const distance = Math.hypot(point.x - center.x, point.y - center.y) || 1;
    return {
      x: point.x + (point.x - center.x) / distance * padding,
      y: point.y + (point.y - center.y) / distance * padding,
    };
  }).sort((a, b) => Math.atan2(a.y - center.y, a.x - center.x)
    - Math.atan2(b.y - center.y, b.x - center.x));
  const midpoint = (a, b) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
  const start = midpoint(expanded.at(-1), expanded[0]);
  const segments = expanded.map((point, index) => {
    const next = midpoint(point, expanded[(index + 1) % expanded.length]);
    return `Q ${point.x} ${point.y} ${next.x} ${next.y}`;
  }).join(" ");
  return {
    path: `M ${start.x} ${start.y} ${segments} Z`,
    labelX: center.x,
    labelY: Math.min(...expanded.map((point) => point.y)) - 13,
  };
}

function playFocusSpotlight(stateKind = focusZoneState(state).kind) {
  if (!state.focusRing.length) return;
  focusSpotlightTimers.forEach(clearTimeout);
  focusSpotlightTimers = [];
  focusSpotlightPlayed = true;
  focusSpotlightActive = true;
  revealedFocusState = stateKind;
  elements.focusLayer.classList.remove("revealed", "drawing", "field-visible", "label-visible");
  elements.nodeLayer.closest("svg").classList.remove("focus-spotlight");
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    focusSpotlightActive = false;
    elements.focusLayer.classList.add("revealed");
    return;
  }
  focusSpotlightTimers = [
    setTimeout(() => {
      focusSpotlightActive = false;
      elements.nodeLayer.closest("svg").classList.add("focus-spotlight");
      elements.focusLayer.classList.add("drawing");
    }, 400),
    setTimeout(() => elements.focusLayer.classList.add("field-visible"), 720),
    setTimeout(() => elements.focusLayer.classList.add("label-visible"), 1120),
    setTimeout(() => {
      elements.nodeLayer.closest("svg").classList.remove("focus-spotlight");
      elements.focusLayer.classList.add("revealed");
      elements.focusLayer.classList.remove("drawing", "field-visible", "label-visible");
    }, 1550),
  ];
}

function addFact(label, value) {
  if (!value) return;
  const term = document.createElement("dt");
  term.textContent = label;
  const description = document.createElement("dd");
  description.textContent = value;
  elements.detailFacts.append(term, description);
}

function renderDetail() {
  const node = state.nodes[state.selectedNodeId];
  const profile = node?.product_id ? state.profiles[node.product_id] : null;
  elements.detail.classList.toggle("open", Boolean(node));
  elements.detail.setAttribute("aria-hidden", String(!node));
  if (!node) return;
  const detail = productDetailModel(state, node);
  elements.detailName.textContent = detail.name;
  elements.detailRelationship.textContent = [detail.relationship !== "UNKNOWN" ? detail.relationship : null, node.similarity_to_user != null ? `${Math.round(node.similarity_to_user * 100)}% feature match` : null].filter(Boolean).join(" · ") || "Relationship still being assessed";
  elements.detailFacts.replaceChildren();
  for (const row of detail.rows) addFact(row.label, row.text);
  if (!detail.rows.length) addFact("Analysis", "Product intelligence is still arriving.");
  elements.detailSources.replaceChildren();
  if (detail.sources.length) {
    const heading = document.createElement("h3");
    heading.textContent = "Evidence";
    elements.detailSources.append(heading);
  }
  for (const source of detail.sources) {
    const item = document.createElement("article");
    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = source.title;
    link.title = [source.claim, source.inferred ? "Interpreted evidence" : "Source evidence", source.id].filter(Boolean).join(" · ");
    const domain = document.createElement("small");
    domain.textContent = new URL(source.url).hostname.replace(/^www\./, "");
    item.append(link, domain);
    if (source.claim) {
      const claim = document.createElement("p");
      claim.textContent = source.claim;
      item.append(claim);
    }
    elements.detailSources.append(item);
  }
  const selected = state.compareProductIds.includes(node.product_id);
  elements.compareToggle.textContent = selected ? "Remove from compare" : "Add to compare";
  elements.compareToggle.disabled = !profile || (!selected && state.compareProductIds.length >= 4);
}

function renderInterpretationList(container, items) {
  container.replaceChildren();
  const presentationMode = document.body.classList.contains("presentation-mode");
  const visibleItems = presentationMode
    ? [concisePresentationInsight(items)].filter(Boolean)
    : (items || []).map(item => concisePresentationInsight([item], 360)).filter(Boolean).slice(0, 3);
  if (!visibleItems.length) {
    const empty = document.createElement("p");
    empty.className = "placeholder";
    empty.textContent = presentationMode ? "" : "Insights will appear as the map develops.";
    container.append(empty);
    return;
  }
  const list = document.createElement("ul");
  for (const item of visibleItems) {
    const row = document.createElement("li");
    row.textContent = item;
    list.append(row);
  }
  container.append(list);
}

function renderComparison() {
  const rows = comparisonRows(state);
  const model = comparisonModel(state);
  elements.compareCount.textContent = String(rows.length);
  elements.compareTray.classList.toggle("open", rows.length > 0);
  elements.compareEmpty.hidden = rows.length >= 2;
  elements.compareEmpty.textContent = rows.length
    ? "Add one more product to compare."
    : "Open a product and add 2–4 nodes to compare.";
  elements.compareTableWrap.replaceChildren();
  elements.compareSynthesis.replaceChildren();
  if (rows.length < 2) return;
  const table = document.createElement("table");
  table.className = "compare-table";
  const head = document.createElement("tr");
  head.append(document.createElement("th"));
  for (const row of model.columns) {
    const heading = document.createElement("th");
    heading.textContent = row.name;
    if (row.isAnchor) heading.className = "anchor-cell";
    head.append(heading);
  }
  table.append(head);
  for (const { label, key } of model.dimensions) {
    const line = document.createElement("tr");
    const heading = document.createElement("th");
    heading.textContent = label;
    line.append(heading);
    for (const row of model.columns) {
      const cell = document.createElement("td");
      const field = row[key];
      cell.textContent = field?.text || "—";
      if (!field) cell.className = "insufficient";
      if (row.isAnchor) cell.classList.add("anchor-cell");
      if (field?.evidenceIds?.length) {
        cell.title = `${field.evidenceIds.length} evidence ${field.evidenceIds.length === 1 ? "source" : "sources"}${field.inferred ? " · interpreted" : ""}`;
        cell.dataset.evidence = field.inferred ? "inferred" : "supported";
      }
      line.append(cell);
    }
    table.append(line);
  }
  elements.compareTableWrap.append(table);
  if (model.omitted.length) {
    const note = document.createElement("p");
    note.className = "evidence-note";
    note.textContent = `Insufficient evidence: ${model.omitted.join(", ")}.`;
    elements.compareTableWrap.append(note);
  }
  const synthesis = [
    ["Closest overlap", model.synthesis.closestOverlap],
    ["Clearest differentiation", model.synthesis.clearestDifferentiation],
    ["Strategic takeaway", model.synthesis.strategicTakeaway],
  ];
  for (const [label, copy] of synthesis) {
    const block = document.createElement("article");
    const heading = document.createElement("h3");
    const paragraph = document.createElement("p");
    heading.textContent = label;
    paragraph.textContent = copy;
    block.append(heading, paragraph);
    elements.compareSynthesis.append(block);
  }
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
    : state.initialReadyReached
      ? "No close direct rivals identified. Adjacent market territories remain visible."
      : "The center is fixed. Validated competitors will appear around your idea.";
  elements.emptyMessage.classList.toggle("hidden", Object.keys(state.nodes).length > 1);
  elements.briefTitle.textContent = state.idea === "Your product" ? "New market exploration" : state.idea;
  const currentBrief = state.marketBriefStreamed ? state.marketBrief : {
    ...state.marketBrief,
    target_user: framing.values.targetUser,
    problem: framing.values.problem,
    exclusions: framing.values.exclusions ? [framing.values.exclusions] : [],
  };
  const context = [
    currentBrief.target_user,
    currentBrief.problem,
    currentBrief.competitive_scope,
    currentBrief.exclusions?.length ? `Excluding ${currentBrief.exclusions.join(", ")}` : "",
  ].filter(Boolean).join(" · ");
  elements.briefContext.textContent = context || "Answer a few short questions to begin.";
  const canExport = Object.values(state.nodes).some((node) => node.node_type === "PRODUCT");
  elements.exportSvg.disabled = !canExport;
  elements.exportPng.disabled = !canExport;
  elements.presentationExportSvg.disabled = !canExport;
  elements.presentationExportPng.disabled = !canExport;
  elements.presentationFooter.textContent = currentPresentationData(state).evidenceNote;
  renderClusters();
  renderFocusRing();
  renderNodes();
  renderDetail();
  renderComparison();
  renderInterpretationList(elements.closest, state.presentation.closest_rivals);
  renderInterpretationList(elements.differentiation, state.presentation.your_differentiation);
  renderInterpretationList(elements.opportunity, state.presentation.opportunity_around_you);
  renderFraming();
}

function renderFraming() {
  elements.framingCard.classList.toggle("hidden", framing.complete);
  if (framing.complete) return;
  const current = framingQuestion(framing);
  elements.framingQuestion.textContent = current.question;
  elements.framingAnswer.placeholder = current.placeholder;
  elements.framingAnswer.required = current.field !== "exclusions";
  elements.researchRunning.hidden = !framing.researchStarted;
  elements.skipQuestion.hidden = current.field !== "exclusions";
  elements.framingProgress.forEach((step, index) => {
    step.classList.toggle("active", index <= framing.step);
  });
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

async function startResearch(values) {
  activeRequest?.abort();
  activeRequest = new AbortController();
  try {
    const response = await fetch("/api/v1/runs/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        idea: values.idea,
        target_user: values.targetUser,
        problem: values.problem,
        exclusions: values.exclusions ? [values.exclusions] : [],
      }),
      signal: activeRequest.signal,
    });
    activeRunId = response.headers.get("X-RivalMap-Run-Id");
    await consumeEventStream(response);
  } catch (error) {
    if (error.name === "AbortError") return;
    state = applyAgentEvent(state, { event: "run_failed", run_status: "FAILED" });
    render();
  }
}

async function refineResearch(values) {
  if (!activeRunId) return;
  try {
    const response = await fetch(`/api/v1/runs/${encodeURIComponent(activeRunId)}/refine`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ exclusions: values.exclusions ? [values.exclusions] : [] }),
    });
    if (response.ok) {
      state = applyAgentEvent(state, { market_brief: await response.json() });
      render();
    }
  } catch {
    // Refinement is best-effort; the active progressive stream remains authoritative.
  }
}

function submitFramingAnswer(answer) {
  const previous = framing;
  framing = answerFramingQuestion(framing, answer);
  if (framing === previous) return;
  if (previous.step === 0) state = createInitialState(framing.values.idea);
  if (!previous.researchStarted && framing.researchStarted) startResearch(framing.values);
  if (previous.step === 3 && framing.researchStarted) {
    refineResearch(framing.values);
    state = {
      ...state,
      activities: [...state.activities, "Market refinement saved · research continues"].slice(-8),
    };
  }
  elements.framingAnswer.value = "";
  render();
  if (!framing.complete) elements.framingAnswer.focus();
}

elements.framingForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitFramingAnswer(elements.framingAnswer.value);
});
elements.skipQuestion.addEventListener("click", () => submitFramingAnswer(""));

elements.newMap.addEventListener("click", () => {
  activeRequest?.abort();
  activeRequest = null;
  activeRunId = null;
  focusSpotlightPlayed = false;
  framing = createFramingState();
  state = createInitialState();
  render();
  elements.framingAnswer.focus();
});

function setPresentationMode(enabled) {
  document.body.classList.toggle("presentation-mode", enabled);
  elements.exitPresentation.hidden = !enabled;
  renderInterpretationList(elements.closest, state.presentation.closest_rivals);
  renderInterpretationList(elements.differentiation, state.presentation.your_differentiation);
  renderInterpretationList(elements.opportunity, state.presentation.opportunity_around_you);
}

elements.presentationMode.addEventListener("click", () => setPresentationMode(true));
elements.exitPresentation.addEventListener("click", () => setPresentationMode(false));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") setPresentationMode(false);
});

elements.demoMode.addEventListener("click", () => {
  activeRequest?.abort();
  focusSpotlightPlayed = false;
  framing = createFramingState();
  framing = answerFramingQuestion(framing, "AI interview coaching platform");
  framing = answerFramingQuestion(framing, "Practice interviews and receive feedback");
  framing = answerFramingQuestion(framing, "Job seekers");
  state = createInitialState(framing.values.idea);
  startResearch(framing.values);
  render();
});

elements.replayFocus.addEventListener("click", () => playFocusSpotlight());

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

function currentExportSvg() {
  return buildPresentationSvg(document.querySelector("#market-map").outerHTML, currentPresentationData(state));
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function showExportToast(format) {
  elements.exportToast.textContent = `${format} export ready`;
  elements.exportToast.classList.add("visible");
  setTimeout(() => elements.exportToast.classList.remove("visible"), 1800);
}

elements.exportSvg.addEventListener("click", () => {
  downloadBlob(
    new Blob([currentExportSvg()], { type: "image/svg+xml;charset=utf-8" }),
    exportFilename(state.idea, "svg"),
  );
  showExportToast("SVG");
});

elements.exportPng.addEventListener("click", () => {
  const svg = currentExportSvg();
  const image = new Image();
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml;charset=utf-8" }));
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = 1600;
    canvas.height = 900;
    const context = canvas.getContext("2d");
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) downloadBlob(blob, exportFilename(state.idea, "png"));
      URL.revokeObjectURL(url);
      showExportToast("PNG");
    }, "image/png");
  };
  image.src = url;
});
elements.presentationExportSvg.addEventListener("click", () => elements.exportSvg.click());
elements.presentationExportPng.addEventListener("click", () => elements.exportPng.click());

render();
elements.framingAnswer.focus();

if (new URLSearchParams(window.location.search).get("demo") === "1") {
  elements.demoMode.click();
}
