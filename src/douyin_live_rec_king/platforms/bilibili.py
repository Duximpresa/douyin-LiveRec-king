"""Bilibili live-room adapter backed by streamget."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

from ..models import LiveStatus, VideoQuality
from .base import BasePlatformExtractor


class BilibiliExtractor(BasePlatformExtractor):
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )

    def __init__(
        self,
        cookie: str = "",
        proxy: str | None = None,
        quality: VideoQuality = VideoQuality.OD,
    ) -> None:
        self.cookie = cookie.strip()
        self.proxy = proxy
        self.quality = quality

    def normalize_url(self, url: str) -> str:
        value = url.strip()
        if value.startswith(("mock://", "stream://")):
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("请输入 Bilibili 直播间地址")
        if parsed.netloc.lower() not in {"live.bilibili.com", "www.live.bilibili.com"}:
            raise ValueError("当前仅支持 live.bilibili.com 直播间地址")
        room_id = parsed.path.strip("/").split("/", 1)[0]
        if not room_id.isdigit():
            raise ValueError("Bilibili 直播间地址缺少有效 room_id")
        return f"https://live.bilibili.com/{room_id}"

    def _request_fields(self, canonical_url: str) -> dict[str, object]:
        return {
            "headers": {
                "Origin": "https://live.bilibili.com",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
            "user_agent": self.USER_AGENT,
            "referer": canonical_url,
            "cookie": self.cookie or None,
        }

    async def _fetch(self, url: str) -> LiveStatus:
        try:
            from streamget import BilibiliLiveStream
        except ImportError as exc:
            return LiveStatus(
                False,
                error="缺少 streamget 4.0.10，请重新安装依赖",
                parser_error=str(exc),
            )
        live = BilibiliLiveStream(
            proxy_addr=self.proxy, cookies=self.cookie or None
        )
        try:
            raw_data = await live.fetch_web_stream_data(url)
            stream = await live.fetch_stream_url(raw_data, self.quality.value)
            stream_url = (
                getattr(stream, "record_url", None)
                or getattr(stream, "m3u8_url", None)
                or getattr(stream, "flv_url", None)
            )
            fields = self._request_fields(url)
            return LiveStatus(
                is_live=bool(getattr(stream, "is_live", False)),
                title=getattr(stream, "title", None),
                anchor_name=getattr(stream, "anchor_name", None),
                stream_url=stream_url,
                hls_url=getattr(stream, "m3u8_url", None),
                flv_url=getattr(stream, "flv_url", None),
                canonical_url=getattr(stream, "live_url", None) or url,
                quality=getattr(stream, "quality", None) or self.quality.value,
                raw=raw_data if isinstance(raw_data, dict) else {},
                **fields,
            )
        except Exception as exc:
            message = str(exc)
            lower = message.lower()
            if "cookie" in lower or "403" in lower or "forbidden" in lower:
                message = "Bilibili 访问受限，请检查 Cookie、代理或直播间地址"
            return LiveStatus(False, error=message, parser_error=str(exc))

    def check_live_status(self, url: str) -> LiveStatus:
        try:
            normalized = self.normalize_url(url)
            if normalized == "mock://offline":
                return LiveStatus(
                    False, anchor_name="Mock Bilibili", raw={"mode": "mock"}
                )
            if normalized.startswith("mock://live"):
                query = parse_qs(urlparse(normalized).query)
                stream_url = query.get("url", [None])[0]
                canonical = "https://live.bilibili.com/1"
                return LiveStatus(
                    bool(stream_url),
                    title="Mock Bilibili live",
                    anchor_name="Mock Bilibili",
                    stream_url=stream_url,
                    hls_url=stream_url,
                    canonical_url=canonical,
                    quality=self.quality.value,
                    raw={"mode": "mock"},
                    error=None if stream_url else "mock://live 需要 ?url= 测试流地址",
                    **self._request_fields(canonical),
                )
            if normalized.startswith("stream://"):
                stream_url = normalized.removeprefix("stream://")
                canonical = "https://live.bilibili.com/1"
                return LiveStatus(
                    True,
                    title="Direct Bilibili test stream",
                    anchor_name="Direct Bilibili Stream",
                    stream_url=stream_url,
                    hls_url=stream_url,
                    canonical_url=canonical,
                    quality=self.quality.value,
                    raw={"mode": "direct"},
                    **self._request_fields(canonical),
                )
            return asyncio.run(self._fetch(normalized))
        except ValueError as exc:
            return LiveStatus(False, error=str(exc), parser_error=str(exc))

    def get_stream_url(self, url: str) -> str | None:
        return self.check_live_status(url).stream_url
