from pathlib import Path

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
