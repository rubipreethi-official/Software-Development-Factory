"""
Base agent — all AI workers in the factory inherit from this.

Role in pipeline: Handles all LLM communication, retry logic,
rate limiting, cost tracking, and mock/real mode switching.
Never call the LLM directly — always go through execute().

Depends on: openai, settings, AGENT_MODELS
Used by: SpecGeneratorAgent, CodeGeneratorAgent, TestGeneratorAgent,
         ValidationAgent, OrchestratorAgent, LogSummaryAgent
"""
import asyncio
import time
import logging
from openai import AsyncOpenAI
from src.config.settings import settings, AGENT_MODELS, get_api_key_for_tier

logger = logging.getLogger(__name__)

class BaseAgent:
    def __init__(
        self,
        agent_id: str,
        system_prompt: str,
        model_tier: str = "tier1"
    ):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.model = AGENT_MODELS.get(model_tier, AGENT_MODELS["tier1"])
        self.model_tier = model_tier
        self.call_count = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0

        # Create client configured specifically for this model tier's API key
        self._nvidia_client = AsyncOpenAI(
            base_url=settings.nvidia_base_url,
            api_key=get_api_key_for_tier(model_tier),
        )
        
        self._openai_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
        )
        
        self._gemini_client = AsyncOpenAI(
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            api_key=settings.gemini_api_key,
        )

    async def execute(
        self,
        user_message: str,
        temperature: float = 0.1,
        max_tokens: int = 2000,
    ) -> str:
        """
        Execute an LLM call with automatic fallback chain.

        Flow: NVIDIA NIM (tier1/2) → NVIDIA fallback model
        In mock mode: returns placeholder instantly, no API calls made.
        """
        if settings.agent_mode == "mock":
            return self._mock_response(user_message)

        last_error = None
        for attempt in range(settings.agent_max_retries):
            try:
                # Fallback Provider Routing
                client = self._nvidia_client
                target_model = self.model
                provider_desc = "NVIDIA NIM"
                
                if attempt == 1:
                    client = self._openai_client
                    target_model = "gpt-4o"
                    provider_desc = "OpenAI GPT-4o"
                    logger.info(f"[{self.agent_id}] Falling back to {provider_desc}")
                elif attempt >= 2:
                    client = self._gemini_client
                    target_model = "gemini-1.5-pro"
                    provider_desc = "Google Gemini"
                    logger.info(f"[{self.agent_id}] Falling back to {provider_desc}")

                start = time.time()
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=target_model,
                        messages=[
                            {"role": "system", "content": self.system_prompt},
                            {"role": "user",   "content": user_message},
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    ),
                    timeout=float(settings.agent_timeout_seconds),
                )
                latency_ms = int((time.time() - start) * 1000)
                self._log_call(response.usage, latency_ms, f"{target_model} ({provider_desc})")
                return response.choices[0].message.content

            except asyncio.TimeoutError:
                last_error = f"timeout attempt {attempt + 1}"
                logger.warning(f"[{self.agent_id}] {last_error}")
                await asyncio.sleep(2 ** attempt)

            except Exception as e:
                error_str = str(e)
                wait = (2 ** attempt) * 2   
                logger.warning(
                    f"[{self.agent_id}] Attempt {attempt + 1} failed: {error_str}. "
                    f"Waiting {wait}s."
                )
                await asyncio.sleep(wait)
                last_error = error_str

        raise RuntimeError(
            f"[{self.agent_id}] All fallbacks exhausted. Last: {last_error}"
        )

    def _log_call(self, usage, latency_ms: int, model: str) -> None:
        """Track tokens and latency for cost monitoring."""
        self.call_count += 1
        if usage:
            self.total_tokens_in  += getattr(usage, "prompt_tokens", 0) or 0
            self.total_tokens_out += getattr(usage, "completion_tokens", 0) or 0
        logger.info(
            f"[{self.agent_id}] calls={self.call_count} "
            f"tokens_in={self.total_tokens_in} "
            f"tokens_out={self.total_tokens_out} "
            f"latency={latency_ms}ms model={model}"
        )

    def _mock_response(self, user_message: str) -> str:
        """Realistic placeholder for mock mode — no API calls."""
        return (
            f"[MOCK] Agent: {self.agent_id} | Model: {self.model}\n"
            f"Input: {user_message[:80]}...\n"
            f"Set AGENT_MODE=real in .env to use live API."
        )
