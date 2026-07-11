from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"

    llm_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    llm_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        alias="LLM_BASE_URL",
    )
    llm_model: str = Field(
        default="deepseek/deepseek-v4-flash",
        alias="LLM_MODEL",
    )
    topic_llm_model: str = Field(
        default="deepseek/deepseek-v4-flash",
        alias="TOPIC_LLM_MODEL",
    )
    script_llm_model: str = Field(
        default="deepseek/deepseek-v4-pro",
        alias="SCRIPT_LLM_MODEL",
    )
    direction_llm_model: str = Field(
        default="deepseek/deepseek-v4-flash",
        alias="DIRECTION_LLM_MODEL",
    )
    llm_fallback_model: str = Field(
        default="qwen/qwen3.5-flash-02-23",
        alias="LLM_FALLBACK_MODEL",
    )
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id_ro: str = Field(default="", alias="ELEVENLABS_VOICE_ID_RO")
    elevenlabs_voice_id_en: str = Field(default="", alias="ELEVENLABS_VOICE_ID_EN")
    search_api_key: str = Field(default="", alias="SEARCH_API_KEY")
    search_provider: str = Field(default="tavily", alias="SEARCH_PROVIDER")
    image_model: str = Field(
        default="openai/gpt-image-1-mini",
        alias="OPENROUTER_IMAGE_MODEL",
    )
    skills_path: str = Field(default="", alias="SKILLS_PATH")

    video_width: int = Field(default=1080, alias="DEFAULT_VIDEO_WIDTH")
    video_height: int = Field(default=1920, alias="DEFAULT_VIDEO_HEIGHT")
    video_fps: int = Field(default=30, alias="DEFAULT_VIDEO_FPS")
    audio_sample_rate: int = Field(default=44100, alias="DEFAULT_AUDIO_SAMPLE_RATE")

    ffmpeg_bin: str = Field(default="ffmpeg", alias="FFMPEG_BIN")
    ffprobe_bin: str = Field(default="ffprobe", alias="FFPROBE_BIN")

    mascot_set: str = Field(default="default", alias="MASCOT_SET")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def assets_dir(self) -> Path:
        return self.project_root / "assets"

    @property
    def templates_dir(self) -> Path:
        return self.project_root / "templates"

    @property
    def mascots_dir(self) -> Path:
        return self.assets_dir / "mascots" / self.mascot_set

    @property
    def fonts_dir(self) -> Path:
        return self.assets_dir / "fonts"

    @property
    def backgrounds_dir(self) -> Path:
        return self.assets_dir / "backgrounds"

    @property
    def data_dir(self) -> Path:
        return self.project_root / "data"

    def resolve_font(self, name: Optional[str] = None) -> Path:
        if name:
            p = self.fonts_dir / name
            if p.exists():
                return p
        for candidate in ("DejaVuSans-Bold.ttf", "Arial-Bold.ttf", "arialbd.ttf"):
            p = self.fonts_dir / candidate
            if p.exists():
                return p
        for candidate in (
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ):
            p = Path(candidate)
            if p.exists():
                return p
        return Path("")

    @property
    def skills_file(self) -> Optional[Path]:
        if self.skills_path:
            p = Path(self.skills_path)
            if p.exists():
                return p
        p = self.project_root / "SKILLS.md"
        if p.exists():
            return p
        return None


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_llm_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None

    skills_content = ""
    if settings.skills_file:
        skills_content = settings.skills_file.read_text(encoding="utf-8")

    from app.providers.llm.openai_provider import LLMProvider

    return LLMProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        fallback_models=[settings.llm_fallback_model],
        base_url=settings.llm_base_url,
        skills_content=skills_content,
    )


def get_topic_llm_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None

    skills_content = ""
    if settings.skills_file:
        skills_content = settings.skills_file.read_text(encoding="utf-8")

    from app.providers.llm.openai_provider import LLMProvider

    return LLMProvider(
        api_key=settings.llm_api_key,
        model=settings.topic_llm_model,
        fallback_models=[settings.llm_fallback_model],
        base_url=settings.llm_base_url,
        skills_content=skills_content,
    )


def get_script_llm_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None
    skills_content = ""
    if settings.skills_file:
        skills_content = settings.skills_file.read_text(encoding="utf-8")
    from app.providers.llm.openai_provider import LLMProvider
    return LLMProvider(
        api_key=settings.llm_api_key,
        model=settings.script_llm_model,
        fallback_models=[settings.llm_fallback_model],
        base_url=settings.llm_base_url,
        skills_content=skills_content,
    )


def get_direction_llm_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.llm_api_key:
        return None
    skills_content = ""
    if settings.skills_file:
        skills_content = settings.skills_file.read_text(encoding="utf-8")
    from app.providers.llm.openai_provider import LLMProvider
    return LLMProvider(
        api_key=settings.llm_api_key,
        model=settings.direction_llm_model,
        fallback_models=[settings.llm_fallback_model],
        base_url=settings.llm_base_url,
        skills_content=skills_content,
    )


def get_tts_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return None
    from app.providers.tts.elevenlabs_provider import ElevenLabsProvider
    return ElevenLabsProvider(
        api_key=settings.elevenlabs_api_key,
        cache_dir=settings.project_root / "cache" / "tts",
    )


def get_search_provider() -> Optional[object]:
    settings = get_settings()
    if not settings.search_api_key:
        return None
    from app.providers.search.tavily_provider import SerperProvider, TavilyProvider
    if settings.search_provider.lower() == "serper":
        return SerperProvider(api_key=settings.search_api_key)
    return TavilyProvider(api_key=settings.search_api_key)


def get_image_provider(settings: Optional[Settings] = None) -> Optional[object]:
    settings = settings or get_settings()
    if not settings.llm_api_key:
        return None
    from app.providers.images.openrouter_provider import OpenRouterImageProvider
    return OpenRouterImageProvider(
        api_key=settings.llm_api_key,
        model=settings.image_model,
        cache_dir=settings.project_root / "cache" / "images",
    )


def get_topic_history_service() -> "TopicHistoryService":
    from app.services.topic_history import TopicHistoryService

    settings = get_settings()
    return TopicHistoryService(settings.data_dir / "topic_history.json")
