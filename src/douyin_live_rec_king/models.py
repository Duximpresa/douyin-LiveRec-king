"""Typed domain models for tasks, settings, live status, and recording state."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class PlatformType(StrEnum):
    DOUYIN = "douyin"
    BILIBILI = "bilibili"


class TaskStatus(StrEnum):
    IDLE = "未开播"
    MONITORING = "监控中"
    CHECKING = "检测中"
    LIVE_DETECTED = "已开播"
    STARTING_RECORD = "启动录制中"
    RECORDING = "录制中"
    STOPPING = "停止中"
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


class RecordingExitReason(StrEnum):
    COMPLETED = "completed"
    MANUAL_STOP = "manual_stop"
    LIVE_ENDED = "live_ended"
    NETWORK_ERROR = "network_error"
    PARSER_ERROR = "parser_error"
    AUTH_ERROR = "auth_error"
    STORAGE_ERROR = "storage_error"
    FFMPEG_ERROR = "ffmpeg_error"
    CONVERSION_ERROR = "conversion_error"
    INTERRUPTED = "interrupted"


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
    headers: dict[str, str] = field(default_factory=dict)
    user_agent: str | None = None
    referer: str | None = None
    cookie: str | None = None


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
    retry_count: int = 0
    next_retry_at: str | None = None

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
        platform_value = payload.get("platform", PlatformType.DOUYIN.value)
        try:
            payload["platform"] = PlatformType(platform_value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"不支持的平台: {platform_value}") from exc
        payload["status"] = cls._parse_status(payload.get("status"))
        source = payload.get("nickname_source")
        if source is None:
            source = "custom" if payload.get("anchor_name") else "auto"
        payload["nickname_source"] = NicknameSource(source)
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{key: value for key, value in payload.items() if key in allowed})

    @staticmethod
    def _parse_status(value: object) -> TaskStatus:
        if isinstance(value, TaskStatus):
            return value
        if value is None:
            return TaskStatus.IDLE
        text = str(value).strip()
        legacy = {
            "空闲": TaskStatus.IDLE,
            "未开播": TaskStatus.IDLE,
            "监控中": TaskStatus.MONITORING,
            "检测中": TaskStatus.CHECKING,
            "已开播": TaskStatus.LIVE_DETECTED,
            "启动录制中": TaskStatus.STARTING_RECORD,
            "录制中": TaskStatus.RECORDING,
            "停止中": TaskStatus.STOPPING,
            "错误": TaskStatus.ERROR,
            "已禁用": TaskStatus.DISABLED,
        }
        if text in legacy:
            return legacy[text]
        try:
            return TaskStatus[text.upper()]
        except (KeyError, AttributeError):
            try:
                return TaskStatus(text)
            except ValueError:
                return TaskStatus.IDLE

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
    bilibili_cookie: str = ""
    ffmpeg_path: str = ""
    log_level: str = "INFO"
    task_view: str = "table"
    retry_max_attempts: int = 3
    retry_delays_seconds: str = "5,15,45"
    max_concurrent_retries: int = 2

    @property
    def proxy(self) -> str | None:
        return self.proxy_address.strip() if self.proxy_enabled else None

    @property
    def retry_delays(self) -> tuple[int, ...]:
        values: list[int] = []
        for item in self.retry_delays_seconds.split(","):
            try:
                values.append(max(1, int(item.strip())))
            except ValueError:
                continue
        return tuple(values) or (5, 15, 45)
