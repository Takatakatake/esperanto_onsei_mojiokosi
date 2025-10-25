"""Audio capture utilities."""

from __future__ import annotations

import asyncio
import logging
import queue
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

import sounddevice as sd

from .config import AudioInputConfig


class AudioCaptureError(Exception):
    """Raised when the audio subsystem cannot be initialised."""


class AudioChunkStream:
    """Async iterator producing raw PCM audio chunks."""

    def __init__(self, config: AudioInputConfig) -> None:
        self.config = config
        self._queue: "queue.Queue[bytes]" = queue.Queue(maxsize=10)
        self._stream: Optional[sd.RawInputStream] = None
        self._stopped = asyncio.Event()

    def _callback(self, indata: bytes, frames: int, _time, status: sd.CallbackFlags) -> None:
        if status:
            logging.warning("Audio stream status: %s", status)
        try:
            self._queue.put_nowait(bytes(indata))
        except queue.Full:
            # Drop oldest chunk to prevent runaway latency.
            try:
                _ = self._queue.get_nowait()
                self._queue.put_nowait(bytes(indata))
                logging.debug("Dropped one audio chunk to keep up with realtime processing.")
            except queue.Empty:
                logging.debug("Audio buffer overflow handled, but queue empty when trimming.")

    @asynccontextmanager
    async def connect(self) -> AsyncGenerator["AudioChunkStream", None]:
        """Context manager that starts and stops the underlying audio stream."""

        frames_per_chunk = int(self.config.sample_rate * self.config.chunk_duration_seconds)
        if frames_per_chunk <= 0:
            raise AudioCaptureError("Chunk duration and sample rate produce zero frames.")

        try:
            self._stream = sd.RawInputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype="int16",
                callback=self._callback,
                blocksize=frames_per_chunk if self.config.blocksize is None else self.config.blocksize,
                device=self.config.device_index,
            )
            self._stream.start()
        except Exception as exc:  # pylint: disable=broad-except
            raise AudioCaptureError(f"Failed to initialise audio input: {exc}") from exc

        try:
            yield self
        finally:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
            self._stopped.set()

    async def __anext__(self) -> bytes:
        return await self.next_chunk()

    def __aiter__(self) -> "AudioChunkStream":
        return self

    async def next_chunk(self) -> bytes:
        """Await the next audio chunk."""

        loop = asyncio.get_running_loop()
        if self._stopped.is_set():
            raise StopAsyncIteration
        try:
            return await loop.run_in_executor(None, self._queue.get)
        except Exception as exc:  # pylint: disable=broad-except
            raise AudioCaptureError(f"Failed to read audio chunk: {exc}") from exc
