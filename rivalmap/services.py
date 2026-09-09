"""Standalone RivalMap services."""

from __future__ import annotations

from .contracts import AnalysisResult, EvidenceItem, MarketStructure, RivalMapRequest


class DeterministicAnalysisService:
    """Small baseline analysis that never calls a model.

    This keeps the extracted runtime independently testable. Strands/Bedrock/LLM
    enrichment belongs to later slices and should plug in through this boundary.
    """

    def analyze(
        self,
        request: RivalMapRequest,
        evidence: list[EvidenceItem],
        structure: MarketStructure | None,
    ) -> AnalysisResult | None:
        if structure is None or not structure.products:
            return None
        direct = [item.name for item in structure.products if item.directness == "DIRECT"]
        adjacent = [item.name for item in structure.products if item.directness != "DIRECT"]
        meaning = []
        if direct:
            meaning.append(f"直接竞品候选包括：{'、'.join(direct[:4])}。")
        if adjacent:
            meaning.append(f"相邻线索包括：{'、'.join(adjacent[:4])}。")
        if not meaning:
            meaning.append("当前证据主要形成候选市场轮廓，仍需要更多来源确认。")
        clusters = "、".join(cluster.name for cluster in structure.clusters[:4])
        return AnalysisResult(
            summary=(
                f"围绕「{request.idea}」已形成 {len(structure.products)} 个候选对象。"
                + (f"初步聚合在：{clusters}。" if clusters else "")
            ),
            market_meaning=meaning,
            differentiators=[
                "当前差异主要来自使用时刻、反馈深度和是否贴近实时任务。"
            ],
            opportunity_hypotheses=[
                "下一步应验证哪些候选是真实产品、哪些只是相邻需求信号。"
            ],
        )
