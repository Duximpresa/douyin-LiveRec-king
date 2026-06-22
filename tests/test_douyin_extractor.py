import asyncio
import sys
import types

from douyin_live_rec_king.models import StreamSource, VideoQuality
from douyin_live_rec_king.platforms.douyin import DouyinExtractor


class FakeStreamData:
    is_live = True
    title = "测试直播"
    anchor_name = "自动主播"
    m3u8_url = "https://example.test/live.m3u8"
    flv_url = "https://example.test/live.flv"
    record_url = m3u8_url
    live_url = "https://live.douyin.com/123"
    quality = "HD"


class FakeDouyinLiveStream:
    calls: list[str] = []

    def __init__(self, **_kwargs):
        pass

    async def fetch_web_stream_data(self, _url):
        self.calls.append("web")
        return {"status": 2}

    async def fetch_app_stream_data(self, _url):
        self.calls.append("app")
        return {"status": 2}

    async def fetch_stream_url(self, _data, _quality):
        return FakeStreamData()


def install_fake_streamget(monkeypatch) -> None:
    module = types.ModuleType("streamget")
    module.DouyinLiveStream = FakeDouyinLiveStream
    monkeypatch.setitem(sys.modules, "streamget", module)
    FakeDouyinLiveStream.calls.clear()


def test_live_room_uses_web_route(monkeypatch) -> None:
    install_fake_streamget(monkeypatch)
    status = DouyinExtractor(quality=VideoQuality.HD).check_live_status(
        "https://live.douyin.com/123"
    )
    assert FakeDouyinLiveStream.calls == ["web"]
    assert status.anchor_name == "自动主播"
    assert status.stream_url.endswith(".m3u8")


def test_profile_and_short_link_use_app_route(monkeypatch) -> None:
    install_fake_streamget(monkeypatch)
    extractor = DouyinExtractor(stream_source=StreamSource.FLV)
    profile = extractor.check_live_status("https://www.douyin.com/user/abc")
    short = extractor.check_live_status("https://v.douyin.com/abcd/")
    assert FakeDouyinLiveStream.calls == ["app", "app"]
    assert profile.stream_url.endswith(".flv")
    assert short.canonical_url == "https://live.douyin.com/123"


def test_mock_and_invalid_url() -> None:
    assert not DouyinExtractor().check_live_status("mock://offline").is_live
    status = DouyinExtractor().check_live_status("https://example.com/room")
    assert status.error and "douyin.com" in status.error

