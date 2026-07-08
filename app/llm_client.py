"""Thin OpenAI-compatible chat client."""

from typing import Dict, List

import httpx

from .config import config


class LLMClient:
    def __init__(self):
        self.base = config.LLM_BASE_URL.rstrip("/") if config.LLM_BASE_URL else ""
        self.key = config.LLM_API_KEY
        self.model = config.LLM_MODEL
        self.enabled = config.llm_enabled

    async def chat(self, messages: List[Dict[str, str]],
                   temperature: float = 0.2) -> str:
        if not self.enabled:
            raise RuntimeError("LLM endpoint not configured")
        url = f"{self.base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        async with httpx.AsyncClient(timeout=120) as cx:
            r = await cx.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        return data["choices"][0]["message"]["content"]


llm = LLMClient()
