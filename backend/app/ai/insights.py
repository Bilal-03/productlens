from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from app.ai.providers import ProviderError, ProviderRouter
from app.models.contracts import Evidence, Finding, Recommendation


class GroundedInsight(BaseModel):
    headline: str
    summary: str
    findings: list[Finding]
    recommendations: list[Recommendation]
    follow_up_questions: list[str] = Field(min_length=2, max_length=5)
    caveats: list[str]


class InsightService:
    def __init__(self, router: ProviderRouter) -> None:
        self.router = router

    def interpret(
        self,
        *,
        question: str,
        metric_label: str,
        evidence: list[Evidence],
        deterministic: GroundedInsight,
    ) -> tuple[GroundedInsight, str, bool]:
        if not self.router.available:
            return deterministic, "deterministic", True
        system = (
            "You are an evidence-bound product analyst. Use only the supplied evidence. "
            "Every quantitative finding and recommendation must reference evidence_ids. "
            "Separate observations, likely drivers, hypotheses, and investigations. "
            "Never claim causation from observational data."
        )
        payload = json.dumps({"question": question, "metric": metric_label, "evidence": [item.model_dump() for item in evidence]})
        try:
            candidate, provider = self.router.complete_structured(GroundedInsight, system, payload)
        except ProviderError:
            return deterministic, "deterministic", True
        grounded = self._validate(candidate, evidence)
        return (candidate, provider, True) if grounded else (deterministic, "deterministic-grounding-fallback", False)

    @staticmethod
    def _validate(candidate: GroundedInsight, evidence: list[Evidence]) -> bool:
        valid_ids = {item.id for item in evidence}
        evidence_numbers = set(re.findall(r"-?\d+(?:\.\d+)?", " ".join(f"{item.value} {item.detail}" for item in evidence)))
        narrative_text = [candidate.headline, candidate.summary]
        for finding in candidate.findings:
            if not finding.evidence_ids:
                return False
            if not set(finding.evidence_ids).issubset(valid_ids):
                return False
            numbers = set(re.findall(r"-?\d+(?:\.\d+)?", finding.text))
            if not numbers.issubset(evidence_numbers):
                return False
            narrative_text.append(finding.text)
        for recommendation in candidate.recommendations:
            if not recommendation.evidence_ids or not set(recommendation.evidence_ids).issubset(valid_ids):
                return False
            narrative_text.extend([recommendation.action, recommendation.expected_impact, recommendation.how_to_validate])
        for text in narrative_text:
            numbers = set(re.findall(r"-?\d+(?:\.\d+)?", text))
            if not numbers.issubset(evidence_numbers):
                return False
        return True
