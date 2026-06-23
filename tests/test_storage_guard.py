from pathlib import Path

import douyin_live_rec_king.services.storage_guard as storage_module
from douyin_live_rec_king.services.storage_guard import StorageGuard


def test_storage_guard_creates_directory_and_accepts_zero_threshold(tmp_path: Path) -> None:
    target = tmp_path / "recordings"
    result = StorageGuard().check(target, 0)
    assert result.ok
    assert target.is_dir()
    assert result.free_gb is not None


def test_storage_guard_reports_low_space(tmp_path: Path, monkeypatch) -> None:
    class Usage:
        free = 512 * 1024 * 1024

    monkeypatch.setattr(storage_module.shutil, "disk_usage", lambda _path: Usage())
    result = StorageGuard().check(tmp_path, 1.0)
    assert not result.ok
    assert "低于阈值" in (result.error or "")


def test_storage_guard_reports_unusable_path(tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x", encoding="utf-8")
    result = StorageGuard().check(target, 1)
    assert not result.ok
    assert "无法使用录制目录" in (result.error or "")
