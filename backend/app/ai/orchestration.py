"""Bounded, typed coordination for the Copilot analysis pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import ClassVar

from app.models.contracts import AgentStatus, AnalysisMode, OrchestrationMetadata


@dataclass
class AgentOrchestrator:
    """Coordinate the fixed Planner → Analyst → Evidence stages.

    This is intentionally a small deterministic coordinator rather than an
    autonomous agent swarm. Stages cannot create tools or SQL capabilities;
    they only annotate the existing governed pipeline and share a hard budget.
    """

    enabled: bool
    timeout_ms: int
    mode: AnalysisMode
    started_at: float = field(default_factory=time.perf_counter)
    _stages: dict[str, AgentStatus] = field(default_factory=dict)
    _fallback: bool = False
    AGENT_CAPABILITIES: ClassVar[dict[str, tuple[str, ...]]] = {
        "planner": ("classify_question",),
        "analyst": ("run_governed_analytics",),
        "evidence": ("bind_evidence", "grounded_prose"),
    }

    def start(self, name: str) -> float:
        if name not in self.AGENT_CAPABILITIES:
            raise ValueError("Only the fixed planner, analyst, and evidence stages are allowed")
        if name in self._stages:
            raise ValueError(f"Agent stage '{name}' has already completed")
        return time.perf_counter()

    def capabilities(self, name: str) -> tuple[str, ...]:
        try:
            return self.AGENT_CAPABILITIES[name]
        except KeyError as exc:
            raise ValueError("Unknown agent stage") from exc

    def complete(self, name: str, started: float, *, fallback: bool = False) -> None:
        status = "fallback" if fallback else "completed"
        self._stages[name] = AgentStatus(
            name=name,
            status=status,
            duration_ms=max(0.0, (time.perf_counter() - started) * 1000),
        )
        self._fallback = self._fallback or fallback

    def fail(self, name: str, started: float) -> None:
        self._stages[name] = AgentStatus(
            name=name,
            status="fallback",
            duration_ms=max(0.0, (time.perf_counter() - started) * 1000),
        )
        self._fallback = True

    def within_budget(self) -> bool:
        return (time.perf_counter() - self.started_at) * 1000 < self.timeout_ms

    def has_stage(self, name: str) -> bool:
        return name in self._stages

    def finish(self) -> OrchestrationMetadata:
        for name in ("planner", "analyst", "evidence"):
            if name not in self._stages:
                self._stages[name] = AgentStatus(name=name, status="skipped", duration_ms=0)
        return OrchestrationMetadata(
            enabled=self.enabled,
            mode="bounded_pipeline" if self.enabled else "single_pipeline",
            agents=[self._stages[name] for name in ("planner", "analyst", "evidence")],
            handoffs=2 if self.enabled else 0,
            fallback=self._fallback,
            bounded=True,
        )
