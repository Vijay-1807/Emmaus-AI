import pytest

from app.providers.base import TaskType, extract_json
from app.providers.mock import MockProvider


def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = 'Here you go:\n```json\n{"scores": [9, 3]}\n```'
    assert extract_json(text) == {"scores": [9, 3]}


def test_extract_json_embedded():
    text = 'The answer is {"sufficient": true, "confidence": 0.9} as requested'
    assert extract_json(text) == {"sufficient": True, "confidence": 0.9}


def test_extract_json_invalid():
    with pytest.raises(ValueError):
        extract_json("no json here at all")


@pytest.mark.asyncio
async def test_mock_provider_complete():
    provider = MockProvider()
    result = await provider.complete(
        [{"role": "user", "content": "hi"}], task=TaskType.CLASSIFY
    )
    assert result.provider == "mock"
    assert '"capabilities"' in result.text


@pytest.mark.asyncio
async def test_mock_provider_stream():
    provider = MockProvider()
    pieces = [piece async for piece in provider.stream([{"role": "user", "content": "hi"}])]
    assert pieces
    assert " ".join(pieces).strip()
