from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

from PIL import Image
from pydantic import BaseModel, Field

from app.domain.models import PairedImageBrief, ProductImageBrief
from app.providers.images.openai_provider import RemoteImageProvider
from app.providers.search.base import ImageCandidate
from app.services.reference_image_validator import ImageValidationResult
from app.services.job_cost_ledger import record_cost_event
from app.services.product_asset_normalizer import ProductAssetMetrics, ProductAssetNormalizer


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
    asset_metrics: ProductAssetMetrics


class ReferenceImageService:
    def __init__(
        self,
        search_provider: object,
        generated_provider: Optional[object],
        downloader: Optional[object] = None,
        max_candidates: int = 3,
        validator: Optional[object] = None,
        max_generated_attempts: int = 3,
        normalizer: Optional[ProductAssetNormalizer] = None,
    ):
        self.search_provider = search_provider
        self.generated_provider = generated_provider
        self.downloader = downloader or RemoteImageProvider()
        self.max_candidates = max_candidates
        self.validator = validator
        self.max_generated_attempts = max_generated_attempts
        self.normalizer = normalizer or ProductAssetNormalizer()

    async def acquire(
        self,
        item: str,
        output_path: Path,
        provenance_path: Optional[Path] = None,
        brief: Optional[ProductImageBrief] = None,
        shared_style: str = "",
        prior_rejections: Optional[list[str]] = None,
        force_generated: bool = False,
        input_references: Optional[list[Path]] = None,
        repair_instructions: Optional[list[str]] = None,
        generated_attempt_limit: Optional[int] = None,
    ) -> ImageProvenance:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        requires_real_reference = bool(
            not force_generated
            and brief is not None
            and brief.requires_real_reference
        )
        response = None
        candidates: list[ImageCandidate] = []
        if requires_real_reference:
            search_subject = self._search_subject(item, brief)
            response = await self.search_provider.search(
                f"{search_subject} isolated product cutout transparent background png",
                max_results=self.max_candidates,
                include_images=True,
            )
            candidates = sorted(
                response.images,
                key=lambda candidate: self._candidate_score(item, candidate),
                reverse=True,
            )[:self.max_candidates]
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
                        rejection_reasons=[
                            "downloaded image has no usable isolated white background"
                        ],
                    ))
                    continue
                asset_metrics = self.normalizer.normalize(candidate_path, output_path)
                semantic_result = await self._validate(output_path, brief)
                if semantic_result is None:
                    attempts.append(ImageAttempt(
                        source_type="real",
                        image_url=candidate.url,
                        source_url=candidate.source_url,
                        rejection_reasons=["search candidate could not be semantically validated"],
                    ))
                    output_path.unlink(missing_ok=True)
                    continue
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
                    provider=response.provider if response is not None and response.provider else "search",
                    selection_reason="highest-ranked valid real image",
                    candidates_tried=index + 1,
                    attempts=attempts,
                    asset_metrics=asset_metrics,
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
                "neutral studio lighting, solid pure-white background"
            )
        rejection_feedback = list(prior_rejections or [])
        attempt_limit = generated_attempt_limit or self.max_generated_attempts
        for _ in range(attempt_limit):
            prompt = self.build_generation_prompt(
                effective_brief,
                effective_style,
                rejection_feedback,
                repair_instructions=repair_instructions,
                has_reference=bool(input_references),
            )
            try:
                if input_references:
                    result = await self.generated_provider.generate(
                        prompt,
                        output_path,
                        1024,
                        1024,
                        input_references=input_references,
                    )
                else:
                    result = await self.generated_provider.generate(prompt, output_path, 1024, 1024)
                if not self._is_usable(output_path):
                    reasons = [
                        "generated image must use one uniform solid white background with no checkerboard"
                    ]
                    attempts.append(ImageAttempt(
                        source_type="generated",
                        prompt=prompt,
                        rejection_reasons=reasons,
                    ))
                    rejection_feedback.extend(reasons)
                    continue
                asset_metrics = self.normalizer.normalize(output_path, output_path)
                attempts.append(ImageAttempt(
                    source_type="generated",
                    prompt=prompt,
                    selected=True,
                ))
                provenance = ImageProvenance(
                    item=item,
                    path=output_path,
                    source_type="generated",
                    provider=result.provider or getattr(self.generated_provider, "name", "generated"),
                    description=prompt,
                    selection_reason=(
                        "real candidates exhausted; generated image accepted without semantic validation"
                        if requires_real_reference
                        else "generated directly for a generic object without semantic validation"
                    ),
                    candidates_tried=len(candidates),
                    attempts=attempts,
                    asset_metrics=asset_metrics,
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
            f"Generated image failed media validation for {item}: "
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

    async def generate_pair_repair(
        self,
        *,
        left_item: str,
        right_item: str,
        left_path: Path,
        right_path: Path,
        brief: PairedImageBrief,
        repair_instructions: list[str],
    ) -> tuple[ImageProvenance, ImageProvenance]:
        if self.generated_provider is None:
            raise RuntimeError("Pair repair requires a generated image provider")
        pair_path = left_path.parent / ".pair_repair.png"
        prompt = self.build_pair_repair_prompt(brief, repair_instructions)
        try:
            result = await self.generated_provider.generate(
                prompt,
                pair_path,
                1536,
                1024,
                input_references=[left_path, right_path],
            )
            self._split_pair_image(pair_path, left_path, right_path)
            if not self._is_usable(left_path):
                raise RuntimeError("Left half of paired repair is not usable")
            if not self._is_usable(right_path):
                raise RuntimeError("Right half of paired repair is not usable")
            left_metrics = self.normalizer.normalize(left_path, left_path)
            right_metrics = self.normalizer.normalize(right_path, right_path)
            provider = result.provider or getattr(self.generated_provider, "name", "generated")
            left_provenance = ImageProvenance(
                item=left_item,
                path=left_path,
                source_type="generated",
                provider=provider,
                description=prompt,
                selection_reason="one-shot paired repair",
                attempts=[ImageAttempt(source_type="generated", prompt=prompt, selected=True)],
                asset_metrics=left_metrics,
            )
            right_provenance = ImageProvenance(
                item=right_item,
                path=right_path,
                source_type="generated",
                provider=provider,
                description=prompt,
                selection_reason="one-shot paired repair",
                attempts=[ImageAttempt(source_type="generated", prompt=prompt, selected=True)],
                asset_metrics=right_metrics,
            )
            return left_provenance, right_provenance
        finally:
            pair_path.unlink(missing_ok=True)

    @staticmethod
    def build_pair_repair_prompt(
        brief: PairedImageBrief,
        repair_instructions: list[str],
    ) -> str:
        repairs = "; ".join(repair_instructions) or "Make the two compositions match"
        return (
            "Create one photorealistic side-by-side paired product photograph on a wide canvas. "
            "Place the LEFT requested subject entirely inside the left half and the RIGHT requested "
            "subject entirely inside the right half, with no divider and nothing crossing the center. "
            "Show exactly one object in each half: no duplicates, no extra copies, no collage. Keep each "
            "object upright, centered in its half, in sharp focus, with a small margin so nothing is cropped. "
            "Use the two input images only as composition references. Correct these validator issues: "
            f"{repairs}. Match visible object bounding-box width and height, vertical center, camera "
            "elevation, perspective, crop, lighting direction, shadow softness, and background treatment. "
            "Keep each side's exact identity, material, texture, construction cues, and required elements. "
            "Do not copy one product's identity, material, color, labels, or defining details onto the other. "
            "Different product colors are allowed. Every visible surface must be blank and unbranded: no "
            "embossed, printed, engraved, stitched, overlaid, captioned, or watermark text unless explicitly "
            "required by the brief. Use one flat solid pure-white background with no checkerboard or scenery. "
            f"Paired brief: {brief.model_dump_json()}"
        )

    @staticmethod
    def _split_pair_image(source_path: Path, left_path: Path, right_path: Path) -> None:
        source = Image.open(source_path).convert("RGBA")
        midpoint = source.width // 2
        halves = [
            source.crop((0, 0, midpoint, source.height)),
            source.crop((midpoint, 0, source.width, source.height)),
        ]
        for half, destination in zip(halves, (left_path, right_path)):
            canvas = Image.new("RGBA", (1024, 1024), (255, 255, 255, 255))
            scale = min(1024 / half.width, 1024 / half.height)
            size = (max(1, round(half.width * scale)), max(1, round(half.height * scale)))
            resized = half.resize(size, Image.Resampling.LANCZOS)
            canvas.alpha_composite(
                resized,
                ((1024 - resized.width) // 2, (1024 - resized.height) // 2),
            )
            canvas.save(destination, format="PNG")

    @staticmethod
    def _search_subject(item: str, brief: Optional[ProductImageBrief]) -> str:
        if brief and brief.search_query_en.strip():
            return " ".join(brief.search_query_en.split()[:8])
        subject = (brief.item if brief else item).split(":", 1)[0].strip()
        words = subject.split()
        return " ".join(words[:8]) if words else item

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
        repair_instructions: Optional[list[str]] = None,
        has_reference: bool = False,
    ) -> str:
        generation_style = re.sub(
            r"transparent\s+background",
            "solid pure-white background",
            shared_style,
            flags=re.IGNORECASE,
        )
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
        text_guidance = (
            "Render no readable text, labels, logos, numbers, UI copy, watermarks, or captions. "
            if brief.image_text_language == "none"
            else (
                "If readable text is intrinsic and required by the brief, render it only in Romanian with "
                "correct diacritics; do not render English text, watermarks, or unrelated copy. "
                if brief.image_text_language == "romanian"
                else "If readable text is intrinsic and required by the brief, render it only in English; "
                "do not render Romanian text, watermarks, or unrelated copy. "
            )
        )
        interface_guidance = ""
        if ReferenceImageService._is_digital_interface(brief):
            interface_guidance = (
                "This is a digital interface: show the real device form factor and a generic but "
                "recognizable interface layout. Do not rely on a trademarked logo, platform name, "
                "exact screen text, or pixel-perfect UI; ignore those details if they appear in the brief. "
            )
        elif brief.allow_text:
            interface_guidance = (
                "A concise generic identifying label required by the brief is permitted; use "
                "no brand name, logo, watermark, or unrelated text. "
            )
        repair_guidance = ""
        if repair_instructions:
            repairs = "; ".join(repair_instructions)
            repair_guidance = (
                f"CORRECT THESE VALIDATOR ISSUES: {repairs}. Every visible product surface must be blank "
                "and unbranded: no embossed, printed, engraved, stitched, overlaid, captioned, or watermark "
                "text unless the structured brief explicitly requires a generic identity label. "
            )
        reference_guidance = ""
        if has_reference:
            reference_guidance = (
                "REFERENCE IMAGE IS FOR COMPOSITION ONLY. Match its visible bounding-box width and height, "
                "vertical center, camera elevation, perspective, crop, lighting direction, shadow softness, "
                "and background treatment. Do not copy the reference object's identity, material, color, "
                "labels, text, controls, or product-specific details. Preserve the exact requested subject "
                "and every distinguishing attribute from this brief. "
            )
        return (
            f"Create one photorealistic {brief.exact_subject}. "
            f"It must visibly show: {attributes}. Required composition details: {required}. "
            f"{interface_guidance}{text_guidance}"
            f"{repair_guidance}{reference_guidance}"
            f"Pair style: {generation_style}. Show exactly one {brief.exact_subject}: a single object, with "
            "no duplicates, no mirrored twin, no split screen, and no collage. "
            "The full subject must be perfectly upright with no roll or tilt, "
            "with its vertical centerline aligned to the canvas midpoint. It must be centered, in sharp focus, and "
            "completely visible with a small even margin so nothing touches or is cropped by the frame edges, "
            f"occupying 85 to 92 percent of the canvas, targeting 88 percent, on a solid pure-white background extending to every edge. "
            "Use physically plausible real-world proportions, materials, and lighting; do not produce "
            "an illustration, cartoon, CGI render, or product mockup. Do not replace the complete subject with a detail, control, accessory, or one component "
            "unless that detail is explicitly the requested subject. "
            f"Use even neutral studio lighting and realistic texture. The background must be one flat white color: "
            "no checkerboard, transparency grid, scenery, horizon, wall, floor, gradient, or colored backdrop. "
            f"Negative constraints: {', '.join(negatives)}. Output one normal raster image."
        )

    @staticmethod
    def _is_digital_interface(brief: ProductImageBrief) -> bool:
        text = " ".join([
            brief.exact_subject,
            *brief.distinguishing_attributes,
            *brief.required_elements,
        ]).casefold()
        interface_terms = (
            "interface", "homepage", "webpage", "app screen", "app interface",
            "search results", "search result", "for you feed", "mobile screen",
        )
        return any(term in text for term in interface_terms)

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
