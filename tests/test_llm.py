from types import SimpleNamespace

import ward.core.config as config_module
from ward.core.config import Config, LLMConfig
from ward.core.llm import complete_text, stream_text


class FakeMessages:
    def __init__(self):
        self.params = None

    def create(self, **params):
        self.params = params
        return SimpleNamespace(
            content=[SimpleNamespace(text="first"), SimpleNamespace(text="second")],
            usage=SimpleNamespace(input_tokens=10, output_tokens=4),
        )

    def stream(self, **params):
        self.params = params
        return FakeStream()


class FakeStream:
    text_stream = iter(["one", "two"])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def test_complete_text_normalizes_response_and_usage():
    previous = config_module._config
    config_module._config = Config(llm=LLMConfig(api_key="key", base_url="https://example.invalid", model="model-x"))
    messages = FakeMessages()
    client = SimpleNamespace(messages=messages)
    try:
        text, usage = complete_text(client, system="system", prompt="prompt", max_tokens=100)
    finally:
        config_module._config = previous

    assert text == "first\nsecond"
    assert usage == {
        "provider": "anthropic-compatible",
        "model": "model-x",
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": 14,
    }
    assert messages.params["messages"] == [{"role": "user", "content": "prompt"}]


def test_stream_text_uses_same_request_shape():
    previous = config_module._config
    config_module._config = Config(llm=LLMConfig(api_key="key", base_url="https://example.invalid", model="model-x"))
    messages = FakeMessages()
    try:
        chunks = list(stream_text(SimpleNamespace(messages=messages), system="system", prompt="prompt", max_tokens=100))
    finally:
        config_module._config = previous

    assert chunks == ["one", "two"]
    assert messages.params["model"] == "model-x"
