"""Concurrent, progressively emitted research waves for RivalMap V1."""

from __future__ import annotations

import hashlib
import time
from collections import deque
from collections.abc import Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Protocol

from .candidate_normalization import candidate_from_evidence, merge_candidates
from .candidate_validation import RuleBasedCandidateValidator
from .contracts import (
    CandidateRecord,
    CandidateValidation,
    EvidenceItem,
    MarketBrief,
    ResearchBatch,
    ResearchBranch,
    ResearchBudget,
    ResearchEvent,
    ResearchEventType,
    ResearchSummary,
    SearchSeed,
)

_BRANCH_ORDER = (
    ResearchBranch.DIRECT,
    ResearchBranch.ADJACENT,
    ResearchBranch.CATEGORY,
    ResearchBranch.ALTERNATIVES,
)


class ResearchSearchService(Protocol):
    def search(
        self,
        query: str,
        *,
        max_results: int,
        timeout_seconds: float,
    ) -> list[EvidenceItem]:
        """Return independently typed evidence for one query."""


class CandidateValidator(Protocol):
    def validate(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> CandidateValidation:
        """Decide candidate admission without judging overall research sufficiency."""


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


class DeterministicResearchPlanner:
    """Create the four bounded V1 research branches without an LLM."""

    def plan(self, brief: MarketBrief) -> list[SearchSeed]:
        context = " ".join(
            part for part in (brief.product_idea, brief.target_user, brief.problem) if part
        )
        exclusions = f" exclude {', '.join(brief.exclusions)}" if brief.exclusions else ""
        queries = {
            ResearchBranch.DIRECT: f"{context} direct competitors products{exclusions}",
            ResearchBranch.ADJACENT: f"{context} adjacent competitor products{exclusions}",
            ResearchBranch.CATEGORY: f"{context} category products companies{exclusions}",
            ResearchBranch.ALTERNATIVES: (
                f"{context} alternative substitute products workflows{exclusions}"
            ),
        }
        return [
            SearchSeed(
                seed_id=_stable_id("seed", f"{branch.value}:{queries[branch]}"),
                query=queries[branch],
                branch=branch,
            )
            for branch in _BRANCH_ORDER
        ]


@dataclass(frozen=True)
class _PendingQuery:
    seed: SearchSeed
    submitted_at: float


class ParallelResearchService:
    """Fan out bounded searches and emit candidates as each branch returns."""

    def __init__(
        self,
        search: ResearchSearchService,
        *,
        budget: ResearchBudget | None = None,
        validator: CandidateValidator | None = None,
        planner: DeterministicResearchPlanner | None = None,
    ) -> None:
        self.search = search
        self.budget = budget or ResearchBudget()
        self.validator = validator or RuleBasedCandidateValidator()
        self.planner = planner or DeterministicResearchPlanner()

    def stream(
        self,
        brief: MarketBrief,
        seeds: Sequence[SearchSeed] | None = None,
    ) -> Iterator[ResearchEvent]:
        selected = list(seeds if seeds is not None else self.planner.plan(brief))
        selected = selected[: self.budget.max_queries_per_wave]
        if not selected:
            return

        wave_identity = "|".join(seed.seed_id for seed in selected)
        batch_id = _stable_id("batch", wave_identity)
        queue = deque(selected)
        pending: dict[Future[list[EvidenceItem]], _PendingQuery] = {}
        evidence_by_id: dict[str, EvidenceItem] = {}
        candidates: dict[str, CandidateRecord] = {}
        validations: dict[str, CandidateValidation] = {}
        covered: set[ResearchBranch] = set()
        queries_completed = 0
        queries_failed = 0
        wave_started = time.monotonic()

        def summary(*, continuing: bool) -> ResearchSummary:
            decisions = [validation.status for validation in validations.values()]
            return ResearchSummary(
                candidates_found=len(candidates),
                passed=decisions.count("PASS"),
                provisional=decisions.count("PROVISIONAL"),
                rejected=decisions.count("REJECT"),
                queries_completed=queries_completed,
                queries_failed=queries_failed,
                search_branches_covered=[
                    branch for branch in _BRANCH_ORDER if branch in covered
                ],
                research_continuing=continuing,
            )

        def batch() -> ResearchBatch:
            admitted_ids = {
                candidate_id
                for candidate_id, validation in validations.items()
                if validation.status in {"PASS", "PROVISIONAL"}
            }
            return ResearchBatch(
                batch_id=batch_id,
                seed=selected[0],
                seeds=selected,
                evidence=sorted(evidence_by_id.values(), key=lambda item: item.evidence_id),
                candidates=sorted(
                    (
                        candidate
                        for candidate_id, candidate in candidates.items()
                        if candidate_id in admitted_ids
                    ),
                    key=lambda candidate: candidate.candidate_id,
                ),
                validations=sorted(
                    (
                        validation
                        for candidate_id, validation in validations.items()
                        if candidate_id in admitted_ids
                    ),
                    key=lambda validation: validation.candidate_id,
                ),
            )

        def submit_available(executor: ThreadPoolExecutor) -> None:
            while queue and len(pending) < self.budget.max_concurrent_searches:
                seed = queue.popleft()
                future = executor.submit(
                    self.search.search,
                    seed.query,
                    max_results=self.budget.max_candidates_per_query,
                    timeout_seconds=self.budget.request_timeout_seconds,
                )
                pending[future] = _PendingQuery(seed=seed, submitted_at=time.monotonic())

        executor = ThreadPoolExecutor(
            max_workers=self.budget.max_concurrent_searches,
            thread_name_prefix="rivalmap-research",
        )
        try:
            submit_available(executor)
            while pending or queue:
                now = time.monotonic()
                ready = {future for future in pending if future.done()}
                if not ready and now - wave_started >= self.budget.wave_timeout_seconds:
                    failed_seeds = [task.seed for task in pending.values()] + list(queue)
                    queries_failed += len(failed_seeds)
                    for future in pending:
                        future.cancel()
                    pending.clear()
                    queue.clear()
                    for seed in failed_seeds:
                        yield ResearchEvent(
                            event=ResearchEventType.RESEARCH_BATCH_UPDATED,
                            branch=seed.branch,
                            batch=batch(),
                            summary=summary(continuing=True),
                            error_code="TIMEOUT",
                        )
                    break

                expired = [
                    future
                    for future, task in pending.items()
                    if not future.done()
                    and now - task.submitted_at >= self.budget.request_timeout_seconds
                ]
                for future in expired:
                    task = pending.pop(future)
                    future.cancel()
                    queries_failed += 1
                    yield ResearchEvent(
                        event=ResearchEventType.RESEARCH_BATCH_UPDATED,
                        branch=task.seed.branch,
                        batch=batch(),
                        summary=summary(continuing=True),
                        error_code="TIMEOUT",
                    )
                submit_available(executor)
                if not pending:
                    continue

                if ready:
                    done = ready
                else:
                    now = time.monotonic()
                    request_deadline = min(
                        task.submitted_at + self.budget.request_timeout_seconds
                        for task in pending.values()
                    )
                    wave_deadline = wave_started + self.budget.wave_timeout_seconds
                    wait_seconds = max(0.0, min(request_deadline, wave_deadline) - now)
                    done, _ = wait(
                        pending,
                        timeout=wait_seconds,
                        return_when=FIRST_COMPLETED,
                    )
                ordered_done = sorted(
                    done,
                    key=lambda future: selected.index(pending[future].seed),
                )
                for future in ordered_done:
                    task = pending.pop(future)
                    try:
                        raw_items = future.result()
                    except Exception:  # noqa: BLE001 - isolate one provider branch
                        queries_failed += 1
                        yield ResearchEvent(
                            event=ResearchEventType.RESEARCH_BATCH_UPDATED,
                            branch=task.seed.branch,
                            batch=batch(),
                            summary=summary(continuing=True),
                            error_code="SEARCH_FAILED",
                        )
                        continue

                    queries_completed += 1
                    covered.add(task.seed.branch)
                    if not isinstance(raw_items, list):
                        raw_items = []
                    for raw_item in raw_items[: self.budget.max_candidates_per_query]:
                        if not isinstance(raw_item, EvidenceItem):
                            continue
                        evidence_by_id[raw_item.evidence_id] = raw_item
                        try:
                            incoming = candidate_from_evidence(raw_item)
                        except ValueError:
                            continue
                        existing = candidates.get(incoming.candidate_id)
                        candidate = (
                            merge_candidates(existing, incoming) if existing else incoming
                        )
                        candidates[candidate.candidate_id] = candidate
                        if existing is None:
                            yield ResearchEvent(
                                event=ResearchEventType.CANDIDATE_FOUND,
                                branch=task.seed.branch,
                                candidate=candidate,
                                summary=summary(continuing=True),
                            )

                        validation = self.validator.validate(
                            candidate,
                            list(evidence_by_id.values()),
                            brief,
                        )
                        validations[candidate.candidate_id] = validation
                        yield ResearchEvent(
                            event=ResearchEventType.CANDIDATE_VALIDATED,
                            branch=task.seed.branch,
                            candidate=candidate,
                            validation=validation,
                            summary=summary(continuing=True),
                        )
                        yield ResearchEvent(
                            event=ResearchEventType.RESEARCH_BATCH_UPDATED,
                            branch=task.seed.branch,
                            batch=batch(),
                            summary=summary(continuing=True),
                        )
                    yield ResearchEvent(
                        event=ResearchEventType.RESEARCH_BATCH_UPDATED,
                        branch=task.seed.branch,
                        batch=batch(),
                        summary=summary(continuing=True),
                    )
                submit_available(executor)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        yield ResearchEvent(
            event=ResearchEventType.RESEARCH_WAVE_COMPLETE,
            batch=batch(),
            summary=summary(continuing=False),
        )
