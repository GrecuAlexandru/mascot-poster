from __future__ import annotations

import asyncio
import json
from pathlib import Path
import wave

from PIL import Image, ImageDraw

from app.config import Settings, get_image_provider, get_search_provider
from app.providers.images.base import GeneratedImage
from app.domain.enums import SfxKind
from app.domain.models import PairedImageBrief, ProductImageBrief, ResearchPackage, TopicSpec
from app.providers.images.openai_provider import OpenAIImageProvider
from app.providers.images.openrouter_provider import OpenRouterImageProvider
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
    assert '"8080:8080"' in compose
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

        async def complete_structured_with_images(self, system, user, paths, model_type, **kwargs):
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
    assert Image.open(left).convert("RGBA").getpixel((0, 0))[3] == 0


def test_generated_retry_uses_semantic_feedback(tmp_path: Path) -> None:
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
            if self.calls == 1:
                return ImageValidationResult(
                    depicts_requested_item=False,
                    distinguishing_attributes_present=False,
                    contains_logo_or_prominent_text=False,
                    contains_prohibited_content=True,
                    background_acceptable=True,
                    rejection_reasons=["looks like whole-wheat bread"],
                    confidence=0.95,
                )
            return ImageValidationResult(
                depicts_requested_item=True,
                distinguishing_attributes_present=True,
                contains_logo_or_prominent_text=False,
                contains_prohibited_content=False,
                background_acceptable=True,
                confidence=0.95,
            )

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

    assert provenance.attempts[0].rejection_reasons == ["looks like whole-wheat bread"]
    assert "looks like whole-wheat bread" in generator.prompts[1]
    assert provenance.attempts[-1].selected is True


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
    assert body["model"] == "openai/gpt-image-1-mini"
    assert body["background"] == "transparent"
    assert body["output_format"] == "png"


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
    Image.new("RGB", (800, 800), "white").save(source)

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

    service = ReferenceImageService(
        search_provider=Search(),
        generated_provider=None,
        downloader=Downloader(),
    )
    output = tmp_path / "selected.png"
    provenance_path = tmp_path / "provenance.json"

    provenance = asyncio.run(
        service.acquire("Zahăr vanilat", output, provenance_path)
    )

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

    provenance = asyncio.run(service.acquire("Ceai verde", output))

    assert provenance.source_type == "generated"
    assert provenance.provider == "gpt-image-1-mini"
    assert Image.open(output).getextrema()[-1][0] == 0


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
