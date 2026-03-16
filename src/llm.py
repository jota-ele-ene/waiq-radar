"""
Abstracción del LLM. Soporta OpenAI, Anthropic y Google Gemini (google-genai SDK).
"""

import json
import logging
import time
from typing import List, Dict, Optional

logger = logging.getLogger("waiq-radar.llm")

MAX_RETRIES = 3
RETRY_BASE_DELAY = 20  # seconds


class LLMClient:
    def __init__(self, config: dict, tool_log: list):
        self.provider = config["llm"]["provider"]
        self.model = config["llm"]["model"]
        self.temperature = config["llm"]["temperature"]
        self.max_tokens = config["llm"]["max_tokens"]
        self.api_key = config["llm"]["api_key"]
        self.tool_log = tool_log
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        if self.provider == "openai":
            from openai import OpenAI
            self._client = OpenAI(api_key=self.api_key)
        elif self.provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        elif self.provider == "google":
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def complete(self, system_prompt: str, user_prompt: str, action_desc: str = "") -> str:
        """Envía un prompt al LLM y devuelve la respuesta como texto."""
        client = self._get_client()
        logger.info(f"LLM call [{self.provider}/{self.model}]: {action_desc[:80]}...")

        try:
            if self.provider == "openai":
                resp = client.chat.completions.create(
                    model=self.model,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                text = resp.choices[0].message.content
                usage = f"tokens: {resp.usage.prompt_tokens}in/{resp.usage.completion_tokens}out"

            elif self.provider == "anthropic":
                resp = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                text = resp.content[0].text
                usage = f"tokens: {resp.usage.input_tokens}in/{resp.usage.output_tokens}out"

            elif self.provider == "google":
                from google.genai import types

                text, usage = self._google_generate(client, system_prompt, user_prompt)

            else:
                raise ValueError(f"Proveedor LLM no soportado: {self.provider}")

            self.tool_log.append({
                "step": len(self.tool_log) + 1,
                "tool": f"llm ({self.provider})",
                "model": self.model,
                "action": action_desc,
                "result": f"OK — {usage}",
            })
            return text

        except Exception as e:
            logger.error(f"Error en LLM: {e}")
            self.tool_log.append({
                "step": len(self.tool_log) + 1,
                "tool": f"llm ({self.provider})",
                "model": self.model,
                "action": action_desc,
                "result": f"ERROR — {str(e)}",
            })
            raise

    def _google_generate(self, client, system_prompt: str, user_prompt: str):
        """Google Gemini call with retry logic for 429 rate-limit errors."""
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
        )

        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = client.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=config,
                )
                text = resp.text

                # Extract usage metadata if available
                usage_meta = getattr(resp, "usage_metadata", None)
                if usage_meta:
                    prompt_tokens = getattr(usage_meta, "prompt_token_count", "?")
                    output_tokens = getattr(usage_meta, "candidates_token_count", "?")
                    usage = f"tokens: {prompt_tokens}in/{output_tokens}out"
                else:
                    usage = "tokens: N/A (Gemini)"

                return text, usage

            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                is_rate_limit = "429" in str(e) or "resource_exhausted" in error_str or "rate" in error_str

                if is_rate_limit and attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        f"Rate limit hit (attempt {attempt}/{MAX_RETRIES}). "
                        f"Retrying in {delay}s..."
                    )
                    time.sleep(delay)
                else:
                    raise

        # Should not reach here, but just in case
        raise last_error

    def complete_json(self, system_prompt: str, user_prompt: str, action_desc: str = "") -> dict:
        """Envía prompt y parsea la respuesta como JSON."""
        raw = self.complete(system_prompt, user_prompt + "\n\nRespond ONLY with valid JSON.", action_desc)

        # Limpiar bloques de código markdown
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        return json.loads(text)
