"""Deterministic market-structure builder and renderer-independent base map.

Copied/adapted from MarketCompass frozen baseline ca1356c.
"""

from __future__ import annotations

import hashlib
import re
from itertools import combinations
from typing import Literal
from urllib.parse import urlparse

from .contracts import (
    DegradationLevel,
    EvidenceItem,
    MarketCluster,
    MarketStructure,
    ProductMap,
    ProductMapPoint,
    ProductPosition,
    ProductProfile,
    ProductRelation,
)

_SEPARATORS = (" | ", " - ", " — ", " – ", "：", ":")
_DIRECT_MARKERS = (
    "app",
    "tool",
    "product",
    "platform",
    "assistant",
    "coach",
    "simulator",
    "interview",
    "mock",
    "practice",
    "ai",
    "面试",
    "工具",
    "助手",
    "模拟",
    "练习",
)
_RESEARCH_MARKERS = (
    "journal",
    "doi.org",
    "study",
    "research",
    "paper",
    "article",
    "university",
    "springer",
    "arxiv",
    "学报",
    "论文",
    "研究",
)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _clean_name(title: str, url: str) -> str:
    name = " ".join(title.split()).strip()
    for separator in _SEPARATORS:
        if separator in name:
            name = name.split(separator, 1)[0].strip()
    name = re.sub(r"^\(?PDF\)?\s*", "", name, flags=re.IGNORECASE).strip()
    if not name:
        host = urlparse(url).netloc.replace("www.", "")
        name = host.split(".")[0] if host else "候选产品"
    return name[:52]


def _tags(text: str) -> list[str]:
    lowered = text.casefold()
    tags: list[str] = []
    checks = (
        ("实时辅助", ("real-time", "realtime", "实时", "副驾")),
        ("模拟面试", ("mock interview", "simulated", "simulation", "模拟面试", "模拟")),
        ("语言表达", ("language", "english", "speaking", "语言", "英语", "表达")),
        ("文化语用", ("culture", "cultural", "intercultural", "文化", "语用")),
        ("反馈评分", ("feedback", "rating", "score", "评分", "反馈")),
        ("职业准备", ("career", "employability", "job", "职业", "求职")),
    )
    for tag, markers in checks:
        if any(marker in lowered for marker in markers):
            tags.append(tag)
    return tags or ["候选信号"]


def _directness(
    title: str,
    claim: str,
    url: str,
) -> tuple[Literal["DIRECT", "ADJACENT", "UNKNOWN"], float]:
    text = f"{title} {claim} {url}".casefold()
    direct_hits = sum(marker in text for marker in _DIRECT_MARKERS)
    research_hits = sum(marker in text for marker in _RESEARCH_MARKERS)
    if direct_hits >= 2 and research_hits <= 2:
        return "DIRECT", 0.72
    if direct_hits >= 1:
        return "ADJACENT", 0.58
    return "ADJACENT", 0.46


def _cluster_for_product(product: ProductProfile) -> str:
    if "实时辅助" in product.tags:
        return "实时面试辅助"
    if "文化语用" in product.tags:
        return "文化语用训练"
    if "反馈评分" in product.tags:
        return "反馈与评分"
    if "模拟面试" in product.tags:
        return "模拟面试练习"
    return "相邻研究线索"


def _position_for(product: ProductProfile, index: int) -> tuple[float, float]:
    x = 2.0
    y = 2.0
    if "实时辅助" in product.tags:
        x += 5.4
    elif "模拟面试" in product.tags:
        x += 2.8
    elif "文化语用" in product.tags:
        x += 1.8
    else:
        x += 0.8

    if "反馈评分" in product.tags:
        y += 4.4
    elif "文化语用" in product.tags:
        y += 3.5
    elif "语言表达" in product.tags:
        y += 2.5
    else:
        y += 1.2

    jitter = ((index % 3) - 1) * 0.35
    return (min(max(x + jitter, 0.5), 9.5), min(max(y - jitter, 0.5), 9.5))


def build_market_structure(evidence_items: list[EvidenceItem]) -> MarketStructure:
    products_by_name: dict[str, ProductProfile] = {}

    for item in evidence_items:
        url = str(item.source.url)
        title = item.source.title or item.topic
        name = _clean_name(title, url)
        text = f"{title} {item.claim} {item.evidence_text}"
        tags = _tags(text)
        directness, confidence = _directness(title, item.claim, url)
        existing = products_by_name.get(name.casefold())
        if existing:
            existing.source_evidence_ids.append(item.evidence_id)
            existing.source_urls.append(item.source.url)
            existing.tags = sorted({*existing.tags, *tags})
            existing.confidence = max(existing.confidence, confidence)
            if existing.directness != "DIRECT" and directness == "DIRECT":
                existing.directness = directness
            continue
        products_by_name[name.casefold()] = ProductProfile(
            product_id=_stable_id("product", f"{name}:{url}"),
            name=name,
            description=item.claim[:220],
            source_evidence_ids=[item.evidence_id],
            source_urls=[item.source.url],
            directness=directness,
            confidence=confidence,
            tags=tags,
        )

    products = list(products_by_name.values())[:8]
    cluster_names = sorted({_cluster_for_product(product) for product in products})
    clusters = [
        MarketCluster(
            cluster_id=_stable_id("cluster", name),
            name=name,
            description=f"围绕「{name}」聚合的候选产品或相邻线索。",
            product_ids=[
                product.product_id
                for product in products
                if _cluster_for_product(product) == name
            ],
            confidence=0.62,
        )
        for name in cluster_names
    ]
    cluster_by_name = {cluster.name: cluster.cluster_id for cluster in clusters}
    positions = [
        ProductPosition(
            product_id=product.product_id,
            x=_position_for(product, index)[0],
            y=_position_for(product, index)[1],
            cluster_id=cluster_by_name.get(_cluster_for_product(product)),
            confidence=product.confidence,
        )
        for index, product in enumerate(products)
    ]
    relations = [
        ProductRelation(
            relation_id=_stable_id("relation", f"{left.product_id}:{right.product_id}"),
            source_product_id=left.product_id,
            target_product_id=right.product_id,
            score=round(len(set(left.tags) & set(right.tags)) / 6, 2),
            rationale="两个候选项共享部分标签，因此可作为相邻比较对象。",
        )
        for left, right in combinations(products, 2)
        if set(left.tags) & set(right.tags)
    ][:12]

    if not products:
        level = DegradationLevel.FAILED
        summary = "没有形成可用候选产品结构。"
    elif len(products) < 2:
        level = DegradationLevel.D3
        summary = "只形成了单个候选线索，暂不能稳定比较市场结构。"
    else:
        level = DegradationLevel.D2
        summary = f"已从证据中形成 {len(products)} 个候选产品/线索和 {len(clusters)} 个结构群。"

    return MarketStructure(
        products=products,
        relations=relations,
        clusters=clusters,
        positions=positions,
        degradation_level=level,
        summary=summary,
    )


def product_map_from_structure(structure: MarketStructure) -> ProductMap | None:
    if len(structure.products) < 2:
        return None
    products_by_id = {product.product_id: product for product in structure.products}
    points: list[ProductMapPoint] = []
    for position in structure.positions:
        product = products_by_id.get(position.product_id)
        if product is None:
            continue
        status = "ACTIVE" if product.directness == "DIRECT" else "EXPLORED"
        points.append(
            ProductMapPoint(
                product_name=product.name,
                x=position.x,
                y=position.y,
                segment=next(
                    (
                        cluster.name
                        for cluster in structure.clusters
                        if cluster.cluster_id == position.cluster_id
                    ),
                    "候选线索",
                ),
                evidence_ids=product.source_evidence_ids[:3],
                status=status,
            )
        )
    if len(points) < 2:
        return None
    return ProductMap(
        title="候选市场结构地图",
        x_axis={
            "name": "使用时刻",
            "low_label": "练习前准备",
            "high_label": "实时面试辅助",
            "rationale": "从练习准备到实时辅助，区分产品进入用户流程的位置。",
        },
        y_axis={
            "name": "反馈深度",
            "low_label": "题库/练习",
            "high_label": "文化与表达反馈",
            "rationale": "从简单练习到文化语用和表达反馈，区分产品提供的帮助深度。",
        },
        points=points,
        map_summary=structure.summary,
    )
