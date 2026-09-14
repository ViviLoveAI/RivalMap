import assert from "node:assert/strict";
import test from "node:test";

import {
  activityLabelForEvent,
  applyAgentEvent,
  applyVisualizationDelta,
  comparisonRows,
  createInitialState,
  selectNode,
  statusPresentation,
  toggleCompareProduct,
} from "./state.js";

const productNode = (id, x, y) => ({
  node_id: `node-${id}`,
  candidate_id: `candidate-${id}`,
  product_id: id,
  label: id.toUpperCase(),
  node_type: "PRODUCT",
  lifecycle: "ANALYZED",
  x,
  y,
  relationship: "DIRECT",
  source_evidence_ids: [`ev-${id}`],
});

const profile = (id) => ({
  product_id: id,
  name: id.toUpperCase(),
  source_urls: [`https://${id}.example`],
  structured_facts: {
    target_users: ["Job seekers"],
    workflow_coverage: ["Practice", "Feedback"],
    features: ["Mock interviews"],
    positioning: "Interview practice",
    pricing_signals: ["Subscription"],
  },
  semantic_analysis: {
    relevance_to_brief: "Solves the same interview-practice problem.",
    differentiators: ["Role-specific feedback"],
  },
});

test("maps safe backend events to human-readable activity", () => {
  assert.equal(activityLabelForEvent({ event: "framing_started" }), "Understanding your product...");
  assert.equal(
    activityLabelForEvent({
      event: "research_requested",
      orchestrator_decision: { target_branches: ["DIRECT"] },
    }),
    "Searching direct competitors...",
  );
  assert.equal(
    activityLabelForEvent({
      event: "research_progress",
      research_event: { event: "candidate_validated" },
      research_summary: { passed: 4 },
    }),
    "Found 4 relevant products",
  );
  assert.equal(
    activityLabelForEvent({ event: "orchestration_complete" }),
    "Research complete",
  );
});

test("inserts progressive nodes without moving an existing node", () => {
  let state = createInitialState("My idea");
  state = applyVisualizationDelta(state, {
    upsert_nodes: [productNode("alpha", 4.2, 5.1)],
    remove_node_ids: [],
    upsert_clusters: [],
    remove_cluster_ids: [],
    focus_ring: [],
  });
  const original = { ...state.nodes["node-alpha"] };
  state = applyVisualizationDelta(state, {
    upsert_nodes: [productNode("beta", 7.1, 2.8)],
    remove_node_ids: [],
    upsert_clusters: [],
    remove_cluster_ids: [],
    focus_ring: [],
  });

  assert.deepEqual(state.nodes["node-alpha"], original);
  assert.equal(state.nodes["node-beta"].product_id, "beta");
  assert.equal(state.nodes.user_idea.x, 5);
  assert.equal(state.nodes.user_idea.y, 5);
});

test("retains typed Focus Ring membership and rank", () => {
  const state = applyVisualizationDelta(createInitialState(), {
    upsert_nodes: [productNode("alpha", 4, 4)],
    upsert_clusters: [],
    remove_node_ids: [],
    remove_cluster_ids: [],
    focus_ring: [{ product_id: "alpha", rank: 1, proximity_score: 0.88 }],
  });

  assert.deepEqual(state.focusRing, [{ product_id: "alpha", rank: 1, proximity_score: 0.88 }]);
});

test("selects a product node for its detail panel", () => {
  let state = applyVisualizationDelta(createInitialState(), {
    upsert_nodes: [productNode("alpha", 4, 4)],
    upsert_clusters: [],
    remove_node_ids: [],
    remove_cluster_ids: [],
  });
  state = selectNode(state, "node-alpha");
  assert.equal(state.selectedNodeId, "node-alpha");
  assert.equal(selectNode(state, "missing").selectedNodeId, null);
});

test("compare selection toggles two to four streamed profiles", () => {
  let state = createInitialState();
  for (const id of ["alpha", "beta", "gamma", "delta", "epsilon"]) {
    state = applyAgentEvent(state, {
      event: "intelligence_progress",
      run_status: "ENRICHING",
      intelligence_event: { profile: profile(id) },
    });
    state = toggleCompareProduct(state, id);
  }
  assert.deepEqual(state.compareProductIds, ["alpha", "beta", "gamma", "delta"]);
  assert.equal(comparisonRows(state).length, 4);
  state = toggleCompareProduct(state, "beta");
  assert.deepEqual(state.compareProductIds, ["alpha", "gamma", "delta"]);
});

test("represents initial-ready, enriching, complete, and partial states distinctly", () => {
  let state = createInitialState();
  state = applyAgentEvent(state, { event: "presentation_update", run_status: "INITIAL_READY" });
  assert.equal(statusPresentation(state).tone, "ready");
  state = applyAgentEvent(state, { event: "presentation_update", run_status: "ENRICHING" });
  assert.equal(statusPresentation(state).tone, "enriching");
  state = applyAgentEvent(state, { event: "agent_degraded", run_status: "ENRICHING" });
  assert.equal(statusPresentation(state).tone, "partial");
  state = applyAgentEvent(state, { event: "orchestration_complete", run_status: "COMPLETE" });
  assert.equal(statusPresentation(state).label, "Complete · partial coverage");
});
