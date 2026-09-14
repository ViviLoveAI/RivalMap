import assert from "node:assert/strict";
import test from "node:test";

import { buildPresentationSvg, exportFilename } from "./export.js";

test("generates a presentation SVG with map, insights, and evidence note", () => {
  const result = buildPresentationSvg('<svg viewBox="0 0 1000 700"><circle id="focus-ring" /></svg>', {
    title: "AI interview coach",
    presentation: {
      closest_rivals: ["## **Alpha** is the closest rival. Extra detail should be omitted."],
      your_differentiation: ["Deeper feedback"],
      opportunity_around_you: ["Role-specific practice"],
    },
    evidenceNote: "3 evidence-linked profiles",
  });

  assert.match(result, /Competitive Landscape — AI interview coach/);
  assert.match(result, /width="1600" height="900"/);
  assert.match(result, /focus-ring/);
  assert.doesNotMatch(result, /CLOSEST RIVALS|Alpha is the closest rival|\*\*|##|Extra detail/);
  assert.match(result, /3 evidence-linked profiles/);
  assert.doesNotMatch(result, /<script/);
});

test("creates safe predictable export filenames", () => {
  assert.equal(exportFilename("AI Interview Coach!", "png"), "rivalmap-ai-interview-coach.png");
});
