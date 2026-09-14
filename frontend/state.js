const USER_NODE_ID = "user_idea";

export function createInitialState(idea = "Your product") {
  return {
    idea,
    runStatus: "STARTING",
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
  if (event.event === "market_brief_updated") return "Market brief ready";
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
    return `Found ${count} relevant ${count === 1 ? "product" : "products"}`;
  }
  if (event.event === "research_progress" && research?.branch === "ADJACENT") {
    return "Exploring adjacent products...";
  }
  if (event.event === "intelligence_progress" && intelligence?.event === "analysis_started") {
    return "Analyzing positioning...";
  }
  if (event.event === "presentation_update" && event.run_status === "INITIAL_READY") {
    return "Initial competitive map ready";
  }
  if (event.event === "presentation_update") return "Adding market context...";
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
  };
}

export function applyAgentEvent(state, event) {
  let next = { ...state, runStatus: event.run_status || state.runStatus };
  if (event.market_brief?.product_idea) {
    const user = next.nodes[USER_NODE_ID];
    next = {
      ...next,
      idea: event.market_brief.product_idea,
      nodes: {
        ...next.nodes,
        [USER_NODE_ID]: { ...user, label: event.market_brief.product_idea },
      },
    };
  }
  if (event.research_summary) next.researchSummary = event.research_summary;
  if (event.intelligence_event?.profile) {
    const profile = event.intelligence_event.profile;
    next.profiles = { ...next.profiles, [profile.product_id]: profile };
  }
  if (event.visualization_delta) next = applyVisualizationDelta(next, event.visualization_delta);
  if (event.presentation) next.presentation = event.presentation;
  if (event.event === "agent_degraded" || event.event === "run_failed") next.degraded = true;

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
    const differentiation = (semantic.differentiators || [])[0] || "Not yet established";
    return {
      productId,
      name: profile.name,
      targetCustomer: (facts.target_users || []).join(", ") || "Unknown",
      workflow: (facts.workflow_coverage || []).join(", ") || semantic.core_workflow || "Unknown",
      capabilities: (facts.features || []).join(", ") || "Unknown",
      positioning: facts.positioning || semantic.positioning || "Unknown",
      pricing: (facts.pricing_signals || []).join(", ") || "Unknown",
      overlap: semantic.relevance_to_brief || "Not yet analyzed",
      differentiation,
      takeaway: `${profile.name} overlaps on ${semantic.core_workflow || "the core workflow"}; its clearest distinction is ${differentiation.toLowerCase()}.`,
    };
  });
}

export { USER_NODE_ID };
