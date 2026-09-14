const exportStyles = `
  text { font-family: Inter, Arial, sans-serif; fill: #18263f; }
  #map-grid circle, #map-grid line { fill: none; stroke: #dce3ec; stroke-width: 1; stroke-dasharray: 3 8; }
  #focus-glow { fill: #eff5f3; opacity: .88; }
  #focus-ring { fill: none; stroke: #197a73; stroke-width: 1; opacity: .18; }
  #focus-label { fill: #197a73; font-size: 11px; font-weight: 800; text-anchor: middle; }
  .cluster-region { fill: #edf1f4; stroke: none; opacity: .42; }
  .cluster-label { fill: #84908c; font-size: 10px; font-weight: 800; text-anchor: middle; }
  .cluster-territory.uncategorized { display: none; }
  .map-node.product .node-core { fill: #91a29c; stroke: white; stroke-width: 3; }
  .map-node.focus .node-core { fill: #f25f3a; }
  .map-node.user .node-halo { fill: #dcebe7; }
  .map-node.user .node-core { display: none; }
  .map-node.user .user-star { fill: #197a73; }
  .map-node.user .user-caption { fill: #176b67; font-size: 8px; font-weight: 800; text-anchor: middle; }
  .map-node:not(.user) .user-star, .map-node:not(.user) .user-caption { display: none; }
  .node-label { font-size: 12px; font-weight: 700; paint-order: stroke; stroke: white; stroke-width: 4px; }
  .node-relation { fill: #176b67; font-size: 8px; font-weight: 800; }
`;

export function escapeXml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

export function exportFilename(idea, extension) {
  const slug = idea
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 48) || "market-map";
  return `rivalmap-${slug}.${extension}`;
}

export function buildPresentationSvg(mapMarkup, options) {
  const inner = mapMarkup.replace(/^.*?<svg[^>]*>/s, "").replace(/<\/svg>\s*$/s, "");
  const title = `Competitive Landscape — ${options.title}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900">
    <style>${exportStyles}</style>
    <rect width="1600" height="900" fill="#f8fafc" />
    <rect width="1600" height="6" fill="#197a73" />
    <text x="66" y="52" font-family="Georgia, serif" font-size="28" fill="#18263f">${escapeXml(title)}</text>
    <text x="1534" y="50" text-anchor="end" font-size="11" fill="#647187">USER-CENTERED COMPETITIVE LANDSCAPE</text>
    <svg x="70" y="68" width="1460" height="780" viewBox="0 0 1000 700">${inner}</svg>
    <text x="70" y="874" font-size="10" fill="#7b8682">${escapeXml(options.evidenceNote)}</text>
  </svg>`;
}
