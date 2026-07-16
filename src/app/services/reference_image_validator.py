from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from PIL import Image
from pydantic import BaseModel, Field

from app.domain.models import PairedImageBrief, ProductImageBrief
from app.services.reference_image_brief_service import (
    is_atmospheric_absence_reason,
    observable_image_brief,
)


_VALIDATE_ITEM_SYSTEM = (
    "You are a strict product-image quality inspector for a comparison-video channel. You reject "
    "ambiguity: if you cannot clearly confirm the exact object and its distinguishing attributes, "
    "you fail the image. You judge only what a still photograph can actually prove, and you return "
    "structured JSON only."
)

_VALIDATE_PAIR_SYSTEM = (
    "You are a strict paired product-image quality inspector for a comparison-video channel. You "
    "confirm that the two images show the two requested items, that they are clearly distinct, and "
    "that they match as a photographic pair. You judge only what still photographs can prove, and "
    "you return structured JSON only."
)

_VALIDATE_ITEM_GUIDE = (
    "DECISION CHECKLIST (set every boolean, then list the reasons): depicts_requested_item - is "
    "this unmistakably the exact_subject from the brief? distinguishing_attributes_present - are "
    "the brief's visible attributes actually shown? contains_logo_or_prominent_text and "
    "contains_prohibited_content - per the content rules above. background_acceptable - clean white "
    "with no scenery, colour cast, or dark or busy backdrop? realism_acceptable - believable "
    "photography (true) rather than a cartoon, illustration, or physically impossible render "
    "(false)? composition_acceptable - upright, centered, full object, sensible scale? confidence - "
    "your certainty from zero to one; below 0.8 the app treats the image as failing, so go high only "
    "when you are sure. Put wrong identity, missing defining attributes, unwanted text or logos, "
    "prohibited content, an unusable background, or clearly fake imagery in fatal_reasons; put "
    "softer issues such as slight scale, crop, or lighting in warning_reasons; and when something is "
    "wrong set repair_side and give short imperative repair_instructions. "
    "ACCEPT, for example: a clean studio photo of the exact object on white, even with polished "
    "lighting and crisp reflections; a required source cue such as whole peanuts beside the jar is "
    "visible. REJECT, for example: the object is actually a lookalike (almond butter when peanut "
    "butter was requested); a brand logo is stamped on it; the background is a wooden table; it is a "
    "flat cartoon drawing; the subject is tilted; or it is a close-up of one part instead of the "
    "whole object. "
)

_VALIDATE_PAIR_GUIDE = (
    "Worked calls to guide your judgment. ACCEPT, for example: two matched studio photos where a "
    "butter block on the left and a margarine tub on the right share the angle, scale, crop, and "
    "white background, even though their colours differ. REJECT, for example: one image is a "
    "component close-up while the other is a whole object; the two sit at clearly different heights "
    "or apparent scales; one has a dark or scenic background; or either is a stylized illustration "
    "rather than a believable photograph. "
)


class ImageValidationResult(BaseModel):
    depicts_requested_item: bool
    distinguishing_attributes_present: bool
    contains_logo_or_prominent_text: bool
    contains_prohibited_content: bool
    background_acceptable: bool
    pair_style_acceptable: bool = True
    composition_acceptable: bool = True
    realism_acceptable: bool = True
    rejection_reasons: list[str] = Field(default_factory=list)
    repair_side: Literal["left", "right", "both", "none"] = "none"
    repair_instructions: list[str] = Field(default_factory=list)
    fatal_reasons: list[str] = Field(default_factory=list)
    warning_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @staticmethod
    def _color_pair_reason(reason: str) -> bool:
        lowered = reason.casefold()
        return "color" in lowered and any(
            term in lowered
            for term in ("contrast", "versus", " vs ", "different", "matching")
        )

    @property
    def has_fatal_issues(self) -> bool:
        classified_fatal = any(
            not self._color_pair_reason(reason)
            for reason in self.fatal_reasons
        )
        return (
            not self.depicts_requested_item
            or not self.distinguishing_attributes_present
            or self.contains_logo_or_prominent_text
            or self.contains_prohibited_content
            or not self.background_acceptable
            or not self.realism_acceptable
            or self.confidence < 0.8
            or classified_fatal
        )

    @property
    def needs_repair(self) -> bool:
        return (
            self.repair_side != "none"
            or self.has_fatal_issues
            or not self.pair_style_acceptable
            or not self.composition_acceptable
        )

    @property
    def accepted(self) -> bool:
        return (
            not self.has_fatal_issues
            and self.pair_style_acceptable
            and self.composition_acceptable
        )


class ReferenceImageValidator:
    def __init__(self, llm: object):
        self.llm = llm

    async def validate_item(
        self,
        image_path: Path,
        brief: ProductImageBrief,
    ) -> ImageValidationResult:
        validation_brief = observable_image_brief(brief)
        with TemporaryDirectory(prefix="reference-image-validation-") as directory:
            inspection_path = self._white_matte(image_path, Path(directory) / "image.png")
            interface_guidance = ""
            content_rejection = (
                "Reject logos, prominent text, prohibited content, non-white background remnants (scenery, "
                "color casts, dark or busy backdrops), or confusing alternatives. "
            )
            if brief.allow_text:
                content_rejection = (
                    "Do not mark the required concise generic identity label as prominent text. "
                    "Still reject brand names, logos, watermarks, and unrelated text, prohibited content, "
                    "non-white background remnants, or confusing alternatives. "
                )
            if brief.requires_real_reference:
                content_rejection = (
                    "Do not mark expected logo, model name, or normal interface text that directly proves "
                    "the requested real-world identity as prominent text. Still reject unrelated headers, "
                    "advertising copy, watermarks, prohibited content, non-white background remnants, or "
                    "confusing alternatives. "
                )
            if self._is_digital_interface(brief):
                interface_guidance = (
                    "For a digital interface, accept the correct device form factor and generic interface "
                    "structure as the requested identity. Do not require a trademarked logo, platform name, "
                    "legible interface copy, or pixel-perfect UI even if the brief mentions them. "
                )
                content_rejection = (
                    "Reject only watermarks, unrelated text outside the screen, prohibited content, non-white "
                    "background remnants (scenery, color casts, dark or busy backdrops), or confusing alternatives. "
                    "Do not mark ordinary interface text or an incidental in-screen brand mark as prominent text. "
                )
            result = await self.llm.complete_structured_with_images(
                _VALIDATE_ITEM_SYSTEM,
                (
                    "Inspect this candidate against the structured brief. Confirm the exact object and "
                    "its distinguishing visual attributes. This inspection image is composited over a "
                    "pure-white background; evaluate the visible product and composition, not the plain "
                    "white matte itself. Judge only what a still photo can prove: ignore brief "
                    "requirements about exact temperatures, degrees, tastes, smells, durations, or "
                    "measurements — for those, accept any plausible visible proxy (steam, condensation, "
                    "texture) and never reject solely because such a property cannot be seen. Do not "
                    "treat an atmospheric cue such as steam as mandatory evidence; its absence cannot "
                    "reject an otherwise valid product image. Require "
                    "natural, physically plausible product photography with real-world materials, "
                    "colors, proportions, and lighting. Do not reject an image merely because it has "
                    "clean studio lighting, polished materials, crisp reflections, or an idealized composition; "
                    "a photorealistic AI-generated or studio product image is acceptable when it remains believable. "
                    "Set realism_acceptable to false only for a clearly stylized illustration, cartoon, "
                    "or physically implausible appearance. "
                    + _VALIDATE_ITEM_GUIDE
                    + f"{content_rejection}{interface_guidance}Brief: {validation_brief.model_dump_json()}"
                ),
                [inspection_path],
                ImageValidationResult,
                schema_name="product_image_validation",
                temperature=0.0,
                max_tokens=1200,
            )
            return self._apply_observability_policy(result)

    async def validate_pair(
        self,
        left_path: Path,
        right_path: Path,
        brief: PairedImageBrief,
    ) -> ImageValidationResult:
        validation_brief = brief.model_copy(update={
            "left": observable_image_brief(brief.left),
            "right": observable_image_brief(brief.right),
        })
        with TemporaryDirectory(prefix="reference-image-validation-") as directory:
            base = Path(directory)
            inspection_paths = [
                self._white_matte(left_path, base / "left.png"),
                self._white_matte(right_path, base / "right.png"),
            ]
            interface_guidance = ""
            content_rejection = ""
            if brief.left.allow_text or brief.right.allow_text:
                content_rejection = (
                    "Do not mark required concise generic identity labels as prominent text. "
                    "Still reject brand names, logos, watermarks, and unrelated text. "
                )
            if self._is_digital_interface(brief.left) or self._is_digital_interface(brief.right):
                interface_guidance = (
                    "For digital interfaces, assess the device form factor and generic layout contrast, such as "
                    "search versus short-video discovery. Do not require trademarked logos, platform names, "
                    "legible interface copy, or pixel-perfect UI. "
                )
                content_rejection = (
                    "Do not mark ordinary interface text or incidental in-screen brand marks as prominent text. "
                )
            result = await self.llm.complete_structured_with_images(
                _VALIDATE_PAIR_SYSTEM,
                (
                    "The first image is left and the second is right. Confirm both exact identities, "
                    "clear visual distinction, matching angle, scale, crop, lighting and background. "
                    "Both products must be perfectly upright, centered on their own canvas, and "
                    "positioned symmetrically as a pair. Reject either image if the object is tilted, "
                    "visibly shifted toward or away from the middle, or has a materially different "
                    "apparent scale or vertical placement. Set composition_acceptable to false for "
                    "any of those defects. "
                    "Both inspection images are composited over the same pure-white background; evaluate "
                    "the visible product and composition, not transparent pixels. Judge only what a "
                    "still photo can prove: ignore brief requirements about exact temperatures, degrees, "
                    "tastes, smells, durations, or measurements, and never reject solely because such a "
                    "property cannot be seen. Do not treat an atmospheric cue such as steam as mandatory "
                    "evidence; its absence cannot reject an otherwise valid product image. Require natural, physically plausible product photography "
                    "with real-world materials, colors, proportions, and lighting. Do not reject an image merely "
                    "because it has clean studio lighting, polished materials, crisp reflections, or an idealized "
                    "composition; a photorealistic AI-generated or studio product image is acceptable when it remains "
                    "believable. Set realism_acceptable to false only for a clearly stylized illustration, cartoon, "
                    "or physically implausible appearance. Both sides must share a consistent photographic style. Reject black, dark, scenic, "
                    "or mismatched opaque backgrounds. Reject a component or close-up detail when the brief "
                    "requests a complete subject. Classify every problem. Put wrong identity, missing defining "
                    "attributes, unwanted text, logos, prohibited content, unusable background, or clearly fake "
                    "imagery in fatal_reasons. Put scale, position, crop, angle, lighting, shadow, and photographic "
                    "style differences in warning_reasons. Set repair_side to left, right, both, or none and return "
                    "short imperative repair_instructions that an image generator can follow. Never reject, repair, "
                    "or warn merely because the two compared products have different colors unless the paired brief "
                    "explicitly requires matching colors. Different product colors are normal and can help communicate "
                    "the comparison. "
                    + _VALIDATE_PAIR_GUIDE
                    + f"Paired brief: {validation_brief.model_dump_json()}"
                    + f"{interface_guidance}{content_rejection}"
                ),
                inspection_paths,
                ImageValidationResult,
                schema_name="paired_image_validation",
                temperature=0.0,
                max_tokens=1200,
            )
            return self._apply_observability_policy(result)

    @staticmethod
    def _apply_observability_policy(result: ImageValidationResult) -> ImageValidationResult:
        retained_reasons = [
            reason
            for reason in result.rejection_reasons
            if not is_atmospheric_absence_reason(reason)
        ]
        if len(retained_reasons) == len(result.rejection_reasons):
            return result
        update: dict = {"rejection_reasons": retained_reasons}
        if not retained_reasons:
            update["distinguishing_attributes_present"] = True
        return result.model_copy(update=update)

    @staticmethod
    def _white_matte(source_path: Path, destination_path: Path) -> Path:
        source = Image.open(source_path).convert("RGBA")
        matte = Image.new("RGBA", source.size, (255, 255, 255, 255))
        matte.alpha_composite(source)
        matte.convert("RGB").save(destination_path, format="PNG")
        return destination_path

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
