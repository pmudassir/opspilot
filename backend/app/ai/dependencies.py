from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.ai.assistant.groq_model import GroqAssistantModel
from app.ai.assistant.model import ToolCallingModel
from app.ai.drafter import RequestDrafter
from app.ai.groq_drafter import GroqDrafter
from app.config import SettingsDep


@lru_cache
def _groq_drafter(api_key: str, model: str, timeout_seconds: float) -> GroqDrafter:
    # One client per configuration: reuses its HTTP connection pool across requests.
    return GroqDrafter(api_key=api_key, model=model, timeout_seconds=timeout_seconds)


def get_drafter(settings: SettingsDep) -> RequestDrafter | None:
    """None when AI isn't configured: the feature is off and the app works without it.
    Tests override this dependency with a fake; they never call a real provider."""
    if settings.groq_api_key is None:
        return None
    return _groq_drafter(
        settings.groq_api_key.get_secret_value(), settings.ai_model, settings.ai_timeout_seconds
    )


DrafterDep = Annotated[RequestDrafter | None, Depends(get_drafter)]


@lru_cache
def _groq_assistant_model(api_key: str, model: str, timeout_seconds: float) -> GroqAssistantModel:
    return GroqAssistantModel(api_key=api_key, model=model, timeout_seconds=timeout_seconds)


def get_assistant_model(settings: SettingsDep) -> ToolCallingModel | None:
    """None when AI isn't configured (feature off). Tests override this with a scripted model."""
    if settings.groq_api_key is None:
        return None
    return _groq_assistant_model(
        settings.groq_api_key.get_secret_value(), settings.ai_model, settings.ai_timeout_seconds
    )


AssistantModelDep = Annotated[ToolCallingModel | None, Depends(get_assistant_model)]
