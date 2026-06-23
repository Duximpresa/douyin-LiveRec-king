from pathlib import Path

from douyin_live_rec_king.services.file_integrity import FileIntegrityGuard


def test_missing_zero_small_and_normal_files(tmp_path: Path) -> None:
    guard = FileIntegrityGuard()
    assert not guard.inspect(tmp_path / "missing.ts").ok

    zero = tmp_path / "zero.ts"
    zero.write_bytes(b"")
    assert not guard.inspect(zero).ok

    small = tmp_path / "small.ts"
    small.write_bytes(b"x" * 1024)
    result = guard.inspect(small)
    assert result.ok
    assert result.warnings

    normal = tmp_path / "normal.ts"
    normal.write_bytes(b"x" * (256 * 1024))
    result = guard.inspect(normal)
    assert result.ok
    assert not result.warnings


def test_segment_expansion_and_temporary_scan(tmp_path: Path) -> None:
    guard = FileIntegrityGuard()
    (tmp_path / "video_000.ts").write_bytes(b"x" * 300_000)
    (tmp_path / "video_001.ts").write_bytes(b"x" * 300_000)
    result = guard.inspect(tmp_path / "video_%03d.ts")
    assert result.ok
    assert len(result.files) == 2
    (tmp_path / "unfinished.part").write_bytes(b"x")
    (tmp_path / "state.tmp").write_bytes(b"x")
    assert len(guard.scan_temporary(tmp_path)) == 2
