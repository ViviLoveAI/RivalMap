"""Exa discovery adapter for RivalMap standalone runtime."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from ..contracts import EvidenceItem, EvidenceRelation, RivalMapRequest, Source, SourceQuality


class ExaDiscoveryService:
    endpoint = "https://api.exa.ai/search"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        search_type: str | None = None,
        timeout_seconds: float | None = None,
        max_results: int | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("EXA_API_KEY", "")
        self.search_type = search_type or os.getenv("EXA_SEARCH_TYPE", "fast")
        self.timeout_seconds = timeout_seconds or float(os.getenv("EXA_TIMEOUT_SECONDS", "8"))
        configured_max = os.getenv("EXA_MAX_RESULTS")
        self.max_results = max_results or (int(configured_max) if configured_max else None)

    def discover(self, request: RivalMapRequest) -> list[EvidenceItem]:
        return self.search(
            request.query_text,
            max_results=self.max_results or request.max_results,
            timeout_seconds=self.timeout_seconds,
        )

    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_seconds: float,
    ) -> list[EvidenceItem]:
        """Run one independently budgeted Exa query for research fan-out."""

        if not self.api_key:
            raise RuntimeError("Exa Search authentication is not configured.")
        payload = {
            "query": query,
            "type": self.search_type,
            "numResults": max_results,
            "contents": {"highlights": True},
        }
        http_request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except TimeoutError as exc:
            raise TimeoutError(
                f"Exa Search 请求超时：{timeout_seconds:.0f} 秒内未返回。"
            ) from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Exa Search 请求失败：HTTP {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason).casefold():
                raise TimeoutError(
                    f"Exa Search 请求超时：{timeout_seconds:.0f} 秒内未返回。"
                ) from exc
            raise RuntimeError(f"Exa Search 暂时不可用：{exc.reason}") from exc

        data = json.loads(raw)
        evidence: list[EvidenceItem] = []
        for result in data.get("results", []):
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            if not isinstance(url, str) or not url.strip():
                continue
            title = str(result.get("title") or url)
            highlights = result.get("highlights")
            snippets = (
                [item.strip() for item in highlights if isinstance(item, str) and item.strip()]
                if isinstance(highlights, list)
                else []
            )
            fallback_text = str(result.get("text") or result.get("summary") or "").strip()
            evidence_text = "\n".join(snippets) or fallback_text or title
            claim = snippets[0] if snippets else title
            score = result.get("score")
            confidence = 0.65
            if isinstance(score, int | float):
                confidence = max(0.4, min(float(score), 0.95))
            try:
                evidence.append(
                    EvidenceItem(
                        topic=f"search:{title}",
                        claim=claim,
                        source=Source(url=url, title=title, quality=SourceQuality.UNKNOWN),
                        evidence_text=evidence_text,
                        relation=EvidenceRelation.CONTEXT,
                        confidence=confidence,
                        inferred=False,
                    )
                )
            except ValueError:
                continue
        return evidence
