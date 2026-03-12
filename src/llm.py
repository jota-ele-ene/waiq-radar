"""
Abstracción del LLM. Soporta OpenAI, Anthropic y Google Gemini.
"""

import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("waiq-radar.llm")


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
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._client = genai
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
                model = client.GenerativeModel(self.model)
                full_prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
                resp = model.generate_content(
                    full_prompt,
                    generation_config={"temperature": self.temperature, "max_output_tokens": self.max_tokens},
                )
                text = resp.text
                usage = "tokens: N/A (Gemini)"

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
