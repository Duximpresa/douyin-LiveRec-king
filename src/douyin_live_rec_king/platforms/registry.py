"""Platform adapter factory."""

from __future__ import annotations

from ..models import AppSettings, PlatformType
from .base import BasePlatformExtractor
from .douyin import DouyinExtractor


def create_extractor(
    platform: PlatformType, settings: AppSettings | None = None
) -> BasePlatformExtractor:
    if platform is PlatformType.DOUYIN:
        settings = settings or AppSettings()
        return DouyinExtractor(
            cookie=settings.douyin_cookie,
            proxy=settings.proxy,
            quality=settings.video_quality,
            stream_source=settings.stream_source,
        )
    raise ValueError(f"不支持的平台: {platform}")
