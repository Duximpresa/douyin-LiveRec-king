"""Douyin live-room adapter backed by the maintained streamget library."""

from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse

import requests

from ..models import LiveStatus, StreamSource, VideoQuality
from .base import BasePlatformExtractor


class DouyinExtractor(BasePlatformExtractor):
    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124 Safari/537.36"
    )
    def __init__(
        self,
        timeout: float = 15.0,
        cookie: str = "",
        proxy: str | None = None,
        quality: VideoQuality = VideoQuality.OD,
        stream_source: StreamSource = StreamSource.HLS,
    ) -> None:
        self.timeout = timeout
        self.cookie = cookie.strip()
        self.proxy = proxy
        self.quality = quality
        self.stream_source = stream_source

    def _request_fields(self, canonical_url: str | None) -> dict[str, object]:
        return {
            "headers": {},
            "user_agent": self.USER_AGENT,
            "referer": canonical_url or "https://live.douyin.com/",
            "cookie": self.cookie or None,
        }

    def normalize_url(self, url: str) -> str:
        value = url.strip()
        if value.startswith(("mock://", "stream://")):
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("请输入抖音直播间、作者主页或分享短链")
        if not any(host in parsed.netloc.lower() for host in ("douyin.com", "iesdouyin.com")):
            raise ValueError("当前仅支持 douyin.com 或 iesdouyin.com 地址")
        path_parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.netloc.lower() in {"douyin.com", "www.douyin.com"}
            and len(path_parts) == 3
            and path_parts[:2] == ["follow", "live"]
            and path_parts[2].isdigit()
        ):
            return f"https://live.douyin.com/{path_parts[2]}"
        return value

    @staticmethod
    def _is_web_room(url: str) -> bool:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        return parsed.netloc.lower() == "live.douyin.com" and bool(path) and "/" not in path

    async def _fetch(self, url: str) -> LiveStatus:
        try:
            from streamget import DouyinLiveStream
        except ImportError as exc:
            return LiveStatus(False, error="缺少 streamget 4.0.10，请重新安装依赖", parser_error=str(exc))

        live = DouyinLiveStream(proxy_addr=self.proxy, cookies=self.cookie or None)
        try:
            if self._is_web_room(url):
                raw_data = await live.fetch_web_stream_data(url)
            else:
                raw_data = await live.fetch_app_stream_data(url)
            stream = await live.fetch_stream_url(raw_data, self.quality.value)
            hls = getattr(stream, "m3u8_url", None)
            flv = getattr(stream, "flv_url", None)
            selected = hls if self.stream_source is StreamSource.HLS else flv
            selected = selected or getattr(stream, "record_url", None) or hls or flv
            canonical = getattr(stream, "live_url", None)
            return LiveStatus(
                is_live=bool(getattr(stream, "is_live", False)),
                title=getattr(stream, "title", None),
                anchor_name=getattr(stream, "anchor_name", None),
                stream_url=selected,
                hls_url=hls,
                flv_url=flv,
                canonical_url=canonical,
                quality=getattr(stream, "quality", None) or self.quality.value,
                raw=raw_data if isinstance(raw_data, dict) else {},
                **self._request_fields(canonical),
            )
        except Exception as exc:
            message = str(exc)
            lower = message.lower()
            if "node" in lower or "execjs" in lower:
                message = "解析需要 Node.js，请在“设置 → FFmpeg 与环境”检查 Node.js"
            elif "socksio" in lower or "socks proxy" in lower:
                message = "当前网络使用 SOCKS 代理但缺少 socksio，请重新安装完整依赖"
            elif "risk" in lower or "风控" in message or "cookie" in lower:
                message = "抖音触发风控，请检查网络、代理或在 Cookie 页填写有效 Cookie"
            elif "expecting value" in lower or "json" in lower:
                message = "抖音返回了异常页面，可能触发风控或地址已失效；请检查 Cookie、代理和链接"
            return LiveStatus(False, error=message, parser_error=str(exc), raw={})

    def check_live_status(self, url: str) -> LiveStatus:
        try:
            normalized = self.normalize_url(url)
            if normalized == "mock://offline":
                return LiveStatus(False, anchor_name="Mock Anchor", raw={"mode": "mock"})
            if normalized.startswith("mock://live"):
                query = parse_qs(urlparse(normalized).query)
                stream_url = query.get("url", [None])[0]
                return LiveStatus(
                    bool(stream_url),
                    title="Mock live stream",
                    anchor_name="Mock Anchor",
                    stream_url=stream_url,
                    hls_url=stream_url,
                    canonical_url=normalized,
                    quality=self.quality.value,
                    raw={"mode": "mock"},
                    error=None if stream_url else "mock://live 需要 ?url= 测试流地址",
                    **self._request_fields(normalized),
                )
            if normalized.startswith("stream://"):
                stream_url = normalized.removeprefix("stream://")
                return LiveStatus(
                    True,
                    title="Direct test stream",
                    anchor_name="Direct Stream",
                    stream_url=stream_url,
                    hls_url=stream_url,
                    canonical_url=normalized,
                    quality=self.quality.value,
                    raw={"mode": "direct"},
                    **self._request_fields(normalized),
                )
            return asyncio.run(self._fetch(normalized))
        except (ValueError, requests.RequestException) as exc:
            return LiveStatus(False, error=str(exc), parser_error=str(exc), raw={})

    def get_stream_url(self, url: str) -> str | None:
        return self.check_live_status(url).stream_url
