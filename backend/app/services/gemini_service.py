"""
Thin, real wrapper around the Gemini API (google-genai SDK).

Design notes:
- This is the ONLY place in the codebase that talks to Gemini directly.
  Agents call `GeminiService.generate_json(...)`, never the SDK directly.
  That means swapping API-key auth for Vertex AI service-account auth later
  is a one-file change.
- `generate_json` asks Gemini for a JSON-only response and validates it
  against the caller-supplied Pydantic model. If Gemini returns malformed
  JSON, we retry once with an explicit correction prompt before failing —
  this is the "validate outputs / retry" behaviour the Coordinator relies on.
- If no API key is configured, this raises GeminiNotConfiguredError instead
  of returning fabricated content. Per project requirements, we never fake
  AI output — a missing key is a hard failure surfaced to the caller.
"""
from __future__ import annotations

import json
import logging
from typing import TypeVar

from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, ValidationError

from app.config import get_settings

logger = logging.getLogger("cineflow.gemini")

T = TypeVar("T", bound=BaseModel)


class GeminiNotConfiguredError(RuntimeError):
    """Raised when a Gemini call is attempted without valid credentials."""


class GeminiGenerationError(RuntimeError):
    """Raised when Gemini output cannot be parsed/validated after retries."""


class GeminiService:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._client: genai.Client | None = None

    def _get_client(self) -> genai.Client:
        if not self._settings.gemini_configured:
            raise GeminiNotConfiguredError(
                "GEMINI_API_KEY (or Vertex AI project config) is not set. "
                "Add it to backend/.env — see .env.example."
            )
        if self._client is None:
            if self._settings.USE_VERTEX_AI:
                self._client = genai.Client(
                    vertexai=True,
                    project=self._settings.GOOGLE_CLOUD_PROJECT,
                    location=self._settings.GOOGLE_CLOUD_LOCATION,
                )
            else:
                self._client = genai.Client(api_key=self._settings.GEMINI_API_KEY)
        return self._client

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[T],
        max_output_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> T:
        """Call Gemini and coerce+validate the response into `response_model`."""
        client = self._get_client()
        schema = response_model.model_json_schema()

        contents = (
            f"{user_prompt}\n\n"
            "Respond with ONLY valid JSON matching this exact schema. "
            "No markdown fences, no commentary, no trailing text.\n\n"
            f"SCHEMA:\n{json.dumps(schema)}"
        )

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=self._settings.GEMINI_MODEL,
                    contents=contents,
                    config=genai_types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                        response_mime_type="application/json",
                    ),
                )
                raw_text = (response.text or "").strip()
                data = json.loads(raw_text)
                return response_model.model_validate(data)
            except (json.JSONDecodeError, ValidationError) as exc:
                last_error = exc
                logger.warning("Gemini output failed validation (attempt %s): %s", attempt + 1, exc)
                contents = (
                    f"{contents}\n\nYour previous response was invalid JSON or did not match the "
                    f"schema. The error was: {exc}. Return corrected JSON only."
                )
            except Exception as exc:  # network / API errors — do not swallow
                logger.error("Gemini API call failed: %s", exc)
                raise

        raise GeminiGenerationError(
            f"Gemini did not return valid JSON matching {response_model.__name__} after retries: {last_error}"
        )


_gemini_service: GeminiService | None = None


def get_gemini_service() -> GeminiService:
    global _gemini_service
    if _gemini_service is None:
        _gemini_service = GeminiService()
    return _gemini_service
