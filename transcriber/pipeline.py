"""High-level orchestration of realtime transcription pipeline."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .asr import (
    SpeechmaticsRealtimeBackend,
    SpeechmaticsRealtimeError,
    StreamingTranscriptionBackend,
    TranscriptSegment,
    VoskBackendError,
    VoskStreamingBackend,
    WhisperBackendError,
    WhisperStreamingBackend,
)
from .audio import AudioCaptureError, AudioChunkStream
from .config import BackendChoice, Settings, load_settings
from .zoom_caption import ZoomCaptionPublisher
from .display.webui import CaptionWebUI
import webbrowser
import functools


@dataclass
class PipelineState:
    """Tracks transcription state for downstream consumers."""

    final_transcripts: List[str] = field(default_factory=list)
    latest_partial: Optional[str] = None

    def add_result(self, transcript: TranscriptSegment) -> Optional[str]:
        if transcript.is_final:
            if transcript.text:
                self.final_transcripts.append(transcript.text)
                self.latest_partial = None
                return transcript.text
            return None

        self.latest_partial = transcript.text
        return None


class TranscriptFileLogger:
    """Handles optional transcript persistence."""

    def __init__(self, settings, override_path: Optional[str] = None) -> None:
        self._settings = settings
        self._override_path = override_path
        self._file = None

    @property
    def _resolved_path(self) -> Optional[Path]:
        if self._override_path:
            return Path(self._override_path).expanduser()
        if self._settings.file_path:
            return Path(self._settings.file_path).expanduser()
        return None

    def __enter__(self) -> "TranscriptFileLogger":
        path = self._resolved_path
        should_enable = self._settings.enabled or path is not None
        if not should_enable or path is None:
            return self

        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "w" if self._settings.overwrite else "a"
        self._file = path.open(mode=mode, encoding="utf-8")
        logging.info("Transcript logging to %s (mode=%s)", path, mode)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # noqa: ANN001
        if self._file:
            self._file.close()
            self._file = None

    def log_final(self, segment: TranscriptSegment) -> None:
        if not self._file or not segment.text:
            return

        line = segment.text
        if self._settings.include_timestamps:
            timestamp = datetime.now().isoformat(timespec="seconds")
            line = f"[{timestamp}] {segment.text}"
        self._file.write(line + "\n")
        self._file.flush()


class TranscriptionPipeline:
    """Coordinate audio capture, streaming transcription, and Zoom publishing."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        backend_override: Optional[str] = None,
        transcript_log_override: Optional[str] = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.backend_choice = (
            BackendChoice(backend_override.lower())
            if backend_override
            else self.settings.backend
        )
        self._audio_stream = AudioChunkStream(self.settings.audio)
        self._zoom_publisher = ZoomCaptionPublisher(self.settings.zoom)
        self._transcript_logger = TranscriptFileLogger(
            self.settings.logging, override_path=transcript_log_override
        )
        self._web_ui: Optional[CaptionWebUI] = None
        self.state = PipelineState()
        self._running = False

    async def run(self) -> None:
        """Run the pipeline until cancelled."""

        if self._running:
            raise RuntimeError("Pipeline already running.")
        self._running = True
        logging.info("Starting transcription pipeline with backend=%s.", self.backend_choice.value)

        backend = self._create_backend()
        try:
            with self._transcript_logger:
                async with self._zoom_publisher:
                    if self.settings.web.enabled:
                        self._web_ui = CaptionWebUI(
                            host=self.settings.web.host,
                            port=self.settings.web.port,
                        )
                        await self._web_ui.start()
                        if self.settings.web.open_browser:
                            url = f"http://{self.settings.web.host}:{self.settings.web.port}"
                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(None, functools.partial(webbrowser.open, url))
                    async with self._audio_stream.connect() as audio_stream:
                        async with backend:
                            await self._main_loop(audio_stream, backend)
        except (
            AudioCaptureError,
            SpeechmaticsRealtimeError,
            VoskBackendError,
            WhisperBackendError,
        ) as exc:
            logging.error("Pipeline stopped due to error: %s", exc)
            raise
        finally:
            if self._web_ui:
                await self._web_ui.stop()
                self._web_ui = None
            self._running = False
            logging.info("Transcription pipeline stopped.")

    async def _main_loop(
        self, audio_stream: AudioChunkStream, backend: StreamingTranscriptionBackend
    ) -> None:
        audio_task = asyncio.create_task(
            self._pump_audio(audio_stream, backend), name="audio-producer"
        )
        transcript_task = asyncio.create_task(
            self._consume_transcripts(backend), name="transcript-consumer"
        )

        done, pending = await asyncio.wait(
            {audio_task, transcript_task},
            return_when=asyncio.FIRST_EXCEPTION,
        )
        for task in pending:
            task.cancel()
        for task in done:
            task.result()

    def _create_backend(self) -> StreamingTranscriptionBackend:
        if self.backend_choice is BackendChoice.SPEECHMATICS:
            if not self.settings.speechmatics:
                raise RuntimeError("Speechmatics configuration missing.")
            return SpeechmaticsRealtimeBackend(self.settings.speechmatics)

        if self.backend_choice is BackendChoice.VOSK:
            if not self.settings.vosk:
                raise RuntimeError("Vosk configuration missing.")
            return VoskStreamingBackend(self.settings.vosk)

        if self.backend_choice is BackendChoice.WHISPER:
            if not self.settings.whisper:
                raise RuntimeError("Whisper configuration missing.")
            return WhisperStreamingBackend(
                self.settings.whisper, self.settings.audio.sample_rate
            )

        raise RuntimeError(f"Unsupported backend: {self.backend_choice}")

    async def _pump_audio(
        self, audio_stream: AudioChunkStream, backend: StreamingTranscriptionBackend
    ) -> None:
        async for chunk in audio_stream:
            await backend.send_audio_chunk(chunk)

    async def _consume_transcripts(self, backend: StreamingTranscriptionBackend) -> None:
        async for result in backend.transcript_results():
            if result.is_final:
                logging.info("Final: %s", result.text)
                self._transcript_logger.log_final(result)
                if self._web_ui:
                    await self._web_ui.broadcast({
                        "type": "final",
                        "text": result.text,
                        "speaker": result.speaker,
                    })
            else:
                if result.text:
                    logging.debug("Partial: %s", result.text)
                    if self._web_ui:
                        await self._web_ui.broadcast({
                            "type": "partial",
                            "text": result.text,
                            "speaker": result.speaker,
                        })

            zoom_payload = self.state.add_result(result)
            if zoom_payload:
                await self._zoom_publisher.post_caption(zoom_payload)

    async def shutdown(self) -> None:
        """Cancel any running tasks (best-effort)."""

        await self._zoom_publisher.close()
