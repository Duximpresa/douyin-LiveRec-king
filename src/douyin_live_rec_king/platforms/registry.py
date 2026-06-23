"""Extensible platform adapter registry and UI metadata."""

from __future__ import annotations

from collections.abc import Callable

from ..models import AppSettings, PlatformType
from .base import BasePlatformExtractor, PlatformMetadata
from .bilibili import BilibiliExtractor
from .douyin import DouyinExtractor

ExtractorFactory = Callable[[AppSettings], BasePlatformExtractor]
_FACTORIES: dict[PlatformType, ExtractorFactory] = {}
_METADATA: dict[PlatformType, PlatformMetadata] = {}


def register_extractor(
    platform: PlatformType,
    factory: ExtractorFactory,
    metadata: PlatformMetadata,
    *,
    replace: bool = False,
) -> None:
    if platform in _FACTORIES and not replace:
        raise ValueError(f"平台已注册: {platform.value}")
    _FACTORIES[platform] = factory
    _METADATA[platform] = metadata


def create_extractor(
    platform: PlatformType, settings: AppSettings | None = None
) -> BasePlatformExtractor:
    try:
        factory = _FACTORIES[platform]
    except KeyError as exc:
        raise ValueError(f"不支持的平台: {platform}") from exc
    return factory(settings or AppSettings())


def platform_metadata(platform: PlatformType) -> PlatformMetadata:
    try:
        return _METADATA[platform]
    except KeyError as exc:
        raise ValueError(f"不支持的平台: {platform}") from exc


def registered_platforms() -> tuple[PlatformMetadata, ...]:
    return tuple(_METADATA[item] for item in PlatformType if item in _METADATA)


register_extractor(
    PlatformType.DOUYIN,
    lambda settings: DouyinExtractor(
        cookie=settings.douyin_cookie,
        proxy=settings.proxy,
        quality=settings.video_quality,
        stream_source=settings.stream_source,
    ),
    PlatformMetadata(
        PlatformType.DOUYIN,
        "抖音",
        "直播间、作者主页、v.douyin.com 分享短链或 mock://offline",
        "douyin_cookie",
    ),
)
register_extractor(
    PlatformType.BILIBILI,
    lambda settings: BilibiliExtractor(
        cookie=settings.bilibili_cookie,
        proxy=settings.proxy,
        quality=settings.video_quality,
    ),
    PlatformMetadata(
        PlatformType.BILIBILI,
        "Bilibili",
        "https://live.bilibili.com/<room_id> 或 mock://offline",
        "bilibili_cookie",
    ),
)
