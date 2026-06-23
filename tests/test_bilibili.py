import sys
from types import SimpleNamespace

from douyin_live_rec_king.models import AppSettings, PlatformType
from douyin_live_rec_king.platforms import (
    BilibiliExtractor,
    create_extractor,
    platform_metadata,
)


def test_bilibili_url_and_mock_request_fields() -> None:
    extractor = BilibiliExtractor(cookie="SESSDATA=secret")
    assert (
        extractor.normalize_url("https://live.bilibili.com/12345?spm_id_from=1")
        == "https://live.bilibili.com/12345"
    )
    offline = extractor.check_live_status("mock://offline")
    assert not offline.is_live
    live = extractor.check_live_status(
        "mock://live?url=https%3A%2F%2Fexample.test%2Flive.m3u8"
    )
    assert live.is_live
    assert live.cookie == "SESSDATA=secret"
    assert live.referer == "https://live.bilibili.com/1"
    assert live.headers["Origin"] == "https://live.bilibili.com"


def test_bilibili_streamget_adapter(monkeypatch) -> None:
    class FakeBilibili:
        def __init__(self, proxy_addr=None, cookies=None):
            assert proxy_addr == "http://127.0.0.1:7890"
            assert cookies == "cookie"

        async def fetch_web_stream_data(self, url):
            return {"url": url}

        async def fetch_stream_url(self, data, quality):
            return SimpleNamespace(
                is_live=True,
                title="Title",
                anchor_name="Anchor",
                record_url="https://example.test/live.flv",
                m3u8_url=None,
                flv_url="https://example.test/live.flv",
                live_url="https://live.bilibili.com/99",
                quality=quality,
            )

    monkeypatch.setitem(
        sys.modules,
        "streamget",
        SimpleNamespace(BilibiliLiveStream=FakeBilibili),
    )
    status = BilibiliExtractor(
        cookie="cookie", proxy="http://127.0.0.1:7890"
    ).check_live_status("https://live.bilibili.com/99?from=test")
    assert status.is_live
    assert status.stream_url.endswith(".flv")
    assert status.anchor_name == "Anchor"


def test_platform_registry_metadata_and_settings() -> None:
    settings = AppSettings(bilibili_cookie="bili-cookie")
    extractor = create_extractor(PlatformType.BILIBILI, settings)
    assert isinstance(extractor, BilibiliExtractor)
    assert extractor.cookie == "bili-cookie"
    metadata = platform_metadata(PlatformType.BILIBILI)
    assert metadata.display_name == "Bilibili"
    assert metadata.cookie_setting == "bilibili_cookie"
