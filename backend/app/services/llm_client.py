"""
Generic chat-completion client used by Agent 3 (referral/WhatsApp drafting)
and Agent 4 (report narrative). Agent 1 (entity extraction) and Agent 2 (risk
reasoning) use their own rule-based mock logic in app/agents/ so the demo
pipeline behaves deterministically without a key -- swap those to call
LLMClientBase.complete() with a NER / classification prompt once LLM_API_KEY
is set (see the TODO comments in agent1_voice_comprehension.py and
agent2_risk_classification.py).
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
    set LLM_API_KEY / LLM_MODEL / LLM_BASE_URL in .env and flip USE_MOCKS=false."""

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
    return MockLLMClient() if settings.use_mocks else LLMClient(settings)
