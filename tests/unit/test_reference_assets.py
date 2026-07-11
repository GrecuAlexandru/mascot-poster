from __future__ import annotations

import asyncio
import json
from pathlib import Path
import wave

from PIL import Image, ImageDraw

from app.config import Settings, get_image_provider
from app.providers.images.base import GeneratedImage
from app.domain.enums import SfxKind
from app.providers.images.openai_provider import OpenAIImageProvider
from app.providers.images.openrouter_provider import OpenRouterImageProvider
from app.providers.search.base import ImageCandidate, SearchResponse
from app.providers.search.tavily_provider import TavilyProvider
from app.services.reference_image_service import ReferenceImageService
from app.services.mascot_asset_preparer import MascotAssetPreparer
from app.services.mascot_service import MascotService
from app.services.sfx_service import SfxLibraryService
from streamlit_app import REFERENCE_LANGUAGE_LABELS, REFERENCE_STAGE_LABELS, _reference_preflight


def test_tavily_search_body_requests_described_images() -> None:
    provider = TavilyProvider(api_key="test")

    body = provider._build_search_body(
        query="zahăr vanilat produs fundal alb",
        max_results=5,
        include_images=True,
    )

    assert body["include_images"] is True
    assert body["include_image_descriptions"] is True


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


def test_one_click_interface_uses_english_copy() -> None:
    assert REFERENCE_STAGE_LABELS["preflight"] == "Checking configuration"
    assert REFERENCE_STAGE_LABELS["research_assets"] == "Finding sources and images"
    assert REFERENCE_LANGUAGE_LABELS == {"ro": "Romanian", "en": "English"}


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
