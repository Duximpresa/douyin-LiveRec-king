"""INI settings, JSON task persistence, and migration from the MVP config."""

from __future__ import annotations

import configparser
import json
import threading
from dataclasses import fields
from pathlib import Path

from .models import AppSettings, LiveTask, StreamSource, VideoQuality
from .utils.paths import resolve_app_path
from .utils.json_recovery import atomic_write_json, load_json_with_recovery


class SettingsStore:
    SECTION = "settings"

    def __init__(self, path: str | Path = "config/config.ini") -> None:
        self.path = resolve_app_path(path)
        self._lock = threading.RLock()

    def load(self) -> AppSettings:
        with self._lock:
            if not self.path.exists():
                settings = AppSettings()
                self.save(settings)
                return settings
            parser = configparser.ConfigParser(interpolation=None)
            parser.read(self.path, encoding="utf-8-sig")
            section = parser[self.SECTION] if parser.has_section(self.SECTION) else {}
            defaults = AppSettings()
            return AppSettings(
                output_directory=section.get("output_directory", defaults.output_directory),
                default_format=section.get("default_format", defaults.default_format).lower(),
                video_quality=VideoQuality(section.get("video_quality", defaults.video_quality.value)),
                stream_source=StreamSource(section.get("stream_source", defaults.stream_source.value).upper()),
                check_interval_seconds=max(2, int(section.get("check_interval_seconds", defaults.check_interval_seconds))),
                max_concurrent_checks=max(1, int(section.get("max_concurrent_checks", defaults.max_concurrent_checks))),
                segmented_recording=section.get("segmented_recording", str(defaults.segmented_recording)).lower() == "true",
                segment_seconds=max(60, int(section.get("segment_seconds", defaults.segment_seconds))),
                disk_threshold_gb=max(0.0, float(section.get("disk_threshold_gb", defaults.disk_threshold_gb))),
                auto_convert_mp4=section.get("auto_convert_mp4", str(defaults.auto_convert_mp4)).lower() == "true",
                delete_original=section.get("delete_original", str(defaults.delete_original)).lower() == "true",
                filename_template=section.get("filename_template", defaults.filename_template),
                folder_by_platform=section.get("folder_by_platform", str(defaults.folder_by_platform)).lower() == "true",
                folder_by_anchor=section.get("folder_by_anchor", str(defaults.folder_by_anchor)).lower() == "true",
                proxy_enabled=section.get("proxy_enabled", str(defaults.proxy_enabled)).lower() == "true",
                proxy_address=section.get("proxy_address", defaults.proxy_address),
                douyin_cookie=section.get("douyin_cookie", defaults.douyin_cookie),
                bilibili_cookie=section.get("bilibili_cookie", defaults.bilibili_cookie),
                ffmpeg_path=section.get("ffmpeg_path", defaults.ffmpeg_path),
                log_level=section.get("log_level", defaults.log_level).upper(),
                task_view=section.get("task_view", defaults.task_view),
                retry_max_attempts=max(
                    0,
                    int(section.get("retry_max_attempts", defaults.retry_max_attempts)),
                ),
                retry_delays_seconds=section.get(
                    "retry_delays_seconds", defaults.retry_delays_seconds
                ),
                max_concurrent_retries=max(
                    1,
                    int(
                        section.get(
                            "max_concurrent_retries",
                            defaults.max_concurrent_retries,
                        )
                    ),
                ),
            )

    def save(self, settings: AppSettings) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            parser = configparser.ConfigParser(interpolation=None)
            parser[self.SECTION] = {
                field.name: (
                    getattr(settings, field.name).value
                    if hasattr(getattr(settings, field.name), "value")
                    else str(getattr(settings, field.name))
                )
                for field in fields(settings)
            }
            temporary = self.path.with_suffix(".ini.tmp")
            with temporary.open("w", encoding="utf-8-sig") as handle:
                parser.write(handle)
            temporary.replace(self.path)


class TaskStore:
    def __init__(self, path: str | Path = "data/tasks.json") -> None:
        self.path = resolve_app_path(path)
        self._lock = threading.RLock()

    def load(self) -> list[LiveTask]:
        with self._lock:
            if not self.path.exists():
                self.save([])
                return []
            try:
                payload, _recovered_from = load_json_with_recovery(self.path)
                rows = payload.get("tasks", payload) if isinstance(payload, dict) else payload
                return [LiveTask.from_dict(item) for item in rows]
            except (OSError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
                raise RuntimeError(f"无法读取任务文件 {self.path}: {exc}") from exc

    def save(self, tasks: list[LiveTask]) -> None:
        self.save_snapshot([task.to_dict() for task in tasks])

    def save_snapshot(self, tasks: list[dict[str, object]]) -> None:
        with self._lock:
            atomic_write_json(self.path, {"version": 2, "tasks": tasks})


def migrate_legacy_config(
    legacy_path: str | Path = "data/config.json",
    settings_store: SettingsStore | None = None,
    task_store: TaskStore | None = None,
) -> bool:
    """Migrate the MVP combined JSON once, without deleting the legacy file."""
    legacy = resolve_app_path(legacy_path)
    settings_store = settings_store or SettingsStore()
    task_store = task_store or TaskStore()
    if not legacy.exists():
        return False
    try:
        payload = json.loads(legacy.read_text(encoding="utf-8"))
        old = payload.get("settings", {})
        settings = AppSettings(
            output_directory=old.get("output_directory", "recordings"),
            default_format=old.get("default_format", "ts"),
            check_interval_seconds=int(old.get("check_interval_seconds", 30)),
            ffmpeg_path=old.get("ffmpeg_path", ""),
            log_level=old.get("log_level", "INFO"),
            auto_convert_mp4=bool(old.get("auto_convert_mp4", False)),
        )
        tasks = [LiveTask.from_dict(item) for item in payload.get("tasks", [])]
        migrated = False
        if not settings_store.path.exists():
            settings_store.save(settings)
            migrated = True
        if not task_store.path.exists():
            task_store.save(tasks)
            migrated = True
        return migrated
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"迁移旧配置失败: {exc}") from exc


class ConfigStore:
    """Compatibility facade retained for older integrations and tests."""

    def __init__(self, path: str | Path = "data/tasks.json") -> None:
        self.tasks = TaskStore(path)

    def load(self) -> list[LiveTask]:
        return self.tasks.load()

    def save(self, tasks: list[LiveTask]) -> None:
        self.tasks.save(tasks)
