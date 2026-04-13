"""
Central configuration for the Software Development Factory.
All environment variables validated here at startup.
Fail fast — missing required vars raise RuntimeError immediately.

Depends on: .env file, python-dotenv
Used by: every module that needs config
"""
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # MongoDB
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    mongodb_db_name: str = os.getenv("MONGODB_DB_NAME", "software_factory")

    # NVIDIA NIM API Keys per model tier
    nvidia_api_key_qwen: str = os.getenv("NVIDIA_API_KEY_QWEN", "")
    nvidia_api_key_mistral: str = os.getenv("NVIDIA_API_KEY_MISTRAL", "")
    nvidia_api_key_kimi: str = os.getenv("NVIDIA_API_KEY_KIMI", "")
    nvidia_api_key_minimax: str = os.getenv("NVIDIA_API_KEY_MINIMAX", "")
    nvidia_api_key_deepseek: str = os.getenv("NVIDIA_API_KEY_DEEPSEEK", "")
    
    # Fallback Providers
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    
    nvidia_base_url: str = os.getenv(
        "NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"
    )

    # Agent behavior
    agent_mode: str = os.getenv("AGENT_MODE", "mock")  # "real" or "mock"
    agent_max_retries: int = 3
    agent_timeout_seconds: int = 120

    # App
    environment: str = os.getenv("ENVIRONMENT", "development")
    secret_key: str = os.getenv("SECRET_KEY", "")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")

    def validate(self):
        """Call on startup — fail fast if critical vars missing."""
        if self.agent_mode == "real" and not self.nvidia_api_key_qwen:
            raise RuntimeError("NVIDIA_API_KEY_QWEN required when AGENT_MODE=real")
        if not self.mongodb_uri:
            raise RuntimeError("MONGODB_URI required")

settings = Settings()

### Model routing constants (single source of truth)
AGENT_MODELS = {
    "tier1":              "mistralai/mistral-small-4-119b-2603",
    "tier2_code":         "mistralai/mistral-small-4-119b-2603",
    "tier2_orchestrator": "moonshotai/kimi-k2.5",
    "tier2_summary":      "minimaxai/minimax-m2.7",
    "tier2_validation":   "deepseek-ai/deepseek-v3.2",
    "fallback":           "mistralai/mistral-small-4-119b-2603", 
}

def get_api_key_for_tier(tier: str) -> str:
    """Returns the API key for the corresponding model tier."""
    if tier == "tier1" or tier == "fallback" or tier == "tier2_code":
        return settings.nvidia_api_key_mistral
    elif tier == "tier2_orchestrator":
        return settings.nvidia_api_key_kimi
    elif tier == "tier2_summary":
        return settings.nvidia_api_key_minimax
    elif tier == "tier2_validation":
        return settings.nvidia_api_key_deepseek
    return settings.nvidia_api_key_qwen
