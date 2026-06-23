"""Contract implemented by every live-stream platform adapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..models import LiveStatus, PlatformType


@dataclass(frozen=True, slots=True)
class PlatformMetadata:
    type: PlatformType
    display_name: str
    url_placeholder: str
    cookie_setting: str


class BasePlatformExtractor(ABC):
    @abstractmethod
    def normalize_url(self, url: str) -> str:
        """Return a canonical URL accepted by the platform adapter."""

    @abstractmethod
    def check_live_status(self, url: str) -> LiveStatus:
        """Fetch current live status without raising routine network errors."""

    @abstractmethod
    def get_stream_url(self, url: str) -> str | None:
        """Return a playable stream URL when live, otherwise None."""
