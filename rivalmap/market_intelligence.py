"""Parallel per-candidate market-intelligence analysis and deterministic fusion."""

from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Literal, Protocol

from pydantic import ValidationError

from .contracts import (
    AnalysisBudget,
    CandidateRecord,
    CandidateValidation,
    EnrichedProductProfile,
    EvidenceItem,
    IntelligenceEvent,
    IntelligenceEventType,
    MarketBrief,
    ResearchBatch,
    SemanticProductAnalysis,
    StructuredProductFacts,
)
from .model_router import ModelRouter

_STRUCTURED_FIELDS = (
    "company_name",
    "positioning",
    "target_users",
    "product_category",
    "primary_use_case",
    "features",
    "workflow_coverage",
    "pricing_signals",
    "integrations",
    "business_model",
)


def product_id_for_candidate(candidate_id: str) -> str:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return f"product_{digest}"


class StructuredProductAnalyzer(Protocol):
    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
    ) -> StructuredProductFacts:
        """Extract evidence-backed product facts for one candidate."""


class SemanticProductAnalyzer(Protocol):
    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> SemanticProductAnalysis:
        """Interpret one candidate relative to the market brief."""


@dataclass(frozen=True)
class CandidateIntelligenceInput:
    candidate: CandidateRecord
    validation: CandidateValidation
    evidence: tuple[EvidenceItem, ...]

    def __post_init__(self) -> None:
        if self.validation.candidate_id != self.candidate.candidate_id:
            raise ValueError("candidate validation must match candidate")
        evidence_ids = {item.evidence_id for item in self.evidence}
        if not set(self.candidate.source_evidence_ids).issubset(evidence_ids):
            raise ValueError("candidate evidence must be present in intelligence input")
        if not set(self.validation.source_evidence_ids).issubset(evidence_ids):
            raise ValueError("validation evidence must be present in intelligence input")
        if not set(self.validation.source_evidence_ids).issubset(
            self.candidate.source_evidence_ids
        ):
            raise ValueError("validation evidence must belong to the candidate")
        if self.validation.status == "REJECT":
            raise ValueError("rejected candidates cannot enter market intelligence")


class ConservativeStructuredAnalyzer:
    """Evidence-only fallback that leaves unobserved structured fields missing."""

    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
    ) -> StructuredProductFacts:
        evidence_ids = sorted(item.evidence_id for item in evidence)
        primary_use_case = candidate.description or None
        observed = {
            "product_name": evidence_ids,
            "canonical_url": evidence_ids,
        }
        if primary_use_case:
            observed["primary_use_case"] = evidence_ids
        missing = [field_name for field_name in _STRUCTURED_FIELDS if field_name not in observed]
        confidence = sum(item.confidence for item in evidence) / len(evidence)
        return StructuredProductFacts(
            product_id=product_id_for_candidate(candidate.candidate_id),
            product_name=candidate.name,
            canonical_url=candidate.canonical_url,
            primary_use_case=primary_use_case,
            source_evidence_ids=evidence_ids,
            field_evidence_ids=observed,
            confidence=round(confidence, 3),
            missing_fields=missing,
        )


class ConservativeSemanticAnalyzer:
    """Safe fallback that records relevance but abstains from market classification."""

    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> SemanticProductAnalysis:
        evidence_ids = sorted(item.evidence_id for item in evidence)
        return SemanticProductAnalysis(
            product_id=product_id_for_candidate(candidate.candidate_id),
            relationship="UNKNOWN",
            problem_solved=candidate.description or None,
            relevance_to_brief=(
                f"Evidence-backed candidate for the market brief '{brief.product_idea}'; "
                "relationship classification remains uncertain."
            ),
            uncertainties=[
                "Direct, adjacent, or alternative relationship requires semantic review."
            ],
            source_evidence_ids=evidence_ids,
            confidence=0.4,
        )


@dataclass(frozen=True)
class RoutedStructuredAnalyzer:
    router: ModelRouter

    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
    ) -> StructuredProductFacts:
        return self.router.generate(
            StructuredProductFacts,
            system=(
                "Extract only facts directly supported by the supplied evidence. "
                "Use missing_fields for unknown values and cite evidence IDs."
            ),
            payload={
                "candidate": candidate.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
            task="rivalmap_structured_product_analysis",
        )


@dataclass(frozen=True)
class RoutedSemanticAnalyzer:
    router: ModelRouter

    def analyze(
        self,
        candidate: CandidateRecord,
        evidence: list[EvidenceItem],
        brief: MarketBrief,
    ) -> SemanticProductAnalysis:
        return self.router.generate(
            SemanticProductAnalysis,
            system=(
                "Analyze the candidate relative to the market brief using only supplied "
                "evidence. Return conclusions, not hidden reasoning, and cite evidence IDs."
            ),
            payload={
                "brief": brief.model_dump(mode="json"),
                "candidate": candidate.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
            task="rivalmap_semantic_product_analysis",
        )


class InvalidAnalysisOutput(ValueError):
    """Provider output conflicts with candidate identity or available provenance."""


def _validate_output(
    output: StructuredProductFacts | SemanticProductAnalysis,
    *,
    product_id: str,
    evidence_ids: set[str],
) -> None:
    if output.product_id != product_id:
        raise InvalidAnalysisOutput("analysis product_id does not match candidate")
    if not set(output.source_evidence_ids).issubset(evidence_ids):
        raise InvalidAnalysisOutput("analysis cites evidence outside the candidate record")


class ProductProfileFusion:
    """Fuse independent paths without flattening or overriding their claims."""

    def fuse(
        self,
        item: CandidateIntelligenceInput,
        structured: StructuredProductFacts | None,
        semantic: SemanticProductAnalysis | None,
    ) -> EnrichedProductProfile:
        candidate = item.candidate
        evidence = list(item.evidence)
        structured_available = structured is not None
        semantic_available = semantic is not None
        product_id = product_id_for_candidate(candidate.candidate_id)
        available_evidence_ids = {evidence_item.evidence_id for evidence_item in evidence}
        if structured is not None:
            _validate_output(
                structured,
                product_id=product_id,
                evidence_ids=available_evidence_ids,
            )
        if semantic is not None:
            _validate_output(
                semantic,
                product_id=product_id,
                evidence_ids=available_evidence_ids,
            )
        evidence_ids = sorted(
            {
                *candidate.source_evidence_ids,
                *item.validation.source_evidence_ids,
                *(structured.source_evidence_ids if structured else []),
                *(semantic.source_evidence_ids if semantic else []),
            }
        )
        uncertainties: set[str] = set()
        if structured is None:
            field_evidence_ids = {
                "product_name": sorted(candidate.source_evidence_ids),
            }
            if candidate.canonical_url is not None:
                field_evidence_ids["canonical_url"] = sorted(candidate.source_evidence_ids)
            if candidate.description:
                field_evidence_ids["primary_use_case"] = sorted(
                    candidate.source_evidence_ids
                )
            missing_fields = [
                field_name
                for field_name in _STRUCTURED_FIELDS
                if field_name not in field_evidence_ids
            ]
            structured = StructuredProductFacts(
                product_id=product_id,
                product_name=candidate.name,
                canonical_url=candidate.canonical_url,
                primary_use_case=candidate.description or None,
                source_evidence_ids=sorted(candidate.source_evidence_ids),
                field_evidence_ids=field_evidence_ids,
                confidence=item.validation.identity_confidence,
                missing_fields=missing_fields,
            )
            uncertainties.add("Structured analysis path was unavailable.")
        if semantic is None:
            uncertainties.add("Semantic analysis path was unavailable.")
        else:
            uncertainties.update(semantic.uncertainties)
        uncertainties.update(f"Missing structured field: {name}" for name in structured.missing_fields)

        field_origins: dict[str, list[Literal["STRUCTURED", "SEMANTIC", "VALIDATION"]]] = {
            "candidate_validation": ["VALIDATION"],
            "structured_facts": [
                "STRUCTURED" if structured_available else "VALIDATION"
            ],
        }
        if semantic is not None:
            field_origins["semantic_analysis"] = ["SEMANTIC"]
        if (
            semantic
            and structured.positioning
            and semantic.positioning
            and structured.positioning.casefold() != semantic.positioning.casefold()
        ):
            field_origins["positioning"] = ["STRUCTURED", "SEMANTIC"]
            uncertainties.add("Structured and semantic positioning claims differ.")

        confidence_values = [item.validation.identity_confidence, structured.confidence]
        if semantic is not None:
            confidence_values.append(semantic.confidence)
        directness = semantic.directness if semantic else "UNKNOWN"
        if semantic and semantic.relationship == "ALTERNATIVE":
            directness = "ADJACENT"
        source_urls = sorted(
            {
                str(evidence_item.source.url)
                for evidence_item in evidence
                if evidence_item.evidence_id in evidence_ids
            },
        )
        tags = []
        if structured.product_category:
            tags.append(structured.product_category)
        if semantic and semantic.relationship != "UNKNOWN":
            tags.append(semantic.relationship)
        return EnrichedProductProfile(
            product_id=product_id,
            candidate_id=candidate.candidate_id,
            name=candidate.name,
            description=candidate.description or f"Evidence-backed candidate: {candidate.name}",
            source_evidence_ids=evidence_ids,
            source_urls=source_urls,
            directness=directness,
            confidence=round(sum(confidence_values) / len(confidence_values), 3),
            tags=tags,
            structured_facts=structured,
            semantic_analysis=semantic,
            candidate_validation=item.validation,
            analysis_status=(
                "COMPLETE" if structured_available and semantic_available else "PARTIAL"
            ),
            field_origins=field_origins,
            uncertainties=sorted(uncertainties),
        )


@dataclass
class _CandidateState:
    item: CandidateIntelligenceInput
    structured: StructuredProductFacts | None = None
    semantic: SemanticProductAnalysis | None = None
    structured_done: bool = False
    semantic_done: bool = False
    failed_paths: list[Literal["STRUCTURED", "SEMANTIC"]] = field(default_factory=list)
    failure_codes: list[Literal["PROVIDER_FAILED", "INVALID_OUTPUT"]] = field(
        default_factory=list
    )


class MarketIntelligenceService:
    """Run both analysis paths per candidate and stream completed profiles."""

    def __init__(
        self,
        structured: StructuredProductAnalyzer | None = None,
        semantic: SemanticProductAnalyzer | None = None,
        *,
        fusion: ProductProfileFusion | None = None,
        budget: AnalysisBudget | None = None,
    ) -> None:
        self.structured = structured or ConservativeStructuredAnalyzer()
        self.semantic = semantic or ConservativeSemanticAnalyzer()
        self.fusion = fusion or ProductProfileFusion()
        self.budget = budget or AnalysisBudget()

    @classmethod
    def from_router(
        cls,
        router: ModelRouter,
        *,
        budget: AnalysisBudget | None = None,
    ) -> MarketIntelligenceService:
        return cls(
            RoutedStructuredAnalyzer(router),
            RoutedSemanticAnalyzer(router),
            budget=budget,
        )

    def inputs_from_batch(
        self,
        batch: ResearchBatch,
        *,
        selected_provisional_ids: set[str] | None = None,
    ) -> list[CandidateIntelligenceInput]:
        selected_provisional_ids = selected_provisional_ids or set()
        validation_by_id = {
            validation.candidate_id: validation for validation in batch.validations
        }
        evidence_by_id = {item.evidence_id: item for item in batch.evidence}
        inputs = []
        for candidate in batch.candidates:
            validation = validation_by_id[candidate.candidate_id]
            if validation.status == "PROVISIONAL" and candidate.candidate_id not in selected_provisional_ids:
                continue
            evidence = tuple(
                evidence_by_id[evidence_id]
                for evidence_id in candidate.source_evidence_ids
            )
            inputs.append(
                CandidateIntelligenceInput(
                    candidate=candidate,
                    validation=validation,
                    evidence=evidence,
                )
            )
        return inputs

    def stream_batch(
        self,
        brief: MarketBrief,
        batch: ResearchBatch,
        *,
        selected_provisional_ids: set[str] | None = None,
    ) -> Iterator[IntelligenceEvent]:
        yield from self.stream(
            brief,
            self.inputs_from_batch(
                batch,
                selected_provisional_ids=selected_provisional_ids,
            ),
        )

    def stream(
        self,
        brief: MarketBrief,
        inputs: Sequence[CandidateIntelligenceInput],
    ) -> Iterator[IntelligenceEvent]:
        candidate_ids = [item.candidate.candidate_id for item in inputs]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise ValueError("candidate intelligence inputs must be unique")
        queue = deque(inputs)
        active: dict[str, _CandidateState] = {}
        futures: dict[
            Future[StructuredProductFacts | SemanticProductAnalysis],
            tuple[str, Literal["STRUCTURED", "SEMANTIC"]],
        ] = {}

        executor = ThreadPoolExecutor(
            max_workers=self.budget.max_concurrent_candidates * 2,
            thread_name_prefix="rivalmap-intelligence",
        )

        def launch_available() -> list[str]:
            launched = []
            while queue and len(active) < self.budget.max_concurrent_candidates:
                item = queue.popleft()
                candidate_id = item.candidate.candidate_id
                if candidate_id in active:
                    raise ValueError("candidate intelligence inputs must be unique")
                state = _CandidateState(item=item)
                active[candidate_id] = state
                structured_future = executor.submit(
                    self.structured.analyze,
                    item.candidate,
                    list(item.evidence),
                )
                semantic_future = executor.submit(
                    self.semantic.analyze,
                    item.candidate,
                    list(item.evidence),
                    brief,
                )
                futures[structured_future] = (candidate_id, "STRUCTURED")
                futures[semantic_future] = (candidate_id, "SEMANTIC")
                launched.append(candidate_id)
            return launched

        try:
            for candidate_id in launch_available():
                yield IntelligenceEvent(
                    event=IntelligenceEventType.ANALYSIS_STARTED,
                    candidate_id=candidate_id,
                )

            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                ordered = sorted(
                    done,
                    key=lambda future: (
                        futures[future][0],
                        0 if futures[future][1] == "STRUCTURED" else 1,
                    ),
                )
                for future in ordered:
                    candidate_id, path = futures.pop(future)
                    state = active[candidate_id]
                    product_id = product_id_for_candidate(candidate_id)
                    evidence_ids = {item.evidence_id for item in state.item.evidence}
                    try:
                        output = future.result()
                        if path == "STRUCTURED":
                            if not isinstance(output, StructuredProductFacts):
                                raise InvalidAnalysisOutput("structured path returned wrong type")
                            _validate_output(
                                output,
                                product_id=product_id,
                                evidence_ids=evidence_ids,
                            )
                            state.structured = output
                            yield IntelligenceEvent(
                                event=IntelligenceEventType.STRUCTURED_ANALYSIS_COMPLETE,
                                candidate_id=candidate_id,
                                structured_facts=output,
                            )
                        else:
                            if not isinstance(output, SemanticProductAnalysis):
                                raise InvalidAnalysisOutput("semantic path returned wrong type")
                            _validate_output(
                                output,
                                product_id=product_id,
                                evidence_ids=evidence_ids,
                            )
                            state.semantic = output
                            yield IntelligenceEvent(
                                event=IntelligenceEventType.SEMANTIC_ANALYSIS_COMPLETE,
                                candidate_id=candidate_id,
                                semantic_analysis=output,
                            )
                    except Exception as exc:  # noqa: BLE001 - isolate one analysis path
                        state.failed_paths.append(path)
                        error_code = (
                            "INVALID_OUTPUT"
                            if isinstance(exc, (InvalidAnalysisOutput, ValidationError))
                            else "PROVIDER_FAILED"
                        )
                        state.failure_codes.append(error_code)
                        yield IntelligenceEvent(
                            event=IntelligenceEventType.ANALYSIS_PARTIAL,
                            candidate_id=candidate_id,
                            failed_path=path,
                            error_code=error_code,
                        )
                    finally:
                        if path == "STRUCTURED":
                            state.structured_done = True
                        else:
                            state.semantic_done = True

                    if state.structured_done and state.semantic_done:
                        if state.structured is None and state.semantic is None:
                            yield IntelligenceEvent(
                                event=IntelligenceEventType.ANALYSIS_FAILED,
                                candidate_id=candidate_id,
                                failed_path="BOTH",
                                error_code=(
                                    "INVALID_OUTPUT"
                                    if state.failure_codes
                                    and all(
                                        code == "INVALID_OUTPUT"
                                        for code in state.failure_codes
                                    )
                                    else "PROVIDER_FAILED"
                                ),
                            )
                        else:
                            profile = self.fusion.fuse(
                                state.item,
                                state.structured,
                                state.semantic,
                            )
                            yield IntelligenceEvent(
                                event=IntelligenceEventType.PRODUCT_PROFILE_READY,
                                candidate_id=candidate_id,
                                profile=profile,
                            )
                        del active[candidate_id]

                for candidate_id in launch_available():
                    yield IntelligenceEvent(
                        event=IntelligenceEventType.ANALYSIS_STARTED,
                        candidate_id=candidate_id,
                    )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
