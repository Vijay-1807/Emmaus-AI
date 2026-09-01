from app.providers.openai_compat import OpenAICompatProvider


class CerebrasProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, base_url: str, chat_model: str):
        super().__init__("cerebras", api_key, base_url, chat_model)
