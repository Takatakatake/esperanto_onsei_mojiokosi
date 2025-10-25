"""Configuration loading utilities for the transcription pipeline."""

from __future__ import annotations

import os
from enum import Enum
from functools import lru_cache
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError


class AudioInputConfig(BaseModel):
    """Audio capture configuration."""

    device_index: Optional[int] = Field(
        default=None,
        description="Input device index; None selects system default.",
    )
    sample_rate: int = Field(default=16_000, ge=8_000, le=96_000)
    channels: int = Field(default=1, ge=1, le=2)
    chunk_duration_seconds: float = Field(default=0.5, gt=0, le=5.0)
    blocksize: Optional[int] = Field(
        default=None,
        description="Optional low-level blocksize override for sounddevice.",
    )


class SpeechmaticsConfig(BaseModel):
    """Speechmatics realtime API configuration."""

    api_key: str = Field(..., min_length=10)
    app_id: str = Field(default="realtime", min_length=1)
    language: str = Field(default="eo", min_length=2)
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    enable_diarization: bool = True
    enable_punctuation: bool = True
    connection_url: str = Field(default="wss://eu2.rt.speechmatics.com/v2", min_length=10)
    jwt_token: Optional[str] = Field(default=None, description="Optional pre-issued JWT.")
    jwt_ttl_seconds: int = Field(default=3600, ge=60, le=24 * 3600)
    max_reconnect_attempts: int = Field(default=3, ge=0, le=10)
    reconnect_backoff_seconds: float = Field(default=3.0, ge=0.1, le=30.0)


class VoskConfig(BaseModel):
    """Configuration for the offline Vosk backend."""

    model_path: str = Field(..., min_length=1)
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    enable_partials: bool = True


class ZoomCaptionConfig(BaseModel):
    """Zoom closed-caption API configuration."""

    caption_post_url: Optional[str] = Field(
        default=None,
        description="Closed caption POST URL distributed by the Zoom host.",
    )
    enabled: bool = Field(default=True)
    min_post_interval_seconds: float = Field(default=1.0, ge=0.1, le=5.0)


class TranscriptLoggingConfig(BaseModel):
    """Controls transcript persistence."""

    enabled: bool = False
    file_path: Optional[str] = None
    include_timestamps: bool = True
    overwrite: bool = False


class WebUIConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8765
    open_browser: bool = False

class BackendChoice(str, Enum):
    """Supported transcription backends."""

    SPEECHMATICS = "speechmatics"
    VOSK = "vosk"
    WHISPER = "whisper"


class WhisperConfig(BaseModel):
    """Configuration for the Whisper streaming backend."""

    model_size: str = Field(default="medium", min_length=1)
    device: str = Field(default="auto")
    compute_type: str = Field(default="default")
    language: str = Field(default="eo")
    segment_duration: float = Field(default=6.0, ge=1.0, le=30.0)
    beam_size: int = Field(default=1, ge=1, le=5)
    vad_filter: bool = Field(default=True)


class Settings(BaseModel):
    """Aggregated settings for the transcription pipeline."""

    backend: BackendChoice = BackendChoice.SPEECHMATICS
    audio: AudioInputConfig = AudioInputConfig()
    speechmatics: Optional[SpeechmaticsConfig] = None
    vosk: Optional[VoskConfig] = None
    whisper: Optional[WhisperConfig] = None
    zoom: ZoomCaptionConfig = ZoomCaptionConfig()
    logging: TranscriptLoggingConfig = TranscriptLoggingConfig()
    web: WebUIConfig = WebUIConfig()


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load settings from environment variables and .env files."""

    load_dotenv()

    env = os.environ
    try:
        backend = BackendChoice(env.get("TRANSCRIPTION_BACKEND", "speechmatics").lower())

        speechmatics_cfg: Optional[SpeechmaticsConfig] = None
        if "SPEECHMATICS_API_KEY" in env or "SPEECHMATICS_JWT" in env:
            speechmatics_cfg = SpeechmaticsConfig(
                api_key=env.get("SPEECHMATICS_API_KEY", env.get("SPEECHMATICS_JWT", "")),
                app_id=env.get("SPEECHMATICS_APP_ID", "realtime"),
                language=env.get("SPEECHMATICS_LANGUAGE", "eo"),
                sample_rate=int(env.get("SPEECHMATICS_SAMPLE_RATE", "16000")),
                enable_diarization=env.get("SPEECHMATICS_ENABLE_DIARIZATION", "true").lower()
                in {"1", "true", "yes"},
                enable_punctuation=env.get("SPEECHMATICS_ENABLE_PUNCTUATION", "true").lower()
                in {"1", "true", "yes"},
                connection_url=env.get(
                    "SPEECHMATICS_CONNECTION_URL", "wss://eu2.rt.speechmatics.com/v2"
                ),
                jwt_token=env.get("SPEECHMATICS_JWT"),
                jwt_ttl_seconds=int(env.get("SPEECHMATICS_JWT_TTL", "3600")),
            )

        if backend is BackendChoice.SPEECHMATICS and speechmatics_cfg is None:
            raise RuntimeError("Speechmatics backend selected but SPEECHMATICS_API_KEY/SPEECHMATICS_JWT not set.")

        vosk_cfg: Optional[VoskConfig] = None
        if "VOSK_MODEL_PATH" in env:
            vosk_cfg = VoskConfig(
                model_path=env["VOSK_MODEL_PATH"],
                sample_rate=int(env.get("VOSK_SAMPLE_RATE", env.get("AUDIO_SAMPLE_RATE", "16000"))),
                enable_partials=env.get("VOSK_ENABLE_PARTIALS", "true").lower() in {"1", "true", "yes"},
            )

        if backend is BackendChoice.VOSK and vosk_cfg is None:
            raise RuntimeError("Vosk backend selected but VOSK_MODEL_PATH not configured.")

        whisper_cfg: Optional[WhisperConfig] = None
        if "WHISPER_MODEL_SIZE" in env or backend is BackendChoice.WHISPER:
            whisper_cfg = WhisperConfig(
                model_size=env.get("WHISPER_MODEL_SIZE", "medium"),
                device=env.get("WHISPER_DEVICE", "auto"),
                compute_type=env.get("WHISPER_COMPUTE_TYPE", "default"),
                language=env.get("WHISPER_LANGUAGE", env.get("SPEECHMATICS_LANGUAGE", "eo")),
                segment_duration=float(env.get("WHISPER_SEGMENT_DURATION", "6.0")),
                beam_size=int(env.get("WHISPER_BEAM_SIZE", "1")),
                vad_filter=env.get("WHISPER_VAD_FILTER", "true").lower() in {"1", "true", "yes"},
            )

        if backend is BackendChoice.WHISPER and whisper_cfg is None:
            whisper_cfg = WhisperConfig()

        logging_cfg = TranscriptLoggingConfig(
            enabled=env.get("TRANSCRIPT_LOG_ENABLED", "false").lower() in {"1", "true", "yes"}
            or bool(env.get("TRANSCRIPT_LOG_PATH")),
            file_path=env.get("TRANSCRIPT_LOG_PATH"),
            include_timestamps=env.get("TRANSCRIPT_LOG_WITH_TIMESTAMPS", "true").lower()
            in {"1", "true", "yes"},
            overwrite=env.get("TRANSCRIPT_LOG_OVERWRITE", "false").lower() in {"1", "true", "yes"},
        )

        settings = Settings(
            backend=backend,
            speechmatics=speechmatics_cfg,
            vosk=vosk_cfg,
            whisper=whisper_cfg,
            audio=AudioInputConfig(
                device_index=(
                    int(env["AUDIO_DEVICE_INDEX"])
                    if "AUDIO_DEVICE_INDEX" in env
                    else None
                ),
                sample_rate=int(env.get("AUDIO_SAMPLE_RATE", "16000")),
                channels=int(env.get("AUDIO_CHANNELS", "1")),
                chunk_duration_seconds=float(env.get("AUDIO_CHUNK_DURATION_SECONDS", "0.5")),
                blocksize=(
                    int(env["AUDIO_BLOCKSIZE"])
                    if "AUDIO_BLOCKSIZE" in env
                    else None
                ),
            ),
            zoom=ZoomCaptionConfig(
                caption_post_url=env.get("ZOOM_CC_POST_URL"),
                enabled=env.get("ZOOM_CC_ENABLED", "true").lower() in {"1", "true", "yes"},
                min_post_interval_seconds=float(
                    env.get("ZOOM_CC_MIN_POST_INTERVAL_SECONDS", "1.0")
                ),
            ),
            logging=logging_cfg,
            web=WebUIConfig(
                enabled=env.get("WEB_UI_ENABLED", "false").lower() in {"1","true","yes"},
                host=env.get("WEB_UI_HOST", "127.0.0.1"),
                port=int(env.get("WEB_UI_PORT", "8765")),
                open_browser=env.get("WEB_UI_OPEN_BROWSER", "false").lower() in {"1","true","yes"},
            ),
        )
        return settings
    except KeyError as exc:
        missing = exc.args[0]
        raise RuntimeError(f"Missing required environment variable: {missing}") from exc
    except ValidationError as exc:
        raise RuntimeError(f"Configuration invalid: {exc}") from exc
