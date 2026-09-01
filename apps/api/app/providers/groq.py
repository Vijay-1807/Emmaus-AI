from app.providers.openai_compat import OpenAICompatProvider


class GroqProvider(OpenAICompatProvider):
    def __init__(self, api_key: str, base_url: str, chat_model: str, fast_model: str):
        super().__init__("groq", api_key, base_url, chat_model)
        self.fast_model = fast_model
