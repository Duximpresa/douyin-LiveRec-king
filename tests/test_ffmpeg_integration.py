import shutil
import subprocess
from pathlib import Path

import pytest

from douyin_live_rec_king.services.media_probe import MediaProbeService


pytestmark = pytest.mark.ffmpeg_integration


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="FFmpeg/ffprobe not installed",
)
def test_real_ffmpeg_probe_and_ts_remux(tmp_path: Path) -> None:
    source = tmp_path / "sample.ts"
    subprocess.run(
        [
            shutil.which("ffmpeg"),
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=44100",
            "-t",
            "1",
            "-c:v",
            "mpeg2video",
            "-c:a",
            "mp2",
            "-f",
            "mpegts",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    service = MediaProbeService()
    before = service.probe(source)
    assert before.valid
    assert before.duration_seconds and before.duration_seconds > 0
    target = service.remux(source)
    after = service.probe(target)
    assert target.exists() and source.exists()
    assert after.valid
    assert "mp4" in (after.format_name or "")
