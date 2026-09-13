"""Deterministic candidate normalization for research results."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from .contracts import CandidateRecord, EvidenceItem

_TITLE_SEPARATORS = (" | ", " - ", " — ", " – ", "：", ":")
_GENERIC_TITLES = {"home", "homepage", "official site", "website", "product"}


def normalize_domain(url: str) -> str:
    host = (urlsplit(url).hostname or "").casefold().strip(".")
    return host.removeprefix("www.")


def normalize_url(url: str) -> str:
    parsed = urlsplit(url)
    domain = normalize_domain(url)
    scheme = parsed.scheme.casefold() or "https"
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/")
    return urlunsplit((scheme, domain, path, "", ""))


def normalize_name(title: str, domain: str) -> str:
    name = " ".join(title.split()).strip()
    for separator in _TITLE_SEPARATORS:
        if separator in name:
            name = name.split(separator, 1)[0].strip()
    name = re.sub(r"^(official|welcome to)\s+", "", name, flags=re.IGNORECASE)
    if not name or name.casefold() in _GENERIC_TITLES:
        name = domain.split(".", 1)[0].replace("-", " ")
    return name[:80].strip().title() if name.islower() else name[:80].strip()


def stable_candidate_id(name: str, domain: str) -> str:
    identity = f"{domain.casefold()}|{' '.join(name.casefold().split())}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"candidate_{digest}"


def candidate_from_evidence(item: EvidenceItem) -> CandidateRecord:
    url = str(item.source.url)
    domain = normalize_domain(url)
    if not domain:
        raise ValueError("candidate source URL has no domain")
    source_title = item.source.title or item.topic
    name = normalize_name(source_title, domain)
    if not name:
        raise ValueError("candidate has no usable name")
    canonical_url = normalize_url(url)
    return CandidateRecord(
        candidate_id=stable_candidate_id(name, domain),
        name=name,
        description=item.claim[:240],
        source_evidence_ids=[item.evidence_id],
        canonical_url=canonical_url,
        domain=domain,
        name_variants=[source_title] if source_title != name else [],
    )


def merge_candidates(existing: CandidateRecord, incoming: CandidateRecord) -> CandidateRecord:
    if existing.candidate_id != incoming.candidate_id:
        raise ValueError("cannot merge candidates with different identities")
    evidence_ids = sorted({*existing.source_evidence_ids, *incoming.source_evidence_ids})
    variants = sorted(
        {
            *existing.name_variants,
            *incoming.name_variants,
            existing.name,
            incoming.name,
        }
        - {existing.name}
    )
    description = max(
        (existing.description, incoming.description),
        key=lambda value: (len(value), value),
    )
    urls = [url for url in (existing.canonical_url, incoming.canonical_url) if url is not None]
    canonical_url = min(urls, key=lambda url: (len(str(url)), str(url))) if urls else None
    return existing.model_copy(
        update={
            "description": description,
            "source_evidence_ids": evidence_ids,
            "name_variants": variants,
            "canonical_url": canonical_url,
        }
    )
