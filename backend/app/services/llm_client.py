"""
Generic chat-completion client. Agent 1 (clinical NER), Agent 2 (risk
classification) and Agent 3 (referral/WhatsApp drafting) each branch on
`isinstance(llm_client, MockLLMClient)`: LLM_PROVIDER=mock (default) keeps
the whole pipeline deterministic and offline; LLM_PROVIDER=real sends real
calls and (Agent 1/2 only) falls back to rule-based logic if the response
is missing, malformed, or the call fails. Agent 4 (report generation) is
still pure aggregation over already-structured fields and doesn't need an
LLM call at all.
"""
from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings


class LLMClientBase(ABC):
    @abstractmethod
    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        ...


class MockLLMClient(LLMClientBase):
    """Deterministic, template-based responses -- no network call. Good enough
    to exercise every downstream code path (referral letters, WhatsApp drafts)
    without an API key."""

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        return f"[mock LLM response for prompt beginning: {user_prompt[:60]!r}]"


class LLMClient(LLMClientBase):
    """Real OpenAI-compatible chat completion client. TODO before going live:
    set LLM_API_KEY / LLM_MODEL / LLM_BASE_URL in .env and set LLM_PROVIDER=real."""

    def __init__(self, settings: Settings):
        self.settings = settings

    async def complete(self, system_prompt: str, user_prompt: str) -> str:
        headers = {"Authorization": f"Bearer {self.settings.llm_api_key}"}
        payload = {
            "model": self.settings.llm_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.settings.llm_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


def get_llm_client(settings: Settings) -> LLMClientBase:
    return LLMClient(settings) if settings.llm_provider.lower() == "real" else MockLLMClient()
