from __future__ import annotations

import asyncio
import base64
import json
from io import BytesIO
from pathlib import Path
import wave

import httpx
import pytest
from PIL import Image, ImageDraw

from app.config import Settings, get_image_provider, get_search_provider
from app.providers.images.base import GeneratedImage
from app.domain.enums import SfxKind
from app.domain.models import PairedImageBrief, ProductImageBrief, ResearchPackage, TopicSpec
from app.providers.images.openai_provider import OpenAIImageProvider
from app.providers.images.openrouter_provider import OpenRouterImageProvider
import app.providers.images.openrouter_provider as openrouter_image_module
from app.providers.search.base import ImageCandidate, SearchResponse, SearchResult
from app.providers.search.searxng_provider import SearXNGProvider
from app.providers.search.tavily_provider import TavilyProvider
from app.services.job_cost_ledger import JobCostLedger, cost_scope
from app.services.reference_image_service import ReferenceImageService
from app.services.reference_image_brief_service import ReferenceImageBriefService
from app.services.reference_image_validator import ImageValidationResult, ReferenceImageValidator
from app.providers.llm.openai_provider import LLMProvider
from app.services.mascot_asset_preparer import MascotAssetPreparer
from app.services.mascot_service import MascotService
from app.services.sfx_service import SfxLibraryService
from scripts.check_searxng import run_check
from streamlit_app import (
    REFERENCE_LANGUAGE_LABELS,
    REFERENCE_STAGE_LABELS,
    _cost_report_rows,
    _reference_preflight,
)


def test_tavily_search_body_requests_described_images() -> None:
    provider = TavilyProvider(api_key="test")

    body = provider._build_search_body(
        query="zahăr vanilat produs fundal alb",
        max_results=5,
        include_images=True,
    )

    assert body["include_images"] is True
    assert body["include_image_descriptions"] is True


def test_searxng_maps_general_and_image_json_to_search_response() -> None:
    provider = SearXNGProvider("http://search.test")

    async def fake_get_json(params):
        if params["categories"] == "general":
            return {"results": [
                {
                    "title": "Coffee guide",
                    "url": "https://example.com/coffee",
                    "content": "A useful guide",
                    "score": 4.0,
                },
                {"title": None, "url": ""},
            ]}
        return {"results": [
            {
                "title": "Coffee beans",
                "img_src": "https://cdn.example.com/coffee.png",
                "thumbnail_src": "https://cdn.example.com/coffee-thumb.png",
                "url": "https://example.com/coffee",
                "content": "Fresh beans",
                "score": 3.0,
            },
            {
                "title": "Duplicate",
                "img_src": "https://cdn.example.com/coffee.png",
                "url": "https://example.com/duplicate",
            },
            {"title": "Missing image"},
        ]}

    provider._get_json = fake_get_json
    ledger = JobCostLedger("job-1")
    with cost_scope(ledger, "research_assets"):
        response = asyncio.run(provider.search("coffee", max_results=5, include_images=True))

    assert response.provider == "searxng"
    assert response.estimated_cost_usd == 0.0
    assert response.results[0].url == "https://example.com/coffee"
    assert response.images[0].url == "https://cdn.example.com/coffee.png"
    assert response.images[0].source_url == "https://example.com/coffee"
    assert len(response.images) == 1
    assert {event.operation for event in ledger.events} == {"web_search", "image_search"}
    assert all(event.amount_usd == 0.0 for event in ledger.events)


def test_searxng_uses_thumbnail_when_full_image_is_missing() -> None:
    provider = SearXNGProvider("http://search.test")

    async def fake_get_json(params):
        return {"results": [{
            "title": "Tea",
            "thumbnail_src": "https://cdn.example.com/tea-thumb.png",
            "source": "https://example.com/tea",
        }]}

    provider._get_json = fake_get_json
    response = asyncio.run(provider.search("tea", include_images=True))

    assert response.images[0].url == "https://cdn.example.com/tea-thumb.png"
    assert response.images[0].source_url == "https://example.com/tea"


def test_searxng_uses_url_when_no_explicit_image_field_exists() -> None:
    provider = SearXNGProvider("http://search.test")

    async def fake_get_json(params):
        return {"results": [{
            "title": "Tea package",
            "url": "https://cdn.example.com/tea.png",
            "source": "https://example.com/tea",
        }]}

    provider._get_json = fake_get_json
    response = asyncio.run(provider.search("tea", include_images=True))

    assert response.images[0].url == "https://cdn.example.com/tea.png"
    assert response.images[0].source_url == "https://example.com/tea"


def test_searxng_smoke_check_accepts_normalized_general_and_image_results() -> None:
    class Provider:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(
                query=query,
                results=[SearchResult(title="Coffee", url="https://example.com/coffee")],
                images=[ImageCandidate(url="https://cdn.example.com/coffee.png")],
                provider="searxng",
            )

    result = asyncio.run(run_check(Provider()))

    assert result.general_results == 1
    assert result.image_results == 1


def test_searxng_compose_and_settings_enable_json_and_image_search() -> None:
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    settings = (root / "searxng" / "settings.yml").read_text(encoding="utf-8")

    assert "  searxng:" in compose
    assert '"8080:8080"' not in compose
    assert "./searxng/settings.yml:/etc/searxng/settings.yml:ro" in compose
    assert "SEARXNG_BASE_URL: http://searxng:8080" in compose
    assert "- json" in settings
    assert "general" in settings
    assert "images" in settings


def test_searxng_is_default_and_needs_no_search_api_key() -> None:
    settings = Settings(_env_file=None, SEARCH_PROVIDER="searxng")

    provider = get_search_provider(settings)

    assert isinstance(provider, SearXNGProvider)
    assert provider._base_url == "http://localhost:8080"


def test_paid_search_provider_still_requires_api_key() -> None:
    settings = Settings(_env_file=None, SEARCH_PROVIDER="tavily", SEARCH_API_KEY="")

    assert get_search_provider(settings) is None


def _bread_image_brief() -> PairedImageBrief:
    return PairedImageBrief(
        shared_style=(
            "same three-quarter camera angle, centered full loaf, matching scale, "
            "neutral studio light, transparent background"
        ),
        left=ProductImageBrief(
            item="Pâine albă",
            exact_subject="single Romanian-style white bread loaf",
            distinguishing_attributes=["pale white crumb", "light golden crust"],
            required_elements=["one cut slice showing white crumb"],
            prohibited_elements=["logo", "packaging", "prominent text"],
            confusing_alternatives=["whole-wheat bread", "dark brown crumb"],
        ),
        right=ProductImageBrief(
            item="Pâine integrală",
            exact_subject="single whole-wheat bread loaf",
            distinguishing_attributes=["brown whole-grain crumb", "visible grain texture"],
            required_elements=["one cut slice showing brown crumb"],
            prohibited_elements=["logo", "packaging", "prominent text"],
            confusing_alternatives=["white bread", "pale white crumb"],
        ),
    )


def test_generated_prompt_contains_identity_pair_style_and_negatives() -> None:
    brief = _bread_image_brief()

    prompt = ReferenceImageService.build_generation_prompt(
        brief.left,
        brief.shared_style,
        [],
    )

    assert "single Romanian-style white bread loaf" in prompt
    assert "pale white crumb" in prompt
    assert "same three-quarter camera angle" in prompt
    assert "no logo" in prompt
    assert "not whole-wheat bread" in prompt
    assert "Do not replace the complete subject" in prompt
    assert "solid pure-white background" in prompt
    assert "no checkerboard" in prompt
    assert "transparent background" not in prompt
    assert "transparent PNG" not in prompt


def test_generated_prompt_requires_an_upright_centered_subject() -> None:
    prompt = ReferenceImageService.build_generation_prompt(
        _bread_image_brief().left,
        _bread_image_brief().shared_style,
        [],
    )

    assert "perfectly upright" in prompt
    assert "vertical centerline" in prompt


def test_generated_prompt_requires_physically_plausible_product_photography() -> None:
    prompt = ReferenceImageService.build_generation_prompt(
        _bread_image_brief().left,
        _bread_image_brief().shared_style,
        [],
    )

    assert "physically plausible" in prompt
    assert "do not produce an illustration" in prompt


def test_generated_prompt_relaxes_brand_text_for_digital_interfaces() -> None:
    brief = ProductImageBrief(
        item="Google search",
        exact_subject="desktop monitor displaying Google Search homepage interface",
        distinguishing_attributes=["Google Search logo", "search input field"],
        required_elements=["Google.com interface", "blue result titles"],
        allow_text=True,
    )

    prompt = ReferenceImageService.build_generation_prompt(
        brief,
        "matching studio device photography",
        [],
    )

    assert "generic but recognizable interface layout" in prompt
    assert "trademarked logo" in prompt


def test_generated_prompt_requests_an_allowed_generic_identity_label() -> None:
    brief = ProductImageBrief(
        item="Unt de migdale",
        exact_subject="creamy almond butter in a clear glass jar",
        distinguishing_attributes=["recognizable almond butter"],
        required_elements=["small generic label reading almond butter"],
        allow_text=True,
    )

    prompt = ReferenceImageService.build_generation_prompt(
        brief,
        "matching studio jar photography",
        [],
    )

    assert "concise generic identifying label required by the brief is permitted" in prompt
    assert "no brand name, logo, watermark, or unrelated text" in prompt


def test_product_image_brief_defaults_to_direct_generation_without_text() -> None:
    brief = ProductImageBrief(
        item="Frigider",
        exact_subject="freestanding refrigerator",
        distinguishing_attributes=["full-height refrigerator door"],
    )

    assert brief.requires_real_reference is False
    assert brief.image_text_language == "none"


def test_generated_prompt_uses_requested_intrinsic_text_language() -> None:
    base = {
        "item": "Etichetă produs",
        "exact_subject": "product package with an intrinsic ingredient label",
        "distinguishing_attributes": ["clear ingredient label"],
        "allow_text": True,
    }
    romanian = ProductImageBrief(**base, image_text_language="romanian")
    english = ProductImageBrief(**base, image_text_language="english")
    textless = ProductImageBrief(**base, image_text_language="none")

    romanian_prompt = ReferenceImageService.build_generation_prompt(romanian, "studio photography", [])
    english_prompt = ReferenceImageService.build_generation_prompt(english, "studio photography", [])
    textless_prompt = ReferenceImageService.build_generation_prompt(textless, "studio photography", [])

    assert "Romanian" in romanian_prompt
    assert "English" in english_prompt
    assert "no readable text" in textless_prompt.casefold()


def test_item_validator_permits_identity_defining_brand_text_for_real_reference(tmp_path: Path) -> None:
    image = tmp_path / "iphone.png"
    Image.new("RGBA", (32, 32), (255, 255, 255, 0)).save(image)
    brief = ProductImageBrief(
        item="iPhone",
        exact_subject="Apple iPhone smartphone",
        distinguishing_attributes=["Apple logo and iPhone camera arrangement"],
        requires_real_reference=True,
        image_text_language="english",
    )

    class LLM:
        def __init__(self) -> None:
            self.instruction = ""

        async def complete_structured_with_images(self, system, user, paths, model_type, **kwargs):
            self.instruction = user
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.95,
            )

    llm = LLM()
    assert asyncio.run(ReferenceImageValidator(llm).validate_item(image, brief)).accepted
    assert "expected logo, model name, or normal interface text" in llm.instruction


def test_pair_validation_rejects_an_asymmetric_composition() -> None:
    result = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=False,
        contains_prohibited_content=False,
        background_acceptable=True,
        pair_style_acceptable=True,
        composition_acceptable=False,
        confidence=0.95,
    )

    assert not result.accepted


def test_pair_repair_classification_keeps_cosmetic_issues_nonfatal() -> None:
    result = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=False,
        contains_prohibited_content=False,
        background_acceptable=True,
        pair_style_acceptable=False,
        composition_acceptable=False,
        realism_acceptable=True,
        repair_side="right",
        repair_instructions=["Match the left image scale and vertical center"],
        warning_reasons=["Right image is slightly smaller and lower"],
        confidence=0.95,
    )

    assert result.needs_repair
    assert not result.has_fatal_issues
    assert result.repair_side == "right"


def test_pair_repair_classification_keeps_unwanted_text_fatal() -> None:
    result = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=True,
        contains_prohibited_content=False,
        background_acceptable=True,
        repair_side="right",
        repair_instructions=["Remove PU SYNTHETIC LEATHER text"],
        fatal_reasons=["Right image contains unrelated text"],
        confidence=0.95,
    )

    assert result.needs_repair
    assert result.has_fatal_issues


def test_color_difference_alone_cannot_be_fatal() -> None:
    result = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=False,
        contains_prohibited_content=False,
        background_acceptable=True,
        repair_side="none",
        fatal_reasons=["Color contrast is too extreme: brown versus navy"],
        warning_reasons=["Products use different colors"],
        confidence=0.95,
    )

    assert not result.has_fatal_issues


def test_image_validation_rejects_nonrealistic_rendering() -> None:
    result = ImageValidationResult(
        depicts_requested_item=True,
        distinguishing_attributes_present=True,
        contains_logo_or_prominent_text=False,
        contains_prohibited_content=False,
        background_acceptable=True,
        pair_style_acceptable=True,
        composition_acceptable=True,
        realism_acceptable=False,
        confidence=0.95,
    )

    assert not result.accepted


def test_multimodal_request_contains_png_data_url(tmp_path: Path) -> None:
    image_path = tmp_path / "candidate.png"
    Image.new("RGBA", (8, 8), "white").save(image_path)
    provider = LLMProvider(api_key="test", model="openai/gpt-4o-mini")

    body = provider._build_multimodal_request(
        "system",
        "validate",
        [image_path],
        provider._strict_response_format(ImageValidationResult, "image_validation"),
    )

    content = body["messages"][1]["content"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_pair_validator_uses_white_mattes_for_transparent_images(tmp_path: Path) -> None:
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGBA", (32, 32), (20, 20, 20, 0)).save(left)
    Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(right)

    class LLM:
        def __init__(self) -> None:
            self.inspection_pixels = []
            self.instruction = ""

        async def complete_structured_with_images(self, system, user, paths, model_type, **kwargs):
            self.instruction = user
            self.inspection_pixels = [
                Image.open(path).convert("RGBA").getpixel((0, 0))
                for path in paths
            ]
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                pair_style_acceptable=True,
                confidence=0.95,
            )

    llm = LLM()
    result = asyncio.run(ReferenceImageValidator(llm).validate_pair(
        left,
        right,
        _bread_image_brief(),
    ))

    assert result.accepted
    assert llm.inspection_pixels == [(255, 255, 255, 255), (255, 255, 255, 255)]
    assert "Do not reject an image merely because" in llm.instruction
    assert "atmospheric cue such as steam" in llm.instruction
    assert Image.open(left).convert("RGBA").getpixel((0, 0))[3] == 0


def test_item_validator_permits_a_required_generic_identity_label(tmp_path: Path) -> None:
    image = tmp_path / "almond.png"
    Image.new("RGBA", (32, 32), (255, 255, 255, 0)).save(image)
    brief = ProductImageBrief(
        item="Unt de migdale",
        exact_subject="creamy almond butter in a clear glass jar",
        distinguishing_attributes=["recognizable almond butter"],
        required_elements=["small generic label reading almond butter"],
        allow_text=True,
    )

    class LLM:
        def __init__(self) -> None:
            self.instruction = ""

        async def complete_structured_with_images(self, system, user, paths, model_type, **kwargs):
            self.instruction = user
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.95,
            )

    llm = LLM()
    result = asyncio.run(ReferenceImageValidator(llm).validate_item(image, brief))

    assert result.accepted
    assert "Do not mark the required concise generic identity label as prominent text" in llm.instruction
    assert "Still reject brand names, logos, watermarks, and unrelated text" in llm.instruction


def test_pair_validator_permits_required_generic_identity_labels(tmp_path: Path) -> None:
    left = tmp_path / "peanut.png"
    right = tmp_path / "almond.png"
    Image.new("RGBA", (32, 32), (255, 255, 255, 0)).save(left)
    Image.new("RGBA", (32, 32), (255, 255, 255, 0)).save(right)
    brief = PairedImageBrief(
        shared_style="matching studio jar photography",
        left=ProductImageBrief(
            item="Unt de arahide",
            exact_subject="creamy peanut butter in a clear glass jar",
            distinguishing_attributes=["recognizable peanut butter"],
            required_elements=["small generic label reading peanut butter"],
            allow_text=True,
        ),
        right=ProductImageBrief(
            item="Unt de migdale",
            exact_subject="creamy almond butter in a clear glass jar",
            distinguishing_attributes=["recognizable almond butter"],
            required_elements=["small generic label reading almond butter"],
            allow_text=True,
        ),
    )

    class LLM:
        def __init__(self) -> None:
            self.instruction = ""

        async def complete_structured_with_images(self, system, user, paths, model_type, **kwargs):
            self.instruction = user
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.95,
            )

    llm = LLM()
    result = asyncio.run(ReferenceImageValidator(llm).validate_pair(left, right, brief))

    assert result.accepted
    assert "Do not mark required concise generic identity labels as prominent text" in llm.instruction
    assert "Still reject brand names, logos, watermarks, and unrelated text" in llm.instruction


def test_generated_image_bypasses_semantic_validation(tmp_path: Path) -> None:
    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(query=query)

    class Generator:
        name = "generated"

        def __init__(self) -> None:
            self.prompts = []

        async def generate(self, prompt, output_path, width=1024, height=1024):
            self.prompts.append(prompt)
            image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
            ImageDraw.Draw(image).rectangle((200, 200, 824, 824), fill="brown")
            image.save(output_path)
            return GeneratedImage(path=output_path, prompt=prompt, provider=self.name)

    class Validator:
        def __init__(self) -> None:
            self.calls = 0

        async def validate_item(self, path, brief):
            self.calls += 1
            raise AssertionError("Generated images must not be semantically validated")

    generator = Generator()
    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=generator,
        validator=Validator(),
    )

    provenance = asyncio.run(service.acquire(
        "PÃ¢ine albÄƒ",
        tmp_path / "selected.png",
        brief=_bread_image_brief().left,
    ))

    assert service.validator.calls == 0
    assert len(generator.prompts) == 1
    assert provenance.attempts[0].selected is True


def test_logo_metadata_candidate_is_rejected() -> None:
    candidate = ImageCandidate(
        url="https://static.example/images/logos/social-preview.png",
        source_title="Open Food Facts logo",
    )

    assert ReferenceImageService.metadata_rejection(candidate) == "logo or social-preview asset"


def test_reference_image_brief_service_uses_strict_pair_schema() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.calls = []

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.calls.append((system, user, model_type, kwargs))
            return _bread_image_brief()

    llm = FakeLLM()
    service = ReferenceImageBriefService(llm)
    topic = TopicSpec(
        title="Pâine albă vs Pâine integrală",
        comparison_left="Pâine albă",
        comparison_right="Pâine integrală",
    )
    research = ResearchPackage(
        topic=topic.title,
        left_item=topic.comparison_left,
        right_item=topic.comparison_right,
    )

    result = asyncio.run(service.generate(topic, research))

    assert result.left.item == "Pâine albă"
    assert llm.calls[0][2] is PairedImageBrief
    assert llm.calls[0][3]["schema_name"] == "paired_image_brief"
    assert "Never invent or exaggerate" in llm.calls[0][1]
    assert "Never make atmospheric cues mandatory" in llm.calls[0][1]


def test_reference_image_brief_service_requires_truthful_cues_for_lookalikes() -> None:
    class FakeLLM:
        def __init__(self) -> None:
            self.user_prompt = ""

        async def complete_structured(self, system, user, model_type, **kwargs):
            self.user_prompt = user
            return _bread_image_brief()

    llm = FakeLLM()
    service = ReferenceImageBriefService(llm)
    topic = TopicSpec(
        title="Unt de arahide vs Unt de migdale",
        comparison_left="Unt de arahide",
        comparison_right="Unt de migdale",
    )
    research = ResearchPackage(
        topic=topic.title,
        left_item=topic.comparison_left,
        right_item=topic.comparison_right,
    )

    asyncio.run(service.generate(topic, research))

    assert "truthful source-ingredient cue" in llm.user_prompt
    assert "concise generic identity label" in llm.user_prompt
    assert "Set allow_text to true" in llm.user_prompt
    assert "Set allow_packaging to true when that label is attached to the container" in llm.user_prompt
    assert "Never use subtle color or texture differences as the only distinction" in llm.user_prompt


def test_reference_image_brief_service_removes_mandatory_atmospheric_cues() -> None:
    hot = ProductImageBrief(
        item="Ciorbă fierbinte",
        exact_subject="Bowl of steaming hot soup with visible vapor",
        distinguishing_attributes=[
            "visible steam or vapor rising from liquid surface",
            "warm mist above the bowl",
            "recognizable ceramic soup bowl",
        ],
        required_elements=["ceramic bowl", "visible steam or vapor", "heat shimmer"],
    )
    cold = ProductImageBrief(
        item="Ciorbă rece",
        exact_subject="Bowl of chilled soup with condensation",
        distinguishing_attributes=["condensation on bowl", "recognizable ceramic soup bowl"],
        required_elements=["ceramic bowl", "cold mist"],
    )

    class FakeLLM:
        async def complete_structured(self, system, user, model_type, **kwargs):
            return PairedImageBrief(
                shared_style="matching realistic soup photography",
                left=cold,
                right=hot,
            )

    result = asyncio.run(ReferenceImageBriefService(FakeLLM()).generate(
        TopicSpec(title="Rece vs fierbinte", comparison_left="Ciorbă rece", comparison_right="Ciorbă fierbinte"),
        ResearchPackage(topic="Rece vs fierbinte", left_item="Ciorbă rece", right_item="Ciorbă fierbinte"),
    ))

    assert result.right.exact_subject == "Ciorbă fierbinte"
    assert result.right.distinguishing_attributes == ["recognizable ceramic soup bowl"]
    assert result.right.required_elements == ["ceramic bowl"]
    assert result.left.distinguishing_attributes == ["recognizable ceramic soup bowl"]
    assert result.left.required_elements == ["ceramic bowl"]


def test_image_validator_ignores_rejections_based_only_on_missing_steam(tmp_path: Path) -> None:
    image_path = tmp_path / "soup.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 0)).save(image_path)
    brief = ProductImageBrief(
        item="Ciorbă fierbinte",
        exact_subject="Bowl of steaming hot soup with visible vapor",
        distinguishing_attributes=["visible steam", "warm mist"],
        required_elements=["ceramic bowl", "heat shimmer"],
    )

    class FakeLLM:
        async def complete_structured_with_images(self, system, user, paths, model_type, **kwargs):
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=False,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                rejection_reasons=[
                    "No warm mist above the bowl",
                    "Absence of heat shimmer",
                    "Missing visible steam or vapor",
                ],
                confidence=0.95,
            )

    result = asyncio.run(ReferenceImageValidator(FakeLLM()).validate_item(image_path, brief))

    assert result.accepted
    assert result.rejection_reasons == []


def test_image_candidate_normalizes_null_optional_metadata() -> None:
    candidate = ImageCandidate(
        url="https://example.com/product.png",
        description=None,
        source_title=None,
    )

    assert candidate.description == ""
    assert candidate.source_title == ""


def test_openai_generated_fallback_requests_transparent_png() -> None:
    provider = OpenAIImageProvider(api_key="test")

    body = provider._build_generation_body("isolated coffee bag", 1024, 1024)

    assert body["model"] == "gpt-image-1-mini"
    assert body["background"] == "transparent"
    assert body["output_format"] == "png"
    assert body["quality"] == "medium"
    assert "response_format" not in body


def test_openrouter_image_provider_uses_the_router_key_and_image_api() -> None:
    settings = Settings(_env_file=None, OPENROUTER_API_KEY="router-key")

    provider = get_image_provider(settings)

    assert isinstance(provider, OpenRouterImageProvider)
    assert provider.endpoint == "https://openrouter.ai/api/v1/images"
    body = provider._build_generation_body("isolated coffee bag", 1024, 1024)
    assert body["model"] == "google/gemini-3.1-flash-lite-image"
    assert body["resolution"] == "1K"
    assert body["aspect_ratio"] == "1:1"
    assert "background" not in body
    assert "output_format" not in body
    assert "size" not in body
    assert "quality" not in body


def test_openrouter_provider_normalizes_jpeg_response_to_png(tmp_path: Path, monkeypatch) -> None:
    buffer = BytesIO()
    Image.new("RGB", (64, 64), "white").save(buffer, format="JPEG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            return httpx.Response(
                200,
                json={"data": [{"b64_json": encoded}], "usage": {"cost": 0.01}},
            )

    monkeypatch.setattr(openrouter_image_module.httpx, "AsyncClient", lambda **kwargs: Client())
    output = tmp_path / "generated.png"
    provider = OpenRouterImageProvider(api_key="test")

    asyncio.run(provider.generate("white product photo", output))

    with Image.open(output) as image:
        assert image.format == "PNG"
        assert image.mode == "RGBA"


def test_openrouter_image_provider_encodes_input_references(tmp_path: Path) -> None:
    reference = tmp_path / "reference.png"
    Image.new("RGBA", (16, 16), (20, 40, 60, 255)).save(reference)
    provider = OpenRouterImageProvider(api_key="test")

    body = provider._build_generation_body(
        "match this composition",
        1024,
        1024,
        input_references=[reference],
    )

    assert body["input_references"][0]["type"] == "image_url"
    url = body["input_references"][0]["image_url"]["url"]
    assert url.startswith("data:image/png;base64,")
    assert base64.b64decode(url.split(",", 1)[1]) == reference.read_bytes()


def test_openrouter_reference_images_affect_cache_key(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (8, 8), "red").save(first)
    Image.new("RGB", (8, 8), "blue").save(second)
    provider = OpenRouterImageProvider(api_key="test")

    first_key = provider._cache_key("repair", 1024, 1024, [first])
    second_key = provider._cache_key("repair", 1024, 1024, [second])

    assert first_key != second_key


def test_ordinary_openrouter_generation_omits_input_references() -> None:
    provider = OpenRouterImageProvider(api_key="test")

    body = provider._build_generation_body("ordinary generation", 1024, 1024)

    assert "input_references" not in body


def test_reference_guided_repair_prompt_is_detailed_and_identity_safe() -> None:
    prompt = ReferenceImageService.build_generation_prompt(
        _bread_image_brief().right,
        _bread_image_brief().shared_style,
        [],
        repair_instructions=["Remove every visible text label", "Match the left object scale"],
        has_reference=True,
    )

    assert "REFERENCE IMAGE IS FOR COMPOSITION ONLY" in prompt
    assert "visible bounding-box width and height" in prompt
    assert "vertical center" in prompt
    assert "camera elevation" in prompt
    assert "shadow softness" in prompt
    assert "Do not copy the reference object's identity" in prompt
    assert "embossed, printed, engraved, stitched" in prompt
    assert "Remove every visible text label" in prompt


def test_targeted_repair_limits_generation_to_one_attempt(tmp_path: Path) -> None:
    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(query=query, images=[])

    class Generator:
        name = "gemini-image"

        def __init__(self) -> None:
            self.calls = 0

        async def generate(self, prompt, output_path, width=1024, height=1024, **kwargs):
            self.calls += 1
            Image.new("RGB", (1024, 1024), "black").save(output_path, format="JPEG")
            return GeneratedImage(path=output_path, prompt=prompt, provider=self.name)

    generator = Generator()
    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=generator,
    )
    reference = tmp_path / "reference.png"
    Image.new("RGBA", (1024, 1024), (255, 255, 255, 0)).save(reference)

    with pytest.raises(RuntimeError, match="Generated image failed media validation"):
        asyncio.run(service.acquire(
            "Piele ecologica",
            tmp_path / "output.png",
            force_generated=True,
            input_references=[reference],
            repair_instructions=["Remove all text"],
            generated_attempt_limit=1,
        ))

    assert generator.calls == 1


def test_reference_preflight_needs_no_direct_openai_key() -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="router-key",
        ELEVENLABS_API_KEY="eleven-key",
        ELEVENLABS_VOICE_ID_RO="voice-ro",
        SEARCH_API_KEY="search-key",
    )

    assert _reference_preflight(settings, "ro") == []


def test_reference_preflight_does_not_require_search_key_for_searxng() -> None:
    settings = Settings(
        _env_file=None,
        OPENROUTER_API_KEY="router-key",
        ELEVENLABS_API_KEY="eleven-key",
        ELEVENLABS_VOICE_ID_RO="voice-ro",
        SEARCH_PROVIDER="searxng",
        SEARCH_API_KEY="",
    )

    assert "Missing SEARCH_API_KEY" not in _reference_preflight(settings, "ro")


def test_one_click_interface_uses_english_copy() -> None:
    assert REFERENCE_STAGE_LABELS["preflight"] == "Checking configuration"
    assert REFERENCE_STAGE_LABELS["research_assets"] == "Finding sources and images"
    assert REFERENCE_STAGE_LABELS["image_brief"] == "Defining the exact paired visuals"
    assert REFERENCE_STAGE_LABELS["image_validation"] == "Selecting and validating product images"
    assert REFERENCE_LANGUAGE_LABELS == {"ro": "Romanian", "en": "English"}


def test_cost_report_rows_expose_actual_and_estimated_details() -> None:
    rows = _cost_report_rows({
        "events": [{
            "stage": "tts",
            "provider": "elevenlabs",
            "model": "eleven_multilingual_v2",
            "operation": "synthesize",
            "input_units": 120,
            "output_units": 0,
            "unit_type": "characters",
            "amount_kind": "estimated",
            "amount_usd": 0.036,
            "status": "success",
            "cached": False,
        }],
    })

    assert rows[0]["Cost kind"] == "estimated"
    assert rows[0]["USD"] == "0.036000"
    assert rows[0]["Units"] == "120 characters"


def test_reference_image_service_prefers_valid_real_candidate(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    transparent = Image.new("RGBA", (800, 800), (255, 255, 255, 0))
    ImageDraw.Draw(transparent).rectangle((200, 200, 600, 600), fill=(190, 150, 70, 255))
    transparent.save(source)

    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(
                query=query,
                images=[
                    ImageCandidate(
                        url="https://official.example/product.png",
                        description="Official Zahăr vanilat package on white background",
                        source_url="https://official.example/product",
                        score=0.9,
                    )
                ],
            )

    class Downloader:
        async def download(self, url, output_path):
            output_path.write_bytes(source.read_bytes())
            return GeneratedImage(path=output_path, prompt=url, provider="remote")

    class Validator:
        async def validate_item(self, path, brief):
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.95,
            )

    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=None,
        downloader=Downloader(),
        validator=Validator(),
    )
    output = tmp_path / "selected.png"
    provenance_path = tmp_path / "provenance.json"

    provenance = asyncio.run(service.acquire(
        "Zahăr vanilat",
        output,
        provenance_path,
        brief=ProductImageBrief(
            item="Zahăr vanilat",
            exact_subject="vanilla sugar package",
            distinguishing_attributes=["vanilla sugar package"],
            requires_real_reference=True,
        ),
    ))

    assert output.exists()
    assert provenance.source_type == "real"
    assert provenance.source_url == "https://official.example/product"
    assert json.loads(provenance_path.read_text(encoding="utf-8"))["source_type"] == "real"


def test_reference_image_service_generates_when_real_candidates_fail(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.png"
    Image.new("RGB", (50, 50), "black").save(tiny)

    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(
                query=query,
                images=[ImageCandidate(url="https://bad.example/tiny.png")],
            )

    class Downloader:
        async def download(self, url, output_path):
            output_path.write_bytes(tiny.read_bytes())
            return GeneratedImage(path=output_path, prompt=url, provider="remote")

    class Generator:
        name = "gpt-image-1-mini"

        async def generate(self, prompt, output_path, width=1024, height=1024):
            image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
            ImageDraw.Draw(image).rectangle((200, 200, 824, 824), fill=(20, 120, 50, 255))
            image.save(output_path)
            return GeneratedImage(path=output_path, prompt=prompt, provider=self.name)

    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=Generator(),
        downloader=Downloader(),
    )
    output = tmp_path / "generated.png"

    provenance = asyncio.run(service.acquire(
        "Ceai verde",
        output,
        brief=ProductImageBrief(
            item="Ceai verde",
            exact_subject="green tea package",
            distinguishing_attributes=["green tea leaves"],
            requires_real_reference=True,
        ),
    ))

    assert provenance.source_type == "generated"
    assert provenance.provider == "gpt-image-1-mini"
    assert Image.open(output).getextrema()[-1][0] == 0


def test_reference_image_service_skips_search_for_generic_object(tmp_path: Path) -> None:
    class Search:
        async def search(self, *args, **kwargs):
            raise AssertionError("Generic objects must not use image search")

    class Generator:
        name = "gemini-image"

        async def generate(self, prompt, output_path, width=1024, height=1024):
            image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
            ImageDraw.Draw(image).rectangle((200, 100, 824, 924), fill=(210, 210, 210, 255))
            image.save(output_path)
            return GeneratedImage(path=output_path, prompt=prompt, provider=self.name)

    service = ReferenceImageService(search_provider=Search(), generated_provider=Generator())
    provenance = asyncio.run(service.acquire(
        "Frigider",
        tmp_path / "fridge.png",
        brief=ProductImageBrief(
            item="Frigider",
            exact_subject="freestanding refrigerator",
            distinguishing_attributes=["full-height refrigerator door"],
        ),
    ))

    assert provenance.source_type == "generated"
    assert provenance.candidates_tried == 0


def test_reference_image_service_tries_three_search_candidates_then_generates_without_validation(tmp_path: Path) -> None:
    source = tmp_path / "candidate.png"
    image = Image.new("RGBA", (800, 800), (255, 255, 255, 0))
    ImageDraw.Draw(image).ellipse((150, 150, 650, 650), fill=(100, 100, 100, 255))
    image.save(source)

    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(
                query=query,
                images=[ImageCandidate(url=f"https://example.com/{index}.png") for index in range(4)],
            )

    class Downloader:
        async def download(self, url, output_path):
            output_path.write_bytes(source.read_bytes())
            return GeneratedImage(path=output_path, prompt=url, provider="remote")

    class Validator:
        def __init__(self) -> None:
            self.calls = 0

        async def validate_item(self, path, brief):
            self.calls += 1
            return ImageValidationResult(
                depicts_requested_item=False,
                distinguishing_attributes_present=False,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.1,
                rejection_reasons=["wrong identity"],
            )

    class Generator:
        name = "gemini-image"

        async def generate(self, prompt, output_path, width=1024, height=1024):
            image = Image.new("RGBA", (1024, 1024), (255, 255, 255, 0))
            ImageDraw.Draw(image).ellipse((200, 200, 824, 824), fill=(40, 40, 40, 255))
            image.save(output_path)
            return GeneratedImage(path=output_path, prompt=prompt, provider=self.name)

    validator = Validator()
    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=Generator(),
        downloader=Downloader(),
        validator=validator,
        max_candidates=3,
    )
    provenance = asyncio.run(service.acquire(
        "iPhone",
        tmp_path / "iphone.png",
        brief=ProductImageBrief(
            item="iPhone",
            exact_subject="Apple iPhone smartphone",
            distinguishing_attributes=["Apple camera arrangement"],
            requires_real_reference=True,
        ),
    ))

    assert validator.calls == 3
    assert provenance.source_type == "generated"
    assert provenance.candidates_tried == 3
    assert all(attempt.semantic_result is None for attempt in provenance.attempts if attempt.source_type == "generated")


def test_reference_image_service_removes_solid_generated_background(tmp_path: Path) -> None:
    class Search:
        async def search(self, query, max_results=10, include_images=False):
            return SearchResponse(query=query, images=[])

    class Generator:
        name = "gemini-image"

        async def generate(self, prompt, output_path, width=1024, height=1024):
            image = Image.new("RGB", (1024, 1024), "white")
            ImageDraw.Draw(image).ellipse((220, 180, 804, 900), fill=(25, 30, 35))
            image.save(output_path, format="JPEG")
            return GeneratedImage(path=output_path, prompt=prompt, provider=self.name)

    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=Generator(),
    )
    output = tmp_path / "generated.png"

    provenance = asyncio.run(service.acquire("Casti cablate", output))

    assert provenance.source_type == "generated"
    with Image.open(output) as source:
        assert source.format == "PNG"
        image = source.convert("RGBA")
    assert image.getchannel("A").getextrema() == (0, 255)


def test_mascot_preparer_removes_only_border_connected_background(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    destination = tmp_path / "prepared.png"
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 20, 80, 90), fill=(220, 120, 30, 255), outline=(10, 10, 10, 255), width=4)
    draw.ellipse((40, 40, 60, 60), fill=(255, 255, 255, 255), outline=(10, 10, 10, 255), width=3)
    image.save(source)

    MascotAssetPreparer(canvas_size=(128, 128), padding=8).prepare(source, destination)

    prepared = Image.open(destination).convert("RGBA")
    alpha = prepared.getchannel("A")
    assert alpha.getextrema()[0] == 0
    assert prepared.getpixel((0, 0))[3] == 0
    raw = prepared.tobytes()
    opaque_white_pixels = sum(
        1
        for index in range(0, len(raw), 4)
        if raw[index] > 245
        and raw[index + 1] > 245
        and raw[index + 2] > 245
        and raw[index + 3] > 220
    )
    assert opaque_white_pixels > 0
    assert alpha.getbbox()[3] == 120


def test_mascot_validation_rejects_opaque_alpha_and_border(tmp_path: Path) -> None:
    mascot_dir = tmp_path / "mascot"
    mascot_dir.mkdir()
    (mascot_dir / "mascot_meta.json").write_text(
        json.dumps({
            "canvas_width": 64,
            "canvas_height": 64,
            "poses": {"neutral": "neutral.png"},
        }),
        encoding="utf-8",
    )
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(mascot_dir / "neutral.png")

    problems = MascotService(mascot_dir).validate_pose_images(["neutral"])

    assert any("transparent" in problem.lower() for problem in problems)


def test_sfx_library_is_generated_as_deterministic_mono_wav(tmp_path: Path) -> None:
    service = SfxLibraryService(sample_rate=44100)

    paths = service.ensure_library(tmp_path)

    assert set(paths) == {
        SfxKind.WHOOSH,
        SfxKind.POSE_POP,
        SfxKind.FOCUS_TICK,
        SfxKind.CTA_STING,
    }
    for path in paths.values():
        with wave.open(str(path), "rb") as audio:
            assert audio.getframerate() == 44100
            assert audio.getnchannels() == 1
            assert audio.getnframes() > 1000
    first_bytes = paths[SfxKind.WHOOSH].read_bytes()
    paths[SfxKind.WHOOSH].unlink()
    regenerated = service.ensure_library(tmp_path)[SfxKind.WHOOSH].read_bytes()
    assert regenerated == first_bytes
