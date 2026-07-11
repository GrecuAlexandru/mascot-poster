from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional
from uuid import uuid4

from app.domain.models import CostEvent, CostReport


_active_ledger: ContextVar[Optional["JobCostLedger"]] = ContextVar(
    "active_job_cost_ledger",
    default=None,
)
_active_stage: ContextVar[str] = ContextVar("active_job_cost_stage", default="unknown")


class JobCostLedger:
    def __init__(self, job_id: str, events: Optional[list[CostEvent]] = None):
        self.job_id = job_id
        self._events: dict[str, CostEvent] = {
            event.event_id: event for event in events or []
        }

    @property
    def events(self) -> list[CostEvent]:
        return list(self._events.values())

    def record(
        self,
        *,
        stage: str,
        provider: str,
        operation: str,
        model: str = "",
        input_units: float = 0.0,
        output_units: float = 0.0,
        unit_type: str = "calls",
        amount_usd: float = 0.0,
        amount_kind: Literal["actual", "estimated"] = "estimated",
        pricing_source: str = "estimate",
        attempt: Optional[int] = None,
        status: Literal["success", "failed"] = "success",
        cached: bool = False,
        error: Optional[str] = None,
        request_key: str = "",
    ) -> CostEvent:
        stable_key = request_key or str(uuid4())
        matching = [
            event
            for event in self._events.values()
            if event.stage == stage
            and event.provider == provider
            and event.model == model
            and event.operation == operation
            and event.request_key == stable_key
        ]
        if attempt is None and matching:
            previous = max(matching, key=lambda event: event.attempt)
            if (
                previous.input_units == input_units
                and previous.output_units == output_units
                and previous.unit_type == unit_type
                and previous.amount_usd == round(amount_usd, 6)
                and previous.amount_kind == amount_kind
                and previous.pricing_source == pricing_source
                and previous.status == status
                and previous.cached == cached
                and previous.error == error
            ):
                return previous
        resolved_attempt = attempt or (max((event.attempt for event in matching), default=0) + 1)
        identity = json.dumps([
            self.job_id,
            stage,
            provider,
            model,
            operation,
            resolved_attempt,
            stable_key,
        ], ensure_ascii=False)
        event_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        event = CostEvent(
            event_id=event_id,
            job_id=self.job_id,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            stage=stage,
            provider=provider,
            model=model,
            operation=operation,
            input_units=input_units,
            output_units=output_units,
            unit_type=unit_type,
            amount_usd=round(amount_usd, 6),
            amount_kind=amount_kind,
            pricing_source=pricing_source,
            attempt=resolved_attempt,
            status=status,
            cached=cached,
            error=error,
            request_key=stable_key,
        )
        self._events.setdefault(event_id, event)
        return self._events[event_id]

    def report(self) -> CostReport:
        events = self.events
        actual = round(sum(e.amount_usd for e in events if e.amount_kind == "actual"), 6)
        estimated = round(sum(e.amount_usd for e in events if e.amount_kind == "estimated"), 6)
        return CostReport(
            job_id=self.job_id,
            events=events,
            actual_total_usd=actual,
            estimated_total_usd=estimated,
            projected_total_usd=round(actual + estimated, 6),
            by_provider=self._group(events, "provider"),
            by_stage=self._group(events, "stage"),
            by_operation=self._group(events, "operation"),
            by_model=self._group(events, "model"),
            by_amount_kind=self._group(events, "amount_kind"),
            billable_calls=sum(event.amount_usd > 0 for event in events),
            failed_calls=sum(event.status == "failed" for event in events),
            cached_calls=sum(event.cached for event in events),
            retry_calls=sum(event.attempt > 1 for event in events),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.report().model_dump_json(indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path, job_id: str) -> "JobCostLedger":
        if not path.exists():
            return cls(job_id)
        report = CostReport.model_validate_json(path.read_text(encoding="utf-8"))
        return cls(job_id, report.events)

    @staticmethod
    def _group(events: list[CostEvent], field: str) -> dict[str, float]:
        grouped: dict[str, float] = {}
        for event in events:
            key = str(getattr(event, field) or "unspecified")
            grouped[key] = round(grouped.get(key, 0.0) + event.amount_usd, 6)
        return grouped


@contextmanager
def cost_scope(ledger: JobCostLedger, stage: str) -> Iterator[JobCostLedger]:
    ledger_token = _active_ledger.set(ledger)
    stage_token = _active_stage.set(stage)
    try:
        yield ledger
    finally:
        _active_stage.reset(stage_token)
        _active_ledger.reset(ledger_token)


def record_cost_event(
    *,
    provider: str,
    operation: str,
    model: str = "",
    input_units: float = 0.0,
    output_units: float = 0.0,
    unit_type: str = "calls",
    amount_usd: float = 0.0,
    amount_kind: Literal["actual", "estimated"] = "estimated",
    pricing_source: str = "estimate",
    attempt: Optional[int] = None,
    status: Literal["success", "failed"] = "success",
    cached: bool = False,
    error: Optional[str] = None,
    request_key: str = "",
) -> Optional[CostEvent]:
    ledger = _active_ledger.get()
    if ledger is None:
        return None
    return ledger.record(
        stage=_active_stage.get(),
        provider=provider,
        operation=operation,
        model=model,
        input_units=input_units,
        output_units=output_units,
        unit_type=unit_type,
        amount_usd=amount_usd,
        amount_kind=amount_kind,
        pricing_source=pricing_source,
        attempt=attempt,
        status=status,
        cached=cached,
        error=error,
        request_key=request_key,
    )


def set_cost_stage(stage: str) -> None:
    _active_stage.set(stage)
