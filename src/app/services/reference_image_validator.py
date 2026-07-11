from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image
from pydantic import BaseModel, Field

from app.domain.models import PairedImageBrief, ProductImageBrief


class ImageValidationResult(BaseModel):
    depicts_requested_item: bool
    distinguishing_attributes_present: bool
    contains_logo_or_prominent_text: bool
    contains_prohibited_content: bool
    background_acceptable: bool
    pair_style_acceptable: bool = True
    rejection_reasons: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    @property
    def accepted(self) -> bool:
        return (
            self.depicts_requested_item
            and self.distinguishing_attributes_present
            and not self.contains_logo_or_prominent_text
            and not self.contains_prohibited_content
            and self.background_acceptable
            and self.pair_style_acceptable
            and self.confidence >= 0.8
        )


class ReferenceImageValidator:
    def __init__(self, llm: object):
        self.llm = llm

    async def validate_item(
        self,
        image_path: Path,
        brief: ProductImageBrief,
    ) -> ImageValidationResult:
        with TemporaryDirectory(prefix="reference-image-validation-") as directory:
            inspection_path = self._white_matte(image_path, Path(directory) / "image.png")
            return await self.llm.complete_structured_with_images(
                "You are a strict product-image quality inspector. Reject ambiguity.",
                (
                    "Inspect this candidate against the structured brief. Confirm the exact object and "
                    "its distinguishing visual attributes. Reject logos, prominent text, prohibited "
                    f"content, bad backgrounds, or confusing alternatives. Brief: {brief.model_dump_json()}"
                ),
                [inspection_path],
                ImageValidationResult,
                schema_name="product_image_validation",
                temperature=0.0,
                max_tokens=1200,
            )

    async def validate_pair(
        self,
        left_path: Path,
        right_path: Path,
        brief: PairedImageBrief,
    ) -> ImageValidationResult:
        with TemporaryDirectory(prefix="reference-image-validation-") as directory:
            base = Path(directory)
            inspection_paths = [
                self._white_matte(left_path, base / "left.png"),
                self._white_matte(right_path, base / "right.png"),
            ]
            return await self.llm.complete_structured_with_images(
                "You are a strict paired product-image quality inspector.",
                (
                    "The first image is left and the second is right. Confirm both exact identities, "
                    "clear visual distinction, matching angle, scale, crop, lighting and background. "
                    "Both inspection images are composited over the same pure-white background; evaluate "
                    "the visible product and composition, not transparent pixels. Reject black, dark, scenic, "
                    "or mismatched opaque backgrounds. Reject a component or close-up detail when the brief "
                    f"requests a complete subject. Paired brief: {brief.model_dump_json()}"
                ),
                inspection_paths,
                ImageValidationResult,
                schema_name="paired_image_validation",
                temperature=0.0,
                max_tokens=1200,
            )

    @staticmethod
    def _white_matte(source_path: Path, destination_path: Path) -> Path:
        source = Image.open(source_path).convert("RGBA")
        matte = Image.new("RGBA", source.size, (255, 255, 255, 255))
        matte.alpha_composite(source)
        matte.convert("RGB").save(destination_path, format="PNG")
        return destination_path
