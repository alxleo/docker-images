"""Construct FinRobot's real provider adapters without issuing a model request."""

from finrobot.config import get_settings

for provider in ("openai", "anthropic"):
    settings = get_settings(
        provider_keys={provider: "construction-only"},
        model_name=f"{provider}:construction-check",
    )
    model = settings.create_model()
    assert model.model_name == "construction-check"
    print(f"{provider}: native provider construction passed")
