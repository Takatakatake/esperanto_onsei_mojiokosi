# Esperanto Realtime Transcription

Realtime transcription pipeline tailored for Esperanto conversations on Zoom and Google Meet.  
The implementation follows the design principles captured in *エスペラント（Esperanto）会話を“常時・高精度・低遅延”に文字起こしするための実現案1.md*:

- Speechmatics Realtime STT (official `eo` support, talker diarization, custom dictionary hooks)
- Vosk offline backend as a zero-cost / air-gapped fallback
- Zoom Closed Caption API injection for native on-screen subtitles
- Pipeline abstraction ready for additional engines (e.g., Whisper streaming, Google STT)

> ⚠️ Speechmatics and Zoom endpoints require valid credentials and meeting-level permissions.  
> Keep participants informed about live transcription to comply with privacy & platform policies.

---

## 1. Prerequisites

- Python 3.10+ (tested with CPython 3.10/3.11)
- `virtualenv` or `uv` for dependency isolation
- Audio route from Zoom/Meet into the local machine (e.g. VB-Audio, VoiceMeeter, BlackHole, JACK)
- Speechmatics account with realtime entitlement and API key (when using the cloud backend)
- Zoom host privileges to obtain the Closed Caption POST URL (or use Recall.ai/Meeting SDK for media access)

Optional:

- GPU or high-performance CPU if you plan to run the Whisper backend (recommended: RTX 4070+ or Apple M2 Pro+)
- Google Meet Media API (developer preview) for direct audio capture when available
- Vosk Esperanto model (`vosk-model-small-eo-0.42` or later) if you plan to run fully offline

---

## 2. Bootstrap

```bash
cd /media/yamada/SSD-PUTA1/CODEX作業用202510
python -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`:

```ini
TRANSCRIPTION_BACKEND=speechmatics  # or vosk / whisper
SPEECHMATICS_API_KEY=sk_live_************************
SPEECHMATICS_APP_ID=realtime
SPEECHMATICS_LANGUAGE=eo
ZOOM_CC_POST_URL=https://wmcc.zoom.us/closedcaption?... (host-provided URL)
```

Optional overrides:

```ini
AUDIO_DEVICE_INDEX=8            # from --list-devices output
AUDIO_SAMPLE_RATE=16000
AUDIO_CHUNK_DURATION_SECONDS=0.5
ZOOM_CC_MIN_POST_INTERVAL_SECONDS=1.0
VOSK_MODEL_PATH=/absolute/path/to/vosk-model-small-eo-0.42
WHISPER_MODEL_SIZE=medium
WHISPER_DEVICE=auto              # e.g. cuda, cpu, mps
WHISPER_COMPUTE_TYPE=default     # e.g. float16 (for GPU)
WHISPER_SEGMENT_DURATION=6.0
WHISPER_BEAM_SIZE=1
TRANSCRIPT_LOG_PATH=logs/esperanto-caption.log
```

---

## 3. Usage

List capture devices and verify routing:

```bash
python -m transcriber.cli --list-devices
```

Start the pipeline (prints finals to stdout, pushes finals to Zoom):

```bash
python -m transcriber.cli --log-level=INFO
```

Switch backends or override log output on demand:

```bash
python -m transcriber.cli --backend=vosk --log-file=logs/offline.log
python -m transcriber.cli --backend=whisper --log-level=DEBUG
```

Stopping with `Ctrl+C` sends a graceful shutdown signal. Logs show:

- `Final:` lines once Speechmatics emits confirmed segments
- Caption POST success/failure (watch for 401/403 → token expired or meeting not ready)
- When transcript logging is enabled, the log file receives timestamped lines for each confirmed utterance.

Zoom-specific steps (per the proposal):

1. Host joins the meeting, enables **Allow participants to request Live Transcription** and copies the Closed Caption API URL.
2. Paste the URL into `.env` or set `ZOOM_CC_POST_URL` at runtime (`export ZOOM_CC_POST_URL=...`).
3. Participants enable subtitles in the Zoom UI. Timing is ~1 s end-to-end in normal network conditions.

Google Meet options:

- **Meet Media API (preview)**: swap the audio frontend to consume the REST/WS media stream, then feed PCM into the same Speechmatics client.
- **Screen overlay**: run this pipeline locally, render the transcript in a floating window (future work) and share it via Meet Companion mode.

---

## 4. Architecture Notes

- `transcriber/audio.py`: pulls `int16` PCM frames from the chosen device at 16 kHz (configurable).  
- `transcriber/asr/speechmatics_backend.py`: realtime WebSocket client (`Authorization: Bearer <API key>`) streaming PCM and parsing partial/final JSON with diarization metadata.  
- `transcriber/asr/whisper_backend.py`: chunked realtime transcription using faster-whisper (GPU/M-series friendly).  
- `transcriber/asr/vosk_backend.py`: lightweight offline recognizer built on Vosk/Kaldi for zero-cost fallback.  
- `transcriber/pipeline.py`: orchestrates audio capture, chosen backend, transcript logging, and caption delivery.  
- `transcriber/zoom_caption.py`: throttled POSTs (`text/plain`, `seq` parameter) to Zoom’s Closed Caption API.  
- `transcriber/cli.py`: CLI helpers for device discovery, config inspection, backend override, and graceful shutdown.

Anticipated extensions (mirroring the proposal’s roadmap):

- Additional transcription backends (Whisper streaming, Google STT) via the same interface
- Post-processing pipeline (Esperanto diacritics normalisation, punctuation refinements)
- Observer hooks for on-screen display, translation, persistence

---

## 5. Next Steps & Validation

1. Validate Speechmatics handshake: confirm `start` payload matches your tenant’s latest schema (see Docs §Real-time Quickstart). Adjust `transcription_config` as needed (custom dictionary, `operating_point`, etc.).  
2. Run a dry rehearsal with recorded Esperanto audio: measure WER, diarization accuracy, delay. Use logs to capture `raw` payloads for tuning.  
3. Register frequent Esperanto-specific words in the Speechmatics Custom Dictionary (Docs §4) and mirror the same lexicon for Vosk post-processing if required.  
4. Validate the offline path: download the Vosk Esperanto model, run `python -m transcriber.cli --backend=vosk`, and compare WER/latency vs Speechmatics.  
5. Benchmark the Whisper backend on your hardware (`python -m transcriber.cli --backend=whisper`) to understand GPU/CPU load and tune `WHISPER_SEGMENT_DURATION`.  
6. When scaling to production, wrap the CLI with a supervisor (systemd, pm2) and add persistent logging/metrics as emphasised in the guidelines.  
7. Document participant consent workflow; automate “transcription active” notifications inside meeting invites.

For questions on alternate capture paths (Recall.ai bots, Meet Media API wrappers, Whisper fallback) reuse the abstractions in `audio.py` and `transcriber/asr/`—new producers/consumers slot in without touching the pipeline control logic.
