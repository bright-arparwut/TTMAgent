from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from app.config import ModelSlotSettings


def build_chat_model(slot: ModelSlotSettings) -> BaseChatModel:
    """Instantiate whichever chat model a config-selected slot names.

    provider="openai" covers any OpenAI-compatible endpoint, including
    Typhoon's hosted API via base_url -- no provider is architecturally
    required for either the Advisor Model or the Vision Describer slot.
    See docs/adr/0001-two-model-pipeline.md.
    """
    # base_url is only forwarded when set: both ChatAnthropic and ChatOpenAI
    # fall back to an env-var/default endpoint via default_factory, but only
    # when the field is omitted entirely -- passing base_url=None explicitly
    # would override that fallback with a literal None.
    base_url_kwargs = {"base_url": slot.base_url} if slot.base_url else {}

    if slot.provider == "openai":
        return ChatOpenAI(model=slot.model, api_key=slot.api_key, **base_url_kwargs)
    if slot.provider == "anthropic":
        return ChatAnthropic(model=slot.model, api_key=slot.api_key, **base_url_kwargs)
    if slot.provider == "google":
        return ChatGoogleGenerativeAI(model=slot.model, api_key=slot.api_key)

    raise ValueError(f"Unknown model provider: {slot.provider!r}")
