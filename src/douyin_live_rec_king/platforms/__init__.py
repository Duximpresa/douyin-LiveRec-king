from .base import BasePlatformExtractor
from .douyin import DouyinExtractor

__all__ = ["BasePlatformExtractor", "DouyinExtractor"]
from .base import PlatformMetadata
from .bilibili import BilibiliExtractor
from .douyin import DouyinExtractor
from .registry import create_extractor, platform_metadata, registered_platforms

__all__ = [
    "BilibiliExtractor",
    "DouyinExtractor",
    "PlatformMetadata",
    "create_extractor",
    "platform_metadata",
    "registered_platforms",
]
