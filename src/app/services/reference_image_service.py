from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from PIL import Image
from pydantic import BaseModel

from app.providers.images.openai_provider import RemoteImageProvider
from app.providers.search.base import ImageCandidate


class ImageProvenance(BaseModel):
    item: str
    path: Path
    source_type: Literal["real", "generated"]
    source_url: Optional[str] = None
    image_url: Optional[str] = None
    description: str = ""
    provider: str
    selection_reason: str
    candidates_tried: int = 0


class ReferenceImageService:
    def __init__(
        self,
        search_provider: object,
        generated_provider: Optional[object],
        downloader: Optional[object] = None,
        max_candidates: int = 5,
    ):
        self.search_provider = search_provider
        self.generated_provider = generated_provider
        self.downloader = downloader or RemoteImageProvider()
        self.max_candidates = max_candidates

    async def acquire(
        self,
        item: str,
        output_path: Path,
        provenance_path: Optional[Path] = None,
    ) -> ImageProvenance:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        response = await self.search_provider.search(
            f"{item} official product isolated white background",
            max_results=self.max_candidates,
            include_images=True,
        )
        candidates = sorted(
            response.images,
            key=lambda candidate: self._candidate_score(item, candidate),
            reverse=True,
        )[:self.max_candidates]

        for index, candidate in enumerate(candidates):
            candidate_path = output_path.parent / f".{output_path.stem}_candidate_{index}.png"
            try:
                await self.downloader.download(candidate.url, candidate_path)
                if not self._is_usable(candidate_path):
                    continue
                self._normalize(candidate_path, output_path)
                provenance = ImageProvenance(
                    item=item,
                    path=output_path,
                    source_type="real",
                    source_url=candidate.source_url,
                    image_url=candidate.url,
                    description=candidate.description,
                    provider=response.provider or "search",
                    selection_reason="highest-ranked valid real image",
                    candidates_tried=index + 1,
                )
                self._save_provenance(provenance, provenance_path)
                return provenance
            except Exception:
                pass
            finally:
                if candidate_path.exists():
                    candidate_path.unlink()

        if self.generated_provider is None:
            raise RuntimeError(f"No usable real image and no generated fallback for {item}")
        prompt = (
            f"Photorealistic isolated image of {item}, centered full object, "
            f"transparent background, no added text, no watermark"
        )
        result = await self.generated_provider.generate(prompt, output_path, 1024, 1024)
        if not self._is_usable(output_path, require_transparency=True):
            raise RuntimeError(f"Generated fallback is invalid for {item}")
        provenance = ImageProvenance(
            item=item,
            path=output_path,
            source_type="generated",
            provider=result.provider or getattr(self.generated_provider, "name", "generated"),
            description=prompt,
            selection_reason="real image candidates exhausted",
            candidates_tried=len(candidates),
        )
        self._save_provenance(provenance, provenance_path)
        return provenance

    @staticmethod
    def _candidate_score(item: str, candidate: ImageCandidate) -> float:
        score = candidate.score
        terms = [term.casefold() for term in item.split() if len(term) > 2]
        description = candidate.description.casefold()
        score += sum(0.25 for term in terms if term in description)
        host = urlparse(candidate.source_url or candidate.url).netloc.casefold()
        if any(token in host for token in ("official", "wikipedia", "manufacturer")):
            score += 0.5
        if "white background" in description or "fundal alb" in description:
            score += 0.25
        return score

    @staticmethod
    def _is_usable(path: Path, require_transparency: bool = False) -> bool:
        try:
            image = Image.open(path).convert("RGBA")
            if image.width < 400 or image.height < 400:
                return False
            alpha = image.getchannel("A")
            alpha_min, alpha_max = alpha.getextrema()
            if alpha_max == 0:
                return False
            if require_transparency:
                return alpha_min == 0 and alpha_max > 0
            if alpha_min == 0:
                return True
            corners = [
                image.getpixel((0, 0)),
                image.getpixel((image.width - 1, 0)),
                image.getpixel((0, image.height - 1)),
                image.getpixel((image.width - 1, image.height - 1)),
            ]
            return sum(1 for pixel in corners if min(pixel[:3]) >= 225) >= 3
        except Exception:
            return False

    @staticmethod
    def _normalize(source: Path, output: Path) -> None:
        image = Image.open(source).convert("RGBA")
        image.save(output, format="PNG")

    @staticmethod
    def _save_provenance(
        provenance: ImageProvenance,
        provenance_path: Optional[Path],
    ) -> None:
        if provenance_path is None:
            return
        provenance_path.parent.mkdir(parents=True, exist_ok=True)
        provenance_path.write_text(
            provenance.model_dump_json(indent=2),
            encoding="utf-8",
        )
