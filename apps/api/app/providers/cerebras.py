from typing import Any

from app.providers.openai_compat import OpenAICompatProvider


class CerebrasProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, base_url: str, chat_model: str, vision_model: str = ""):
        super().__init__("cerebras", api_key, base_url, chat_model)
        self.chat_model = chat_model
        self.vision_model = vision_model

    def supports_vision(self) -> bool:
        return bool(self.vision_model)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        task: Any = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        json_mode: bool = False,
        ctx: Any = None,
    ) -> Any:
        from app.providers.base import TaskType

        if task == TaskType.VISION and model is None and self.vision_model:
            model = self.vision_model
        return await super().complete(
            messages,
            task=task,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            ctx=ctx,
        )
