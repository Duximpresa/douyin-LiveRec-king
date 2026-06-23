from pathlib import Path

import pytest

import douyin_live_rec_king.recording.ffmpeg as ffmpeg_module
from douyin_live_rec_king.recording.ffmpeg import FFmpegTool


def test_local_ffmpeg_has_highest_priority(tmp_path: Path, monkeypatch) -> None:
    local = tmp_path / "runtime" / "ffmpeg" / "bin" / "ffmpeg.exe"
    local.parent.mkdir(parents=True)
    local.write_bytes(b"fake")
    monkeypatch.setattr(ffmpeg_module, "project_root", lambda: tmp_path)
    monkeypatch.setattr(ffmpeg_module.shutil, "which", lambda _name: "C:/system/ffmpeg.exe")
    assert FFmpegTool("Z:/missing/ffmpeg.exe").resolved_executable() == str(local)


def test_segment_command_contains_required_flags(tmp_path: Path, monkeypatch) -> None:
    tool = FFmpegTool()
    monkeypatch.setattr(tool, "resolved_executable", lambda: "ffmpeg")
    command = tool.recording_command(
        "https://example.test/live.m3u8",
        tmp_path / "video_%03d.ts",
        proxy="http://127.0.0.1:7890",
        segmented=True,
        segment_seconds=600,
    )
    assert "-http_proxy" in command
    assert ["-f", "segment"] == command[command.index("-f"):command.index("-f") + 2]
    assert command[-1].endswith("video_%03d.ts")


def test_recording_command_headers_reconnect_and_segment_pattern(
    tmp_path: Path, monkeypatch
) -> None:
    tool = FFmpegTool()
    monkeypatch.setattr(tool, "resolved_executable", lambda: "ffmpeg")
    command = tool.recording_command(
        "https://example.test/live.m3u8",
        tmp_path / "video.ts",
        headers={"Origin": "https://example.test", "Cookie": "old=1"},
        user_agent="Test Agent",
        referer="https://example.test/live",
        cookie="new=2",
        segmented=True,
    )
    assert isinstance(command, list)
    assert "-reconnect" in command
    assert command[command.index("-user_agent") + 1] == "Test Agent"
    header_block = command[command.index("-headers") + 1]
    assert "Origin: https://example.test\r\n" in header_block
    assert "Referer: https://example.test/live\r\n" in header_block
    assert "Cookie: new=2\r\n" in header_block
    assert "old=1" not in header_block
    assert header_block.endswith("\r\n")
    assert command[-1].endswith("video_%03d.ts")


def test_recording_command_can_disable_reconnect(tmp_path: Path, monkeypatch) -> None:
    tool = FFmpegTool()
    monkeypatch.setattr(tool, "resolved_executable", lambda: "ffmpeg")
    command = tool.recording_command(
        "https://example.test/live.flv", tmp_path / "video.flv", reconnect=False
    )
    assert "-reconnect" not in command


def test_convert_rejects_empty_source(tmp_path: Path) -> None:
    source = tmp_path / "empty.ts"
    source.write_bytes(b"")
    with pytest.raises(ValueError):
        FFmpegTool().convert_to_mp4(source, delete_original=True)


def test_convert_only_deletes_source_after_valid_target(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "video.ts"
    source.write_bytes(b"source")
    tool = FFmpegTool()
    monkeypatch.setattr(tool, "resolved_executable", lambda: "ffmpeg")

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"target")

    monkeypatch.setattr(ffmpeg_module.subprocess, "run", fake_run)
    target = tool.convert_to_mp4(source, delete_original=True)
    assert target.exists()
    assert not source.exists()
