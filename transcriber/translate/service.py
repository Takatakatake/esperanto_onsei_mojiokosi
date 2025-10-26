"""Translation service implementation (LibreTranslate default)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

import aiohttp

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except ImportError:  # pragma: no cover - optional dependency
    GoogleAuthRequest = None
    service_account = None

@dataclass
class TranslationResult:
    text: str
    translations: Dict[str, str]


class TranslationService:
    """Translate Esperanto transcripts into target languages."""

    def __init__(
        self,
        enabled: bool,
        source_language: str = "eo",
        targets: Optional[Iterable[str]] = None,
        provider: str = "libre",
        libre_url: str = "https://libretranslate.de",
        libre_api_key: Optional[str] = None,
        timeout: float = 8.0,
        google_api_key: Optional[str] = None,
        google_model: Optional[str] = None,
        google_credentials_path: Optional[str] = None,
    ) -> None:
        self.enabled = enabled and bool(targets)
        self.source_language = source_language
        self.targets = list(targets or [])
        self.provider = provider
        self.libre_url = libre_url.rstrip("/")
        self.libre_api_key = libre_api_key
        self.google_api_key = google_api_key
        self.google_model = google_model
        self.google_credentials_path = Path(google_credentials_path).expanduser() if google_credentials_path else None
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None
        self._lock = asyncio.Lock()
        self._google_credentials = None
        self._google_request = None
        if self.provider == "google" and not self.google_api_key:
            if self.google_credentials_path and service_account and GoogleAuthRequest:
                try:
                    self._google_credentials = service_account.Credentials.from_service_account_file(
                        str(self.google_credentials_path),
                        scopes=["https://www.googleapis.com/auth/cloud-translation"],
                    )
                    self._google_request = GoogleAuthRequest()
                except Exception as exc:  # noqa: BLE001
                    logging.error("Failed to load Google credentials from %s: %s", self.google_credentials_path, exc)
            elif not self.google_credentials_path:
                logging.error("Google translation provider selected but GOOGLE_TRANSLATE_CREDENTIALS_PATH not set.")
            else:
                logging.error(
                    "google-auth not available; install google-auth to use service account credentials."
                )

    async def close(self) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    async def translate(self, text: str) -> TranslationResult:
        if not self.enabled or not text.strip():
            return TranslationResult(text=text, translations={})

        translations: Dict[str, str] = {}
        async with self._lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession(timeout=self._timeout)

            tasks = [self._translate_single(text, target) for target in self.targets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for target, result in zip(self.targets, results):
                if isinstance(result, Exception):
                    logging.error("Translation to %s failed: %s", target, result)
                elif result:
                    translations[target] = result

        return TranslationResult(text=text, translations=translations)

    async def _translate_single(self, text: str, target: str) -> Optional[str]:
        if self.provider == "libre":
            return await self._translate_libre(text, target)
        if self.provider == "google":
            return await self._translate_google(text, target)
        logging.error("Unknown translation provider: %s", self.provider)
        return None

    async def _translate_libre(self, text: str, target: str) -> Optional[str]:
        assert self._session
        payload = {
            "q": text,
            "source": self.source_language,
            "target": target,
            "format": "text",
        }
        if self.libre_api_key:
            payload["api_key"] = self.libre_api_key

        url = f"{self.libre_url}/translate"
        async with self._session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body}")
            data = await resp.json()
            return data.get("translatedText")

    async def _translate_google(self, text: str, target: str) -> Optional[str]:
        assert self._session
        params = {}
        headers = {}
        if self.google_api_key:
            params["key"] = self.google_api_key
        elif self._google_credentials and self._google_request:
            await self._ensure_google_token()
            if not self._google_credentials.token:
                logging.error("Failed to obtain Google OAuth token for translation.")
                return None
            headers["Authorization"] = f"Bearer {self._google_credentials.token}"
        else:
            logging.error(
                "Google translation requested but neither GOOGLE_TRANSLATE_API_KEY nor valid credentials provided."
            )
            return None
        payload = {
            "q": text,
            "source": self.source_language,
            "target": target,
            "format": "text",
        }
        if self.google_model:
            payload["model"] = self.google_model
        url = "https://translation.googleapis.com/language/translate/v2"
        async with self._session.post(url, params=params, json=payload, headers=headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {body}")
            data = await resp.json()
            translations = data.get("data", {}).get("translations", [])
            if translations:
                return translations[0].get("translatedText")
            return None

    async def _ensure_google_token(self) -> None:
        if not self._google_credentials or not self._google_request:
            return
        if self._google_credentials.valid and self._google_credentials.token:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._google_credentials.refresh, self._google_request)
