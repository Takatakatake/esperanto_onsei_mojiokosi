"""Zoom closed-caption publishing utilities."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import aiohttp

from .config import ZoomCaptionConfig


class ZoomCaptionPublisher:
    """Push transcript updates to Zoom using the Closed Caption API."""

    def __init__(self, config: ZoomCaptionConfig) -> None:
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._sequence = 0
        self._last_post_monotonic = 0.0

    async def __aenter__(self) -> "ZoomCaptionPublisher":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        await self.close()

    async def start(self) -> None:
        if not self.config.enabled:
            logging.info("Zoom caption publishing disabled by configuration.")
            return
        if not self.config.caption_post_url:
            logging.warning("Zoom caption URL not configured; captions will not be sent.")
            return
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def post_caption(self, text: str) -> None:
        """Post a caption update, respecting rate limits and sequence numbers."""

        if not self.config.enabled or not self.config.caption_post_url:
            return

        if not text.strip():
            logging.debug("Skipping empty caption payload.")
            return

        now = asyncio.get_running_loop().time()
        if now - self._last_post_monotonic < self.config.min_post_interval_seconds:
            logging.debug("Throttling caption update to honour minimum interval.")
            return

        if self._session is None:
            await self.start()
            if self._session is None:
                logging.error("Zoom caption session could not be initialised.")
                return

        url = self._build_url_with_sequence(self._sequence)
        self._sequence += 1
        payload = text.strip()

        try:
            async with self._session.post(
                url,
                data=payload.encode("utf-8"),
                headers={"Content-Type": "text/plain; charset=utf-8"},
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    logging.error(
                        "Zoom caption POST failed: status=%s body=%s", response.status, body
                    )
                else:
                    logging.debug("Caption posted to Zoom (seq=%s).", self._sequence - 1)
                    self._last_post_monotonic = now
        except Exception as exc:  # pylint: disable=broad-except
            logging.exception("Failed to post caption to Zoom: %s", exc)

    def _build_url_with_sequence(self, sequence: int) -> str:
        base_url = str(self.config.caption_post_url)
        parsed = urlparse(base_url)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query["seq"] = [str(sequence)]
        new_query = urlencode(query, doseq=True)
        updated = parsed._replace(query=new_query)
        return urlunparse(updated)
