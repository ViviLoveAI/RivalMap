import assert from "node:assert/strict";
import test from "node:test";

import {
  activityLabelForEvent,
  answerFramingQuestion,
  applyAgentEvent,
  applyVisualizationDelta,
  comparisonModel,
  comparisonRows,
  concisePresentationInsight,
  productDetailModel,
  currentPresentationData,
  safeSourceUrl,
  createFramingState,
  createInitialState,
  focusZoneState,
  layoutMapLabels,
  softClusterTerritoryPath,
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
    relationship: "DIRECT",
    confidence: 0.82,
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
    null,
  );
  assert.equal(
    activityLabelForEvent({
      event: "research_progress",
      research_event: { event: "candidate_validated" },
      research_summary: { passed: 5 },
    }),
    "✓ 5 relevant products mapped",
  );
  assert.equal(
    activityLabelForEvent({ event: "orchestration_complete" }),
    "Research complete",
  );
  assert.equal(
    activityLabelForEvent({
      event: "presentation_update",
      run_status: "INITIAL_READY",
      visualization_delta: { focus_ring: [] },
    }),
    "✓ Adjacent market mapped",
  );
  assert.equal(
    activityLabelForEvent({
      event: "presentation_update",
      run_status: "INITIAL_READY",
      visualization_delta: { focus_ring: [{ product_id: "alpha", rank: 1 }] },
    }),
    "✓ Competitive space identified",
  );
});

test("open Focus state removes a stale competitive-space milestone", () => {
  const state = {
    ...createInitialState("My idea"),
    activities: ["Searching direct competitors...", "✓ Competitive space identified"],
  };
  const next = applyAgentEvent(state, {
    event: "presentation_update",
    run_status: "ENRICHING",
    visualization_delta: {
      upsert_nodes: [],
      remove_node_ids: [],
      upsert_clusters: [],
      remove_cluster_ids: [],
      focus_ring: [],
    },
  });

  assert.deepEqual(next.focusRing, []);
  assert.equal(next.activities.includes("✓ Competitive space identified"), false);
  assert.equal(next.activities.at(-1), "✓ Adjacent market mapped");
});

test("asks one framing question at a time and starts research before optional refinement", () => {
  let framing = createFramingState();
  assert.equal(framing.step, 0);
  framing = answerFramingQuestion(framing, "AI interview coach");
  assert.equal(framing.step, 1);
  assert.equal(framing.researchStarted, false);
  framing = answerFramingQuestion(framing, "Practice and feedback");
  assert.equal(framing.step, 2);
  framing = answerFramingQuestion(framing, "Job seekers");
  assert.equal(framing.step, 3);
  assert.equal(framing.researchStarted, true);
  assert.equal(framing.complete, false);
  framing = answerFramingQuestion(framing, "Recruiting suites");
  assert.equal(framing.complete, true);
  assert.equal(framing.researchStarted, true);
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

test("maps evidence-backed structured and semantic profile fields into anchored comparison", () => {
  let state = createInitialState("AI interview coach");
  state.marketBrief = {
    product_idea: "AI interview coach",
    target_user: "Job seekers",
    problem: "Practice interviews and receive feedback",
  };
  for (const id of ["alpha", "beta"]) {
    state = applyAgentEvent(state, {
      event: "intelligence_progress",
      run_status: "ENRICHING",
      intelligence_event: { profile: profile(id) },
    });
    state = toggleCompareProduct(state, id);
  }
  const model = comparisonModel(state);

  assert.equal(model.columns[0].name, "YOUR IDEA");
  assert.equal(model.columns[0].targetCustomer.text, "Job seekers");
  assert.equal(model.rivals[0].targetCustomer.text, "Job seekers");
  assert.equal(model.rivals[0].workflow.text, "Practice, Feedback");
  assert.equal(model.rivals[0].capabilities.text, "Mock interviews");
  assert.equal(model.rivals[0].pricing.text, "Subscription");
  assert.equal(model.rivals[0].positioning.text, "Interview practice");
  assert.match(model.rivals[0].differentiation.text, /Role-specific feedback/);
  assert.match(model.synthesis.strategicTakeaway, /selected rivals compete directly/);
  assert.ok(model.synthesis.strategicTakeaway.split(/(?<=[.!?])\s+/).length <= 3);
});

test("omits unsupported comparison dimensions without fabricating values", () => {
  let state = createInitialState("My idea");
  const sparse = profile("sparse");
  sparse.structured_facts = { source_evidence_ids: ["ev-sparse"], confidence: 0.4 };
  sparse.semantic_analysis = {
    relevance_to_brief: "Evidence supports category relevance.",
    relationship: "UNKNOWN",
    source_evidence_ids: ["ev-sparse"],
    confidence: 0.4,
  };
  state = applyAgentEvent(state, {
    event: "intelligence_progress",
    run_status: "ENRICHING",
    intelligence_event: { profile: sparse },
  });
  state = toggleCompareProduct(state, "sparse");
  const model = comparisonModel(state);

  assert.equal(model.rivals[0].pricing, null);
  assert.equal(model.rivals[0].relationship, null);
  assert.ok(model.omitted.includes("Pricing signal"));
  assert.ok(!JSON.stringify(model).includes("Unknown"));
});

test("represents strong, emerging, and empty focus zones without changing membership", () => {
  const empty = createInitialState();
  assert.equal(focusZoneState(empty).kind, "empty");
  const emerging = { ...empty, focusRing: [{ product_id: "alpha", rank: 1 }] };
  assert.equal(focusZoneState(emerging).kind, "emerging");
  const strong = {
    ...empty,
    focusRing: ["alpha", "beta", "gamma"].map((id, index) => ({ product_id: id, rank: index + 1 })),
  };
  assert.equal(focusZoneState(strong).kind, "strong");
  assert.deepEqual(strong.focusRing, ["alpha", "beta", "gamma"].map((id, index) => ({ product_id: id, rank: index + 1 })));
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

test("research evidence and early analysis survive through detail and later profile updates", () => {
  let state = applyVisualizationDelta(createInitialState("Coach"), { upsert_nodes: [productNode("alpha", 4, 4)] });
  state = selectNode(state, "node-alpha");
  state = applyAgentEvent(state, { research_event: { batch: {
    evidence: [{ evidence_id: "ev-alpha", claim: "Practice with feedback", source: { url: "https://alpha.example", title: "Alpha product" } }],
    validations: [{ candidate_id: "candidate-alpha", status: "PROVISIONAL", source_quality: "PRIMARY", evidence_coverage: 1 }],
  } } });
  state = applyAgentEvent(state, { intelligence_event: { candidate_id: "candidate-alpha", structured_facts: {
    features: ["Early feedback"], source_evidence_ids: ["ev-alpha"], field_evidence_ids: { features: ["ev-alpha"] },
  } } });
  assert.ok(productDetailModel(state, state.nodes["node-alpha"]).rows.some(row => row.text === "Early feedback"));
  const enriched = { ...profile("alpha"), candidate_id: "candidate-alpha", source_evidence_ids: ["ev-alpha"],
    uncertainties: ["Limited coverage"], analysis_status: "PARTIAL" };
  enriched.structured_facts.integrations = ["Calendar"];
  enriched.semantic_analysis.uncertainties = ["Pricing not confirmed"];
  state = applyAgentEvent(state, { intelligence_event: { profile: enriched } });
  const detail = productDetailModel(state, state.nodes["node-alpha"]);
  assert.equal(state.selectedNodeId, "node-alpha");
  assert.equal(detail.sources[0].title, "Alpha product");
  assert.ok(detail.rows.some(row => row.text === "Calendar"));
  assert.ok(!detail.rows.some(row => row.text === "Early feedback"));
  assert.ok(detail.rows.some(row => row.label === "Uncertainty" && row.text.includes("Pricing evidence limited")));
  assert.equal(state.degraded, true);
  assert.equal(safeSourceUrl("javascript:alert(1)"), null);
  assert.equal(safeSourceUrl("bad-url"), null);
});

test("comparison uses path-specific provenance and backend ranking without inferring overlap from field presence", () => {
  const state = createInitialState("Coach");
  state.profiles.alpha = profile("alpha");
  state.profiles.alpha.structured_facts.source_evidence_ids = ["structured"];
  state.profiles.alpha.semantic_analysis.source_evidence_ids = ["semantic"];
  state.compareProductIds = ["alpha"];
  let model = comparisonModel(state);
  assert.deepEqual(model.rivals[0].targetCustomer.evidenceIds, ["structured"]);
  assert.deepEqual(model.rivals[0].overlap.evidenceIds, ["semantic"]);
  assert.match(model.synthesis.closestOverlap, /does not establish/);
  state.nodes["node-alpha"] = { ...productNode("alpha", 4, 4), similarity_to_user: 0.81 };
  model = comparisonModel(state);
  assert.match(model.synthesis.closestOverlap, /highest existing mapped similarity.*81%/);
  state.focusRing = [{ product_id: "alpha", rank: 1 }];
  model = comparisonModel(state);
  assert.match(model.synthesis.closestOverlap, /Solves the same/);
  assert.doesNotMatch(model.synthesis.closestOverlap, /overlap in customer/);
  assert.equal(model.columns[0].workflow, null);
});

test("presentation and export reuse backend insights and count unique sources", () => {
  const state = createInitialState("Coach");
  state.profiles.alpha = { ...profile("alpha"), source_evidence_ids: ["ev-a"] };
  state.profiles.beta = { ...profile("beta"), source_evidence_ids: ["ev-b"], source_urls: ["https://alpha.example"] };
  state.evidence = {
    "ev-a": { source: { source_id: "source-a", url: "https://alpha.example" } },
    "ev-b": { source: { source_id: "source-b", url: "https://alpha.example" } },
  };
  state.presentation.closest_rivals = ["Backend interpretation"];
  const result = currentPresentationData(state);
  assert.equal(result.presentation, state.presentation);
  assert.match(result.evidenceNote, /0 products mapped · 2 validated · 1 unique sources · 2 evidence references/);
});

test("latest streamed MarketBrief replaces earlier local context", () => {
  let state = createInitialState("Initial idea");
  state = applyAgentEvent(state, { market_brief: {
    product_idea: "Refined idea", target_user: "Independent job seekers", problem: "Improve answers",
    exclusions: ["Recruiting suites"], competitive_scope: "Consumer coaching",
  } });
  assert.equal(state.marketBriefStreamed, true);
  assert.equal(state.marketBrief.product_idea, "Refined idea");
  assert.equal(state.marketBrief.competitive_scope, "Consumer coaching");
  assert.deepEqual(state.marketBrief.exclusions, ["Recruiting suites"]);
});

test("label layout keeps focus labels visible and hides crowded context first", () => {
  const originalPoints = Array.from({ length: 5 }, (_, index) => ({ x: 500 + index % 2, y: 350 + index % 3 }));
  const layouts = layoutMapLabels([
    ...originalPoints.map((point, index) => ({
      nodeId: `focus-${index}`,
      point,
      label: `Priority focus product ${index} with a long name`,
      priority: 1,
      focusRank: index + 1,
      hasRelation: true,
    })),
    { nodeId: "context", point: { x: 501, y: 351 }, label: "Broader context product", priority: 3 },
  ]);

  assert.equal(Object.values(layouts).filter(layout => layout.priority === 1).every(layout => !layout.hidden), true);
  assert.equal(layouts.context.hidden, true);
  assert.deepEqual(originalPoints, Array.from({ length: 5 }, (_, index) => ({ x: 500 + index % 2, y: 350 + index % 3 })));
});

test("label layout switches anchors without overlapping visible labels", () => {
  const layouts = layoutMapLabels([
    { nodeId: "first", point: { x: 420, y: 300 }, label: "First nearby product", priority: 1, focusRank: 1 },
    { nodeId: "second", point: { x: 424, y: 302 }, label: "Second nearby product", priority: 1, focusRank: 2 },
  ]);
  const first = layouts.first.box;
  const second = layouts.second.box;
  const overlaps = first.left < second.right + 5 && first.right + 5 > second.left
    && first.top < second.bottom + 5 && first.bottom + 5 > second.top;

  assert.equal(layouts.first.hidden, false);
  assert.equal(layouts.second.hidden, false);
  assert.equal(overlaps, false);
  assert.notDeepEqual(
    { x: layouts.first.x, y: layouts.first.y, anchor: layouts.first.anchor },
    { x: layouts.second.x, y: layouts.second.y, anchor: layouts.second.anchor },
  );
});

test("product detail removes markdown, diagnostics, schema names, and broken scrape fragments", () => {
  const state = createInitialState("Interview coach");
  state.nodes["node-alpha"] = productNode("alpha", 4, 4);
  state.profiles.alpha = {
    ...profile("alpha"),
    name: "#1 AI Interview Prep & Coaching.",
    analysis_status: "PARTIAL",
    source_evidence_ids: ["ev-alpha"],
    uncertainties: [
      "Missing structured field: business_model",
      "Missing structured field: target_users",
      "Semantic analysis path was unavailable.",
    ],
    structured_facts: {
      confidence: 0.65,
      primary_use_case: "AI-Powered Interview Prep ... ## #1 AI Interview Prep & Coaching. ... Practice with a realistic AI mock interview tailored to your resume and role. ... AI mock interview practice in j",
      missing_fields: ["business_model", "target_users", "integrations", "pricing_signals"],
      source_evidence_ids: ["ev-alpha"],
    },
    semantic_analysis: null,
  };
  state.evidence["ev-alpha"] = {
    evidence_id: "ev-alpha",
    claim: "Practice interviews with role-specific feedback.",
    source: { title: "## AI Interview Prep", url: "https://alpha.example/product" },
  };

  const detail = productDetailModel(state, state.nodes["node-alpha"]);
  const rendered = JSON.stringify(detail.rows);
  assert.equal(detail.name, "AI Interview Prep & Coaching.");
  assert.equal(rendered.includes("#"), false);
  assert.equal(rendered.includes("business_model"), false);
  assert.equal(rendered.includes("target_users"), false);
  assert.equal(rendered.includes("analysis path was unavailable"), false);
  assert.equal(rendered.includes("in j"), false);
  assert.ok(detail.rows.some(row => row.label === "Primary use case" && row.text.includes("realistic AI mock interview")));
  assert.ok(detail.rows.some(row => row.label === "Evidence gaps" && row.text.includes("Business model")));
  assert.ok(detail.rows.some(row => row.label === "Uncertainty" && row.text.includes("Semantic analysis partial")));
  assert.ok(detail.rows.some(row => row.label === "Profile status" && row.text.includes("some attributes are still being verified")));
  assert.equal(detail.sources[0].url, "https://alpha.example/product");
  assert.equal(detail.sources[0].title, "AI Interview Prep");
  assert.equal(detail.sources[0].claim, "Practice interviews with role-specific feedback.");
});

test("presentation insight is concise and removes markdown artifacts", () => {
  const result = concisePresentationInsight([
    "## **JobSearch.Coach** targets interview preparation. This second paragraph should not appear in the slide and contains much more detail.",
  ]);
  assert.equal(result, "JobSearch.Coach targets interview preparation.");
  assert.equal(result.includes("**"), false);
  assert.ok(result.length < 190);
});

test("cluster territory hint is deterministic and not a regular circle", () => {
  const first = softClusterTerritoryPath({ x: 420, y: 310 }, 90, "cluster-interview");
  const second = softClusterTerritoryPath({ x: 420, y: 310 }, 90, "cluster-interview");
  assert.equal(first, second);
  assert.match(first, /^M /);
  assert.match(first, / Q /);
  assert.doesNotMatch(first, / A |<circle/);
});
