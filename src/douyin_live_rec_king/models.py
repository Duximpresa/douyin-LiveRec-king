"""Typed domain models for tasks, settings, live status, and recording state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class PlatformType(StrEnum):
    DOUYIN = "douyin"


class TaskStatus(StrEnum):
    IDLE = "未开播"
    CHECKING = "检测中"
    RECORDING = "录制中"
    ERROR = "错误"
    DISABLED = "已禁用"


class NicknameSource(StrEnum):
    AUTO = "auto"
    CUSTOM = "custom"


class StreamSource(StrEnum):
    HLS = "HLS"
    FLV = "FLV"


class VideoQuality(StrEnum):
    OD = "OD"
    UHD = "UHD"
    HD = "HD"
    SD = "SD"
    LD = "LD"


@dataclass(slots=True)
class LiveStatus:
    is_live: bool
    title: str | None = None
    anchor_name: str | None = None
    stream_url: str | None = None
    hls_url: str | None = None
    flv_url: str | None = None
    canonical_url: str | None = None
    quality: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    parser_error: str | None = None


@dataclass(slots=True)
class LiveTask:
    url: str
    anchor_name: str = ""
    platform: PlatformType = PlatformType.DOUYIN
    enabled: bool = True
    id: str = field(default_factory=lambda: uuid4().hex)
    canonical_url: str | None = None
    platform_anchor_name: str | None = None
    nickname_source: NicknameSource = NicknameSource.AUTO
    status: TaskStatus = TaskStatus.IDLE
    recording_file: str | None = None
    last_checked_at: str | None = None
    last_error: str | None = None

    @property
    def display_name(self) -> str:
        return self.anchor_name or self.platform_anchor_name or "等待获取主播昵称"

    def set_manual_name(self, value: str) -> None:
        self.anchor_name = value.strip()
        self.nickname_source = (
            NicknameSource.CUSTOM if self.anchor_name else NicknameSource.AUTO
        )

    def apply_platform_name(self, value: str | None) -> None:
        if not value:
            return
        self.platform_anchor_name = value.strip()
        if self.nickname_source is NicknameSource.AUTO:
            self.anchor_name = self.platform_anchor_name

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["platform"] = self.platform.value
        data["nickname_source"] = self.nickname_source.value
        data["status"] = self.status.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LiveTask":
        payload = dict(data)
        payload["platform"] = PlatformType(payload.get("platform", "douyin"))
        payload["status"] = TaskStatus(payload.get("status", TaskStatus.IDLE.value))
        source = payload.get("nickname_source")
        if source is None:
            source = "custom" if payload.get("anchor_name") else "auto"
        payload["nickname_source"] = NicknameSource(source)
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in payload.items() if key in allowed})

    def mark_checked(self) -> None:
        self.last_checked_at = datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass(slots=True)
class AppSettings:
    output_directory: str = "recordings"
    default_format: str = "ts"
    video_quality: VideoQuality = VideoQuality.OD
    stream_source: StreamSource = StreamSource.HLS
    check_interval_seconds: int = 30
    max_concurrent_checks: int = 3
    segmented_recording: bool = False
    segment_seconds: int = 1800
    disk_threshold_gb: float = 1.0
    auto_convert_mp4: bool = False
    delete_original: bool = False
    filename_template: str = "{platform}_{anchor}_{time}"
    folder_by_platform: bool = False
    folder_by_anchor: bool = False
    proxy_enabled: bool = False
    proxy_address: str = ""
    douyin_cookie: str = ""
    ffmpeg_path: str = ""
    log_level: str = "INFO"
    task_view: str = "table"

    @property
    def proxy(self) -> str | None:
        return self.proxy_address.strip() if self.proxy_enabled else None

