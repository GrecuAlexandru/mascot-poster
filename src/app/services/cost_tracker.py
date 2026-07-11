from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from app.domain.models import CostRecord

logger = logging.getLogger(__name__)


class CostTracker:
    def __init__(self, job_id: Optional[str] = None):
        self.job_id = job_id
        self._records: list[CostRecord] = []

    def add(
        self,
        provider: str,
        operation: str,
        units: float,
        unit_type: str,
        estimated_cost_usd: float,
    ) -> None:
        rec = CostRecord(
            job_id=self.job_id,
            provider=provider,
            operation=operation,
            units=units,
            unit_type=unit_type,
            estimated_cost_usd=round(estimated_cost_usd, 6),
        )
        self._records.append(rec)
        logger.info(
            f"Cost: {provider}/{operation} = {units} {unit_type} = ${rec.estimated_cost_usd:.4f}"
        )

    def add_llm(self, provider: str, input_tokens: int, output_tokens: int, cost: float) -> None:
        self.add(provider, "llm_tokens", input_tokens + output_tokens, "tokens", cost)

    def add_tts(self, provider: str, characters: int, cost: float) -> None:
        self.add(provider, "tts_characters", characters, "chars", cost)

    def add_search(self, provider: str, queries: int, cost: float) -> None:
        self.add(provider, "search_queries", queries, "queries", cost)

    def add_images(self, provider: str, count: int, cost: float) -> None:
        self.add(provider, "image_generation", count, "images", cost)

    def add_storage(self, provider: str, size_bytes: int, cost: float) -> None:
        self.add(provider, "storage", size_bytes, "bytes", cost)

    @property
    def total_cost(self) -> float:
        return round(sum(r.estimated_cost_usd for r in self._records), 6)

    def to_dict(self) -> dict:
        by_category: dict[str, float] = {}
        for r in self._records:
            cat = r.operation.split("_")[0] if "_" in r.operation else r.operation
            by_category[cat] = round(by_category.get(cat, 0) + r.estimated_cost_usd, 6)
        by_category["total"] = self.total_cost
        return {
            "job_id": self.job_id,
            "records": [r.model_dump() for r in self._records],
            "by_category": by_category,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        logger.info(f"Cost report saved: {path} (total=${self.total_cost:.4f})")
