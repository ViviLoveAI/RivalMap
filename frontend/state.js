const USER_NODE_ID = "user_idea";
const FRAMING_FIELDS = ["idea", "problem", "targetUser", "exclusions"];

export function createFramingState() {
  return {
    step: 0,
    values: { idea: "", problem: "", targetUser: "", exclusions: "" },
    researchStarted: false,
    complete: false,
  };
}

export function framingQuestion(framing) {
  const field = FRAMING_FIELDS[Math.min(framing.step, FRAMING_FIELDS.length - 1)];
  const questions = {
    idea: ["What are you building?", "e.g. AI interview coaching platform"],
    problem: ["What problem does it solve?", "e.g. Practice interviews and receive feedback"],
    targetUser: ["Who is it for?", "e.g. Job seekers"],
    exclusions: ["Anything to leave outside this map?", "Optional — e.g. recruiting suites"],
  };
  return { field, question: questions[field][0], placeholder: questions[field][1] };
}

export function answerFramingQuestion(framing, answer = "") {
  if (framing.complete) return framing;
  const field = FRAMING_FIELDS[framing.step];
  const cleaned = answer.trim();
  if (!cleaned && field !== "exclusions") return framing;
  const nextStep = framing.step + 1;
  return {
    ...framing,
    step: Math.min(nextStep, FRAMING_FIELDS.length - 1),
    values: { ...framing.values, [field]: cleaned },
    researchStarted: framing.researchStarted || field === "targetUser",
    complete: nextStep >= FRAMING_FIELDS.length,
  };
}

export function createInitialState(idea = "Your product") {
  return {
    idea,
    marketBrief: { product_idea: idea },
    marketBriefStreamed: false,
    runStatus: "STARTING",
    initialReadyReached: false,
    degraded: false,
    activities: ["Understanding your market..."],
    nodes: {
      [USER_NODE_ID]: {
        node_id: USER_NODE_ID,
        candidate_id: USER_NODE_ID,
        label: idea || "Your product",
        node_type: "USER_IDEA",
        lifecycle: "USER_IDEA",
        x: 5,
        y: 5,
        relationship: "UNKNOWN",
        source_evidence_ids: [],
      },
    },
    clusters: {},
    focusRing: [],
    profiles: {},
    evidence: {},
    validations: {},
    analysisByCandidate: {},
    degradationLevel: null,
    selectedNodeId: null,
    compareProductIds: [],
    presentation: {
      closest_rivals: [],
      your_differentiation: [],
      opportunity_around_you: [],
    },
    researchSummary: null,
  };
}

function requestedBranches(event) {
  return event.orchestrator_decision?.target_branches || [];
}

export function activityLabelForEvent(event) {
  const research = event.research_event;
  const intelligence = event.intelligence_event;

  if (event.event === "framing_started") return "Understanding your product...";
  if (event.event === "market_brief_updated") return "✓ Market understood";
  if (event.event === "framing_question") return "Refining the market brief...";
  if (event.event === "research_requested") {
    const branches = requestedBranches(event);
    if (branches.includes("DIRECT")) return "Searching direct competitors...";
    if (branches.includes("ADJACENT")) return "Exploring adjacent products...";
    return "Exploring the market...";
  }
  if (event.event === "enrichment_requested") return "Expanding nearby market...";
  if (event.event === "research_progress" && research?.event === "candidate_validated") {
    const count = event.research_summary?.passed ?? 0;
    if (count < 5 || count % 5 !== 0) return null;
    return `✓ ${count} relevant products mapped`;
  }
  if (event.event === "research_progress" && research?.branch === "ADJACENT") {
    return "Exploring adjacent products...";
  }
  if (event.event === "intelligence_progress" && intelligence?.event === "analysis_started") {
    return "Analyzing your closest rivals";
  }
  if (event.event === "presentation_update" && Array.isArray(event.visualization_delta?.focus_ring)) {
    return event.visualization_delta.focus_ring.length
      ? "✓ Competitive space identified"
      : "✓ Adjacent market mapped";
  }
  if (event.event === "presentation_update") return null;
  if (event.event === "agent_degraded" || event.event === "run_failed") {
    return "Partial results available";
  }
  if (event.event === "orchestration_complete") return "Research complete";
  return null;
}

export function applyVisualizationDelta(state, delta) {
  const nodes = { ...state.nodes };
  for (const nodeId of delta.remove_node_ids || []) delete nodes[nodeId];
  for (const node of delta.upsert_nodes || []) {
    const nodeId = node.node_type === "USER_IDEA" ? USER_NODE_ID : node.node_id;
    const existing = nodes[nodeId] || {};
    nodes[nodeId] = { ...existing, ...node, node_id: nodeId };
  }

  const clusters = { ...state.clusters };
  for (const clusterId of delta.remove_cluster_ids || []) delete clusters[clusterId];
  for (const cluster of delta.upsert_clusters || []) clusters[cluster.cluster_id] = cluster;

  return {
    ...state,
    nodes,
    clusters,
    focusRing: delta.focus_ring ? [...delta.focus_ring] : state.focusRing,
    degradationLevel: delta.degradation_level || state.degradationLevel,
    selectedNodeId: nodes[state.selectedNodeId] ? state.selectedNodeId : null,
  };
}

export function applyAgentEvent(state, event) {
  let next = {
    ...state,
    runStatus: event.run_status || state.runStatus,
    initialReadyReached: state.initialReadyReached || event.run_status === "INITIAL_READY",
  };
  if (event.market_brief?.product_idea) {
    const user = next.nodes[USER_NODE_ID];
    next = {
      ...next,
      idea: event.market_brief.product_idea,
      marketBrief: { ...next.marketBrief, ...event.market_brief },
      marketBriefStreamed: true,
      nodes: {
        ...next.nodes,
        [USER_NODE_ID]: { ...user, label: event.market_brief.product_idea },
      },
    };
  }
  if (event.research_summary) next.researchSummary = event.research_summary;
  const research = event.research_event;
  if (research) {
    next.evidence = { ...next.evidence };
    next.validations = { ...next.validations };
    for (const item of research.batch?.evidence || []) next.evidence[item.evidence_id] = item;
    for (const item of [...(research.batch?.validations || []), research.validation].filter(Boolean)) {
      next.validations[item.candidate_id] = item;
    }
  }
  const analysis = event.intelligence_event;
  if (analysis?.candidate_id) {
    const previous = next.analysisByCandidate[analysis.candidate_id] || {};
    next.analysisByCandidate = { ...next.analysisByCandidate, [analysis.candidate_id]: {
      ...previous,
      ...(analysis.structured_facts ? { structured_facts: analysis.structured_facts } : {}),
      ...(analysis.semantic_analysis ? { semantic_analysis: analysis.semantic_analysis } : {}),
    } };
  }
  if (event.intelligence_event?.profile) {
    const profile = event.intelligence_event.profile;
    next.profiles = { ...next.profiles, [profile.product_id]: profile };
    if (profile.candidate_validation) {
      next.validations = { ...next.validations, [profile.candidate_validation.candidate_id]: profile.candidate_validation };
    }
  }
  if (event.visualization_delta) next = applyVisualizationDelta(next, event.visualization_delta);
  if (event.presentation) next.presentation = event.presentation;
  if (event.event === "agent_degraded" || event.event === "run_failed" || analysis?.profile?.analysis_status === "PARTIAL") next.degraded = true;

  if (event.event === "presentation_update" && Array.isArray(event.visualization_delta?.focus_ring)) {
    const obsoleteMilestone = event.visualization_delta.focus_ring.length
      ? "✓ Adjacent market mapped"
      : "✓ Competitive space identified";
    next.activities = next.activities.filter((item) => item !== obsoleteMilestone);
  }

  const activity = activityLabelForEvent(event);
  if (activity && next.activities.at(-1) !== activity) {
    next.activities = [...next.activities, activity].slice(-8);
  }
  return next;
}

export function selectNode(state, nodeId) {
  return { ...state, selectedNodeId: state.nodes[nodeId] ? nodeId : null };
}

export function toggleCompareProduct(state, productId) {
  if (!state.profiles[productId]) return state;
  const selected = state.compareProductIds;
  if (selected.includes(productId)) {
    return { ...state, compareProductIds: selected.filter((id) => id !== productId) };
  }
  if (selected.length >= 4) return state;
  return { ...state, compareProductIds: [...selected, productId] };
}

export function statusPresentation(state) {
  if (state.runStatus === "FAILED") return { label: "Unable to complete", tone: "failed" };
  if (state.runStatus === "COMPLETE") {
    return state.degraded
      ? { label: "Complete · partial coverage", tone: "partial" }
      : { label: "Research complete", tone: "complete" };
  }
  if (state.runStatus === "INITIAL_READY") {
    return { label: "Initial map ready", tone: "ready" };
  }
  if (state.runStatus === "ENRICHING") {
    return state.degraded
      ? { label: "Enriching · partial coverage", tone: "partial" }
      : { label: "Enriching map", tone: "enriching" };
  }
  return { label: "Searching", tone: "searching" };
}

export function comparisonRows(state) {
  return state.compareProductIds.map((productId) => {
    const profile = state.profiles[productId];
    const facts = profile.structured_facts || {};
    const semantic = profile.semantic_analysis || {};
    const evidenceIds = profile.source_evidence_ids || [];
    const fieldEvidence = facts.field_evidence_ids || {};
    const value = (text, field, inferred = false) => {
      const normalized = Array.isArray(text) ? text.filter(Boolean).join(", ") : text;
      if (!normalized) return null;
      return {
        text: normalized,
        evidenceIds: field?.startsWith("semantic_")
          ? semantic.source_evidence_ids || []
          : fieldEvidence[field] || facts.source_evidence_ids || [],
        confidence: field?.startsWith("semantic_") ? semantic.confidence : facts.confidence,
        inferred,
      };
    };
    const fallbackDescription = profile.description?.startsWith("Evidence-backed candidate:")
      ? null
      : profile.description;
    const fallbackRelevance = semantic.relevance_to_brief?.includes("relationship classification remains uncertain")
      ? null
      : semantic.relevance_to_brief;
    return {
      productId,
      name: profile.name,
      confidence: profile.confidence,
      targetCustomer: value(facts.target_users, "target_users"),
      problem: value(
        semantic.problem_solved || facts.primary_use_case || fallbackDescription,
        semantic.problem_solved ? "semantic_problem_solved" : "primary_use_case",
        Boolean(semantic.problem_solved),
      ),
      workflow: value(
        semantic.core_workflow || facts.workflow_coverage,
        semantic.core_workflow ? "semantic_core_workflow" : "workflow_coverage",
        Boolean(semantic.core_workflow),
      ),
      scope: value(
        [facts.product_category, facts.business_model].filter(Boolean),
        facts.product_category ? "product_category" : "business_model",
      ),
      capabilities: value(facts.features, "features"),
      positioning: value(
        semantic.positioning || facts.positioning,
        semantic.positioning ? "semantic_positioning" : "positioning",
        Boolean(semantic.positioning),
      ),
      pricing: value(facts.pricing_signals, "pricing_signals"),
      relationship: value(
        semantic.relationship && semantic.relationship !== "UNKNOWN" ? semantic.relationship : null,
        "semantic_relationship",
        true,
      ),
      overlap: value(fallbackRelevance, "semantic_relevance", true),
      differentiation: value(semantic.differentiators, "semantic_differentiators", true),
      evidenceIds,
    };
  });
}

export function focusZoneState(state) {
  const count = state.focusRing.length;
  if (count >= 3) return { kind: "strong", label: "Your closest competitive space" };
  if (count > 0) return { kind: "emerging", label: "Emerging competitive space" };
  return { kind: "empty", label: "No close direct rivals identified" };
}

function labelBox(item, placement) {
  const width = Math.min(item.priority === 1 ? 205 : 170, Math.max(46, item.label.length * (item.priority === 1 ? 7.4 : 6.7)));
  const height = item.isUser || item.hasRelation ? 29 : 17;
  const baselineX = item.point.x + placement.x;
  const baselineY = item.point.y + placement.y;
  const left = placement.anchor === "start"
    ? baselineX
    : placement.anchor === "end"
      ? baselineX - width
      : baselineX - width / 2;
  return { left, right: left + width, top: baselineY - 13, bottom: baselineY - 13 + height };
}

function boxesOverlap(first, second, gap = 5) {
  return first.left < second.right + gap
    && first.right + gap > second.left
    && first.top < second.bottom + gap
    && first.bottom + gap > second.top;
}

function overlapArea(box, occupied) {
  return occupied.reduce((total, other) => {
    const width = Math.max(0, Math.min(box.right, other.right) - Math.max(box.left, other.left));
    const height = Math.max(0, Math.min(box.bottom, other.bottom) - Math.max(box.top, other.top));
    return total + width * height;
  }, 0);
}

function placementOptions(point) {
  const preferRight = point.x <= 500;
  const preferBottom = point.y < 350;
  const side = (right, y = 2) => ({ x: right ? 17 : -17, y, anchor: right ? "start" : "end", relationY: y + 14 });
  const vertical = (bottom, x = 0) => ({ x, y: bottom ? 29 : -18, anchor: "middle", relationY: bottom ? 43 : -31 });
  return [
    side(preferRight), side(preferRight, -10), side(preferRight, 14),
    vertical(preferBottom), vertical(preferBottom, -10), vertical(preferBottom, 10),
    side(!preferRight), side(!preferRight, -10), side(!preferRight, 14),
    vertical(!preferBottom), vertical(!preferBottom, -10), vertical(!preferBottom, 10),
    side(preferRight, -22), side(preferRight, 26),
    side(!preferRight, -22), side(!preferRight, 26),
  ];
}

export function layoutMapLabels(items) {
  const occupied = [];
  const result = {};
  const ordered = [...items].sort((left, right) => left.priority - right.priority
    || (left.focusRank ?? Number.MAX_SAFE_INTEGER) - (right.focusRank ?? Number.MAX_SAFE_INTEGER)
    || left.nodeId.localeCompare(right.nodeId));

  for (const item of ordered) {
    const options = item.isUser
      ? [{ x: 0, y: 49, anchor: "middle", relationY: 63 }]
      : placementOptions(item.point);
    let selected = null;
    for (const placement of options) {
      const box = labelBox(item, placement);
      const insideMap = box.left >= 12 && box.right <= 988 && box.top >= 12 && box.bottom <= 688;
      if (insideMap && !occupied.some((other) => boxesOverlap(box, other))) {
        selected = { ...placement, box };
        break;
      }
    }
    if (!selected && item.priority === 1) {
      selected = options
        .map((placement) => ({ ...placement, box: labelBox(item, placement) }))
        .sort((left, right) => overlapArea(left.box, occupied) - overlapArea(right.box, occupied))[0];
    }
    if (!selected) {
      result[item.nodeId] = { hidden: true, priority: item.priority };
      continue;
    }
    occupied.push(selected.box);
    result[item.nodeId] = { ...selected, hidden: false, priority: item.priority };
  }
  return result;
}

export function softClusterTerritoryPath(point, radius, stableKey = "cluster") {
  const seed = [...stableKey].reduce((total, character) => total + character.charCodeAt(0), 0);
  const points = Array.from({ length: 8 }, (_, index) => {
    const angle = -Math.PI / 2 + index * Math.PI / 4;
    const variation = 0.84 + ((seed + index * 17) % 19) / 100;
    return {
      x: point.x + Math.cos(angle) * radius * variation,
      y: point.y + Math.sin(angle) * radius * variation * 0.72,
    };
  });
  const midpoint = (left, right) => ({ x: (left.x + right.x) / 2, y: (left.y + right.y) / 2 });
  const start = midpoint(points.at(-1), points[0]);
  const segments = points.map((current, index) => {
    const next = midpoint(current, points[(index + 1) % points.length]);
    return `Q ${current.x.toFixed(1)} ${current.y.toFixed(1)} ${next.x.toFixed(1)} ${next.y.toFixed(1)}`;
  }).join(" ");
  return `M ${start.x.toFixed(1)} ${start.y.toFixed(1)} ${segments} Z`;
}

const comparisonDimensions = [
  ["Target customer", "targetCustomer"],
  ["Core job / problem solved", "problem"],
  ["Core workflow", "workflow"],
  ["Product scope", "scope"],
  ["Key capabilities", "capabilities"],
  ["Positioning", "positioning"],
  ["Pricing signal", "pricing"],
  ["Relationship to your idea", "relationship"],
  ["Strongest overlap with you", "overlap"],
  ["Biggest difference from you", "differentiation"],
];

function anchorColumn(state) {
  const brief = state.marketBrief || {};
  const known = (text) => text ? { text, evidenceIds: [], confidence: 1, userProvided: true } : null;
  return {
    productId: USER_NODE_ID,
    name: "YOUR IDEA",
    isAnchor: true,
    targetCustomer: known(brief.target_user),
    problem: known(brief.problem),
    workflow: null,
    scope: known(brief.competitive_scope),
    capabilities: null,
    positioning: known(brief.priority_dimension ? `Prioritizes ${brief.priority_dimension}` : null),
    pricing: null,
    relationship: known("Reference point"),
    overlap: null,
    differentiation: null,
  };
}

export function comparisonModel(state) {
  const rivals = comparisonRows(state);
  const anchor = anchorColumn(state);
  const dimensions = comparisonDimensions
    .map(([label, key]) => ({ label, key }))
    .filter(({ key }) => rivals.some((rival) => rival[key]));
  const omitted = comparisonDimensions
    .filter(([, key]) => !rivals.some((rival) => rival[key]))
    .map(([label]) => label);
  const ranked = state.focusRing.find((entry) => rivals.some((rival) => rival.productId === entry.product_id));
  const proximity = rivals.map((rival) => ({
    rival,
    node: Object.values(state.nodes).find((node) => node.product_id === rival.productId),
  })).filter(({ rival, node }) => node?.similarity_to_user != null
    && (rival.overlap || (rival.relationship && rival.relationship.text !== "UNKNOWN")))
    .sort((a, b) => b.node.similarity_to_user - a.node.similarity_to_user)[0];
  const closest = ranked
    ? rivals.find((rival) => rival.productId === ranked.product_id)
    : proximity?.rival;
  const closestBasis = ranked
    ? "ranks highest among your selections in the backend Focus Ring"
    : proximity
      ? `has the highest existing mapped similarity among your selections (${Math.round(proximity.node.similarity_to_user * 100)}%)`
      : null;
  const closestText = closest
    ? `${closest.name} ${closestBasis}.${closest.overlap ? ` ${closest.overlap.text}` : " Overlap details are not yet available."}`
    : "No selected product has a supported Focus Ring rank or mapped proximity; the available data does not establish a closest competitor.";
  const differentiators = rivals
    .filter((rival) => rival.differentiation)
    .map((rival) => `${rival.name}: ${rival.differentiation.text}`);
  const differentiationText = differentiators.length
    ? `Reported rival differentiators: ${differentiators.slice(0, 2).join("; ")}. These do not by themselves establish your idea’s advantage.`
    : "The available evidence does not yet establish a defensible differentiation claim for your idea.";
  const directCount = rivals.filter((rival) => rival.relationship?.text === "DIRECT").length;
  const strategicText = directCount
    ? `${directCount} selected ${directCount === 1 ? "rival competes" : "rivals compete"} directly with your idea. Use the supported differences above to sharpen positioning rather than claiming unsupported whitespace.`
    : "The selected products appear adjacent or uncertain. Treat this as an emerging competitive set until stronger direct-overlap evidence is available.";
  return {
    columns: [anchor, ...rivals],
    rivals,
    dimensions,
    omitted,
    synthesis: {
      closestOverlap: closestText,
      clearestDifferentiation: differentiationText,
      strategicTakeaway: strategicText,
    },
  };
}

export { USER_NODE_ID };

export function safeSourceUrl(value) {
  try { const url = new URL(value); return ["https:", "http:"].includes(url.protocol) ? url.href : null; }
  catch { return null; }
}

const INTERNAL_DIAGNOSTIC = /(missing structured field|analysis path was unavailable|structured analysis path|semantic analysis path)/i;
const TRAILING_FRAGMENT = /\s\b(?:and|or|to|for|with|in|a|an|the|[a-z])\.?$/i;
const FIELD_LABELS = {
  business_model: "Business model",
  canonical_url: "Product website",
  company_name: "Company identity",
  features: "Capabilities",
  integrations: "Integrations",
  positioning: "Positioning",
  pricing_signals: "Pricing",
  primary_use_case: "Primary use case",
  product_category: "Category",
  target_users: "Target customer",
  workflow_coverage: "Workflow coverage",
};

function stripDuplicatePrefix(text, productName) {
  if (!productName) return text;
  const escaped = productName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return text.replace(new RegExp(`^(?:${escaped})(?:\\s*[-—:·|]\\s*|\\s+)+`, "i"), "");
}

export function sanitizeDisplayText(value, { productName = null, maxLength = 220 } = {}) {
  if (value == null) return null;
  let text = String(value)
    .replace(/[`*_]/g, " ")
    .replace(/(^|\s)#{1,6}(?=\s|\d)/g, "$1")
    .replace(/\s+/g, " ")
    .replace(/\s*([|·])\s*(?:\1\s*)+/g, " $1 ")
    .trim();
  text = stripDuplicatePrefix(text, productName).trim();
  if (!text || INTERNAL_DIAGNOSTIC.test(text) || text.length > maxLength || TRAILING_FRAGMENT.test(text)) return null;
  return text.replace(/\s+([,.;:!?])/g, "$1").trim();
}

export function concisePresentationInsight(values, maximum = 190) {
  for (const value of values || []) {
    const cleaned = sanitizeDisplayText(value, { maxLength: 1200 });
    if (!cleaned) continue;
    const completeSentence = cleaned.match(/^.{20,190}?[.!?](?=\s|$)/)?.[0];
    if (completeSentence && completeSentence.length <= maximum) return completeSentence;
    if (cleaned.length <= maximum) return cleaned;
    const words = cleaned.split(/\s+/);
    let result = "";
    for (const word of words) {
      if (`${result} ${word}`.trim().length > maximum - 1) break;
      result = `${result} ${word}`.trim();
    }
    if (result) return `${result.replace(/[,:;—-]+$/, "")}…`;
  }
  return null;
}

function cleanProductName(value) {
  const cleaned = sanitizeDisplayText(value, { maxLength: 100 });
  return cleaned?.replace(/^\d+\s+(?=[A-Z])/i, "").trim() || null;
}

function cleanSupportedStatement(value, productName) {
  const direct = sanitizeDisplayText(value, { productName, maxLength: 180 });
  const raw = String(value || "");
  const contaminated = /#{1,6}|(?:\.{3}|…)|\n/.test(raw) || raw.length > 180;
  if (direct && !contaminated) return direct;
  const candidates = raw
    .split(/(?:#{1,6}|\.{3,}|…+|\n+)/)
    .map(part => sanitizeDisplayText(part, { productName, maxLength: 180 }))
    .filter(part => part && part.length >= 18)
    .sort((left, right) => right.length - left.length);
  return candidates[0] || null;
}

function evidenceGapLabels(facts, profile, semantic) {
  const missing = new Set((facts.missing_fields || []).map(field => FIELD_LABELS[field]).filter(Boolean));
  const diagnostics = [...(profile.uncertainties || []), ...(semantic.uncertainties || [])];
  for (const diagnostic of diagnostics) {
    const match = String(diagnostic).match(/missing structured field:\s*([a-z_]+)/i);
    if (match && FIELD_LABELS[match[1]]) missing.add(FIELD_LABELS[match[1]]);
    if (/pricing/i.test(diagnostic)) missing.add("Pricing");
    if (/positioning/i.test(diagnostic)) missing.add("Positioning");
  }
  return [...missing].slice(0, 4);
}

function uncertaintySummary(profile, semantic, facts) {
  const diagnostics = [...(profile.uncertainties || []), ...(semantic.uncertainties || [])];
  const summaries = [];
  if ((facts.missing_fields || []).length || diagnostics.some(item => /missing structured field/i.test(item))) summaries.push("Product details incomplete");
  if (diagnostics.some(item => /pricing/i.test(item))) summaries.push("Pricing evidence limited");
  if (diagnostics.some(item => /positioning/i.test(item))) summaries.push("Positioning not fully established");
  if (diagnostics.some(item => /semantic analysis path was unavailable/i.test(item))) summaries.push("Semantic analysis partial");
  return [...new Set(summaries)].slice(0, 4);
}

export function productDetailModel(state, node) {
  const profile = state.profiles[node?.product_id] || {};
  const early = state.analysisByCandidate[node?.candidate_id] || {};
  const facts = profile.structured_facts || early.structured_facts || {};
  const semantic = profile.semantic_analysis || early.semantic_analysis || {};
  const validation = profile.candidate_validation || state.validations[node?.candidate_id];
  const focus = state.focusRing.find(entry => entry.product_id === node?.product_id);
  const name = cleanProductName(facts.product_name || profile.name || node?.label) || "Product";
  const rows = [];
  const add = (label, value) => {
    const values = Array.isArray(value) ? value : [value];
    const cleaned = [...new Set(values.map(item => sanitizeDisplayText(item, { productName: name })).filter(Boolean))];
    const text = cleaned.join(" · ");
    if (text && !/^(unknown|not yet known)$/i.test(text)) rows.push({ label, text });
  };
  add("Company", facts.company_name);
  add("Relationship to your idea", semantic.relationship || node?.relationship);
  add("Why it matters", semantic.relevance_to_brief);
  add("Target customer", facts.target_users);
  const primaryUseCase = cleanSupportedStatement(facts.primary_use_case, name)
    || cleanSupportedStatement(semantic.core_workflow, name)
    || cleanSupportedStatement(semantic.problem_solved, name);
  add("Primary use case", primaryUseCase);
  if (sanitizeDisplayText(semantic.core_workflow, { productName: name }) !== primaryUseCase) add("Core workflow", semantic.core_workflow);
  add("Positioning", semantic.positioning || facts.positioning);
  add("Key capabilities", facts.features);
  add("Differentiators", semantic.differentiators);
  add("Pricing signal", facts.pricing_signals);
  add("Category", facts.product_category);
  add("Workflow coverage", facts.workflow_coverage);
  add("Integrations", facts.integrations);
  add("Business model", facts.business_model);
  if (focus) add("Competitive space", `Focus competitor · rank ${focus.rank}`);
  const validationLabel = validation?.status === "PASS" ? "Validated" : validation?.status === "PROVISIONAL" ? "Provisional" : null;
  add("Candidate status", validationLabel);
  const confidence = [
    facts.confidence != null ? `Facts ${Math.round(facts.confidence * 100)}%` : null,
    semantic.confidence != null ? `Interpretation ${Math.round(semantic.confidence * 100)}%` : null,
  ].filter(Boolean);
  add("Analysis confidence", confidence);
  add("Evidence gaps", evidenceGapLabels(facts, profile, semantic));
  add("Uncertainty", uncertaintySummary(profile, semantic, facts));
  if (profile.analysis_status === "PARTIAL") add("Profile status", "Partial profile — some attributes are still being verified.");
  const evidenceIds = [...new Set([...(profile.source_evidence_ids || []), ...(facts.source_evidence_ids || []), ...(semantic.source_evidence_ids || [])])];
  const sources = evidenceIds.map(id => state.evidence[id]).filter(Boolean).map(item => {
    const url = safeSourceUrl(item.source?.url);
    return {
      id: item.evidence_id,
      url,
      title: sanitizeDisplayText(item.source?.title, { maxLength: 100 }) || (url ? new URL(url).hostname : item.evidence_id),
      claim: cleanSupportedStatement(item.claim, name),
      inferred: item.inferred,
      confidence: item.confidence,
      kind: "Evidence",
    };
  }).filter(source => source.url);
  for (const raw of profile.source_urls || []) {
    const url = safeSourceUrl(raw);
    if (url && !sources.some(source => source.url === url)) sources.push({ url, title: new URL(url).hostname, kind: "Source" });
  }
  const canonicalUrl = safeSourceUrl(facts.canonical_url);
  if (canonicalUrl && !sources.some(source => source.url === canonicalUrl)) {
    sources.push({ url: canonicalUrl, title: new URL(canonicalUrl).hostname, kind: "Product website" });
  }
  return { name, relationship: semantic.relationship || node?.relationship,
    rows, sources, evidenceIds, canonicalUrl };
}

export function currentPresentationData(state) {
  const profiles = Object.values(state.profiles);
  const ids = new Set(profiles.flatMap(profile => profile.source_evidence_ids || []));
  const sources = new Set(profiles.flatMap(profile => profile.source_urls || []).map(safeSourceUrl).filter(Boolean));
  ids.forEach(id => {
    const item = state.evidence[id];
    const identity = safeSourceUrl(item?.source?.url) || item?.source?.source_id;
    if (identity) sources.add(identity);
  });
  const mapped = Object.values(state.nodes).filter(node => node.node_type === "PRODUCT").length;
  const validatedIds = new Set(profiles.map(profile => profile.candidate_id || profile.product_id));
  Object.values(state.validations).filter(validation => validation.status !== "REJECT")
    .forEach(validation => validatedIds.add(validation.candidate_id));
  const validated = validatedIds.size;
  return { title: state.idea, presentation: state.presentation,
    evidenceNote: `${mapped} products mapped · ${validated} validated · ${sources.size} unique sources · ${ids.size} evidence references` };
}
