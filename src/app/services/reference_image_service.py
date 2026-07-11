from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from PIL import Image
from pydantic import BaseModel, Field

from app.domain.models import ProductImageBrief
from app.providers.images.openai_provider import RemoteImageProvider
from app.providers.search.base import ImageCandidate
from app.services.reference_image_validator import ImageValidationResult
from app.services.job_cost_ledger import record_cost_event


class ImageAttempt(BaseModel):
    source_type: Literal["real", "generated"]
    image_url: Optional[str] = None
    source_url: Optional[str] = None
    prompt: Optional[str] = None
    semantic_result: Optional[ImageValidationResult] = None
    rejection_reasons: list[str] = Field(default_factory=list)
    selected: bool = False


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
    attempts: list[ImageAttempt] = Field(default_factory=list)


class ReferenceImageService:
    def __init__(
        self,
        search_provider: object,
        generated_provider: Optional[object],
        downloader: Optional[object] = None,
        max_candidates: int = 5,
        validator: Optional[object] = None,
        max_generated_attempts: int = 3,
    ):
        self.search_provider = search_provider
        self.generated_provider = generated_provider
        self.downloader = downloader or RemoteImageProvider()
        self.max_candidates = max_candidates
        self.validator = validator
        self.max_generated_attempts = max_generated_attempts

    async def acquire(
        self,
        item: str,
        output_path: Path,
        provenance_path: Optional[Path] = None,
        brief: Optional[ProductImageBrief] = None,
        shared_style: str = "",
        prior_rejections: Optional[list[str]] = None,
        force_generated: bool = False,
    ) -> ImageProvenance:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        search_subject = brief.exact_subject if brief else item
        response = await self.search_provider.search(
            f"{search_subject} isolated product transparent or white background",
            max_results=0 if force_generated else self.max_candidates,
            include_images=not force_generated,
        )
        candidates = sorted(
            response.images,
            key=lambda candidate: self._candidate_score(item, candidate),
            reverse=True,
        )[:self.max_candidates] if not force_generated else []
        attempts: list[ImageAttempt] = []

        for index, candidate in enumerate(candidates):
            metadata_problem = self.metadata_rejection(candidate)
            if metadata_problem:
                attempts.append(ImageAttempt(
                    source_type="real",
                    image_url=candidate.url,
                    source_url=candidate.source_url,
                    rejection_reasons=[metadata_problem],
                ))
                continue
            candidate_path = output_path.parent / f".{output_path.stem}_candidate_{index}.png"
            try:
                await self.downloader.download(candidate.url, candidate_path)
                record_cost_event(
                    provider=getattr(self.downloader, "name", "remote_download"),
                    operation="image_download",
                    input_units=1,
                    unit_type="downloads",
                    amount_usd=0.0,
                    pricing_source="no_incremental_api_cost",
                    request_key=candidate.url,
                )
                if not self._is_usable(candidate_path):
                    attempts.append(ImageAttempt(
                        source_type="real",
                        image_url=candidate.url,
                        source_url=candidate.source_url,
                        rejection_reasons=["downloaded image failed media validation"],
                    ))
                    continue
                self._normalize(candidate_path, output_path)
                semantic_result = await self._validate(output_path, brief)
                if semantic_result is not None and not semantic_result.accepted:
                    attempts.append(ImageAttempt(
                        source_type="real",
                        image_url=candidate.url,
                        source_url=candidate.source_url,
                        semantic_result=semantic_result,
                        rejection_reasons=semantic_result.rejection_reasons,
                    ))
                    output_path.unlink(missing_ok=True)
                    continue
                attempts.append(ImageAttempt(
                    source_type="real",
                    image_url=candidate.url,
                    source_url=candidate.source_url,
                    semantic_result=semantic_result,
                    selected=True,
                ))
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
                    attempts=attempts,
                )
                self._save_provenance(provenance, provenance_path)
                return provenance
            except Exception as error:
                record_cost_event(
                    provider=getattr(self.downloader, "name", "remote_download"),
                    operation="image_download",
                    input_units=1,
                    unit_type="downloads",
                    amount_usd=0.0,
                    pricing_source="request_failed",
                    status="failed",
                    error=f"{type(error).__name__}: {error}",
                    request_key=candidate.url,
                )
                attempts.append(ImageAttempt(
                    source_type="real",
                    image_url=candidate.url,
                    source_url=candidate.source_url,
                    rejection_reasons=[f"candidate processing failed: {type(error).__name__}: {error}"],
                ))
            finally:
                if candidate_path.exists():
                    candidate_path.unlink()

        if self.generated_provider is None:
            raise RuntimeError(f"No usable real image and no generated fallback for {item}")
        effective_brief = brief or ProductImageBrief(
                item=item,
                exact_subject=item,
                distinguishing_attributes=[f"visually unmistakable {item}"],
                prohibited_elements=["logo", "watermark", "unrelated text"],
            )
        effective_style = shared_style or (
                "three-quarter camera angle, centered full object, matching product scale, "
                "neutral studio lighting, transparent background"
            )
        rejection_feedback = list(prior_rejections or [])
        for _ in range(self.max_generated_attempts):
            prompt = self.build_generation_prompt(
                effective_brief,
                effective_style,
                rejection_feedback,
            )
            try:
                result = await self.generated_provider.generate(prompt, output_path, 1024, 1024)
                if not self._is_usable(output_path, require_transparency=True):
                    reasons = ["generated image failed transparency or media validation"]
                    attempts.append(ImageAttempt(
                        source_type="generated",
                        prompt=prompt,
                        rejection_reasons=reasons,
                    ))
                    rejection_feedback.extend(reasons)
                    continue
                semantic_result = await self._validate(output_path, effective_brief)
                if semantic_result is not None and not semantic_result.accepted:
                    reasons = semantic_result.rejection_reasons or ["semantic validation failed"]
                    attempts.append(ImageAttempt(
                        source_type="generated",
                        prompt=prompt,
                        semantic_result=semantic_result,
                        rejection_reasons=reasons,
                    ))
                    rejection_feedback.extend(reasons)
                    continue
                attempts.append(ImageAttempt(
                    source_type="generated",
                    prompt=prompt,
                    semantic_result=semantic_result,
                    selected=True,
                ))
                provenance = ImageProvenance(
                    item=item,
                    path=output_path,
                    source_type="generated",
                    provider=result.provider or getattr(self.generated_provider, "name", "generated"),
                    description=prompt,
                    selection_reason="real candidates exhausted; generated image passed validation",
                    candidates_tried=len(candidates),
                    attempts=attempts,
                )
                self._save_provenance(provenance, provenance_path)
                return provenance
            except Exception as error:
                reason = f"generation attempt failed: {type(error).__name__}: {error}"
                attempts.append(ImageAttempt(
                    source_type="generated",
                    prompt=prompt,
                    rejection_reasons=[reason],
                ))
                rejection_feedback.append(reason)
        output_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Generated fallback failed validation for {item}: "
            + "; ".join(rejection_feedback[-3:])
        )

    async def _validate(
        self,
        path: Path,
        brief: Optional[ProductImageBrief],
    ) -> Optional[ImageValidationResult]:
        if self.validator is None or brief is None:
            return None
        return await self.validator.validate_item(path, brief)

    @staticmethod
    def metadata_rejection(candidate: ImageCandidate) -> Optional[str]:
        text = " ".join((
            candidate.url,
            candidate.source_url or "",
            candidate.source_title,
            candidate.description,
        )).casefold()
        blocked = (
            "logo", "logos", "icon", "sprite", "favicon", "avatar",
            "social-preview", "social_media_preview", "placeholder", "brandmark",
        )
        if any(token in text for token in blocked):
            return "logo or social-preview asset"
        return None

    @staticmethod
    def build_generation_prompt(
        brief: ProductImageBrief,
        shared_style: str,
        prior_rejections: list[str],
    ) -> str:
        required = ", ".join(brief.required_elements) or "no additional props"
        attributes = ", ".join(brief.distinguishing_attributes)
        prohibited = list(brief.prohibited_elements)
        if not brief.allow_packaging:
            prohibited.append("packaging")
        if not brief.allow_text:
            prohibited.append("text")
        negatives = [f"no {item}" for item in prohibited]
        negatives.extend(f"not {item}" for item in brief.confusing_alternatives)
        if prior_rejections:
            negatives.extend(f"correct previous issue: {reason}" for reason in prior_rejections)
        return (
            f"Create one photorealistic {brief.exact_subject}. "
            f"It must visibly show: {attributes}. Required composition details: {required}. "
            f"Pair style: {shared_style}. The full subject must be centered and completely visible, "
            f"occupying about 72 percent of the canvas with clean transparent pixels to every edge. "
            f"Use even neutral studio lighting and realistic texture. "
            f"Negative constraints: {', '.join(negatives)}. Output a transparent PNG."
        )

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
