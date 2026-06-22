import json
from pathlib import Path

from douyin_live_rec_king.config import SettingsStore, TaskStore, migrate_legacy_config
from douyin_live_rec_king.models import (
    AppSettings,
    LiveTask,
    NicknameSource,
    StreamSource,
    VideoQuality,
)


def test_settings_ini_round_trip(tmp_path: Path) -> None:
    store = SettingsStore(tmp_path / "config.ini")
    settings = AppSettings(
        video_quality=VideoQuality.HD,
        stream_source=StreamSource.FLV,
        proxy_enabled=True,
        proxy_address="http://127.0.0.1:7890",
        douyin_cookie="token=abc%2Fdef; percent=100%",
    )
    store.save(settings)
    loaded = store.load()
    assert loaded.video_quality is VideoQuality.HD
    assert loaded.stream_source is StreamSource.FLV
    assert loaded.proxy == "http://127.0.0.1:7890"
    assert loaded.douyin_cookie == "token=abc%2Fdef; percent=100%"


def test_task_round_trip_and_nickname_policy(tmp_path: Path) -> None:
    store = TaskStore(tmp_path / "tasks.json")
    task = LiveTask(url="https://live.douyin.com/123")
    task.apply_platform_name("平台昵称")
    task.set_manual_name("我的别名")
    task.apply_platform_name("平台新昵称")
    store.save([task])
    loaded = store.load()[0]
    assert loaded.anchor_name == "我的别名"
    assert loaded.platform_anchor_name == "平台新昵称"
    assert loaded.nickname_source is NicknameSource.CUSTOM


def test_legacy_migration(tmp_path: Path) -> None:
    legacy = tmp_path / "config.json"
    legacy.write_text(
        json.dumps({
            "settings": {"default_format": "mp4", "check_interval_seconds": 12},
            "tasks": [{"anchor_name": "旧主播", "url": "mock://offline"}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    settings_store = SettingsStore(tmp_path / "config" / "config.ini")
    task_store = TaskStore(tmp_path / "data" / "tasks.json")
    assert migrate_legacy_config(legacy, settings_store, task_store)
    assert settings_store.load().default_format == "mp4"
    assert task_store.load()[0].display_name == "旧主播"
