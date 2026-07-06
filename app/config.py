from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelSlotSettings(BaseSettings):
    """A single config-selected LLM slot (Advisor Model or Vision Describer).

    provider selects the LangChain integration: "openai" covers any
    OpenAI-compatible endpoint (Typhoon, GPT), "anthropic" covers Claude,
    "google" covers Gemini. No provider is architecturally required — see
    docs/adr/0001-two-model-pipeline.md.
    """

    provider: str
    model: str
    api_key: str
    base_url: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_nested_delimiter="__", extra="ignore")

    # LINE Messaging API
    line_channel_secret: str
    line_channel_access_token: str

    # Advisor Model slot (conducts the Consultation, calls Health Record tools)
    advisor_provider: str = "openai"
    advisor_model: str = "typhoon-v2.1-12b-instruct"
    advisor_api_key: str = ""
    advisor_base_url: str | None = "https://api.opentyphoon.ai/v1"

    # Vision Describer slot (tongue photo -> structured Tongue Description)
    describer_provider: str = "anthropic"
    describer_model: str = "claude-opus-4-8"
    describer_api_key: str = ""
    describer_base_url: str | None = None

    # Roboflow hosted tongue detector
    roboflow_api_key: str = ""
    roboflow_model_id: str = ""
    roboflow_confidence_threshold: float = 0.5
    roboflow_crop_padding_ratio: float = 0.12

    # MongoDB (Health Records + working buffer)
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "ttm_advisor"

    # Chroma (TTM corpus RAG)
    chroma_persist_dir: str = "./data/chroma"
    embedding_model_name: str = "BAAI/bge-m3"
    rag_top_k: int = 5

    # Consultation lifecycle
    consultation_gap_hours: float = 6.0
    health_record_inject_count: int = 3

    # Health Profile (ADR 0003) -- the memory ablation arm: off skips both
    # the Profile Updater at close and the face-sheet injection.
    health_profile_enabled: bool = True

    def advisor_slot(self) -> ModelSlotSettings:
        return ModelSlotSettings(
            provider=self.advisor_provider,
            model=self.advisor_model,
            api_key=self.advisor_api_key,
            base_url=self.advisor_base_url,
        )

    def describer_slot(self) -> ModelSlotSettings:
        return ModelSlotSettings(
            provider=self.describer_provider,
            model=self.describer_model,
            api_key=self.describer_api_key,
            base_url=self.describer_base_url,
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
