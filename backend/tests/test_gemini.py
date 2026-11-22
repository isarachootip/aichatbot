"""Unit tests for Google Gemini 1024-dim embedder and structured-output LLM client."""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.rag.embeddings import create_embedder
from app.rag.embeddings_gemini import GeminiEmbedder, resolve_vertexai_flag
from app.rag.llm import AnthropicLLMClient, create_llm_client
from app.rag.llm_gemini import GeminiLLMClient


def test_resolve_vertexai_flag_defaults_false_unless_explicit() -> None:
    assert resolve_vertexai_flag("AQ.example-key", None) is False
    assert resolve_vertexai_flag("AIzaExampleStudioKey", None) is False
    assert resolve_vertexai_flag("AQ.example", False) is False
    assert resolve_vertexai_flag("AIzaExample", True) is True


async def test_gemini_embedder_batches_l2_normalizes_and_validates_1024_dims() -> None:
    fake_models = SimpleNamespace(embed_content=MagicMock())

    def _fake_embed(*, model: str, contents: list[str], config: object) -> SimpleNamespace:
        assert model == "gemini-embedding-001"
        assert getattr(config, "output_dimensionality", None) == 1024
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[2.0] * 1024) for _ in contents]
        )

    fake_models.embed_content.side_effect = _fake_embed
    embedder = GeminiEmbedder(
        api_key="test-key",
        model="gemini-embedding-001",
        client=SimpleNamespace(models=fake_models),
    )

    vectors = await embedder.embed_texts(["ข้อ 1", "ข้อ 2", "ข้อ 3"], batch_size=2)
    q_vec = await embedder.embed_query("คำถาม")

    assert len(vectors) == 3
    assert len(q_vec) == 1024
    norm = math.sqrt(sum(v * v for v in q_vec))
    assert abs(norm - 1.0) < 1e-5
    assert fake_models.embed_content.call_count == 3


async def test_gemini_llm_client_parses_structured_json_and_handles_invalid_json() -> None:
    payload = (
        '{"answer_text":"ค่าส่ง 40 บาทค่ะ","handoff":false,'
        '"handoff_reason":null,"cited_chunk_indices":[1]}'
    )
    ok_resp = SimpleNamespace(
        text=payload,
        usage_metadata=SimpleNamespace(prompt_token_count=150, candidates_token_count=30),
    )
    fake_models = SimpleNamespace(generate_content=MagicMock(return_value=ok_resp))
    client = GeminiLLMClient(api_key="test-key", client=SimpleNamespace(models=fake_models))

    res = await client.generate_grounded_reply(
        system_prompt="sys",
        messages=[{"role": "user", "content": "ค่าส่งกี่บาท"}],
        model="gemini-2.5-flash",
    )

    assert res.answer_text == "ค่าส่ง 40 บาทค่ะ"
    assert res.handoff is False
    assert res.cited_chunk_indices == [1]
    assert res.input_tokens == 150
    assert res.output_tokens == 30

    bad_resp = SimpleNamespace(
        text="not-json",
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=10),
    )
    fake_models.generate_content.return_value = bad_resp
    fallback = await client.generate_grounded_reply(
        system_prompt="sys",
        messages=[{"role": "user", "content": "hi"}],
        model="gemini-2.5-flash",
    )
    assert fallback.handoff is True
    assert fallback.handoff_reason == "invalid_structured_json"


def test_factories_support_both_gemini_and_anthropic() -> None:
    gem_settings = Settings(
        llm_provider="gemini",
        gemini_api_key="AIzaTest",
        embedding_provider="gemini",
        embedding_model="gemini-embedding-001",
    )
    assert isinstance(create_llm_client(gem_settings), GeminiLLMClient)
    assert isinstance(create_embedder(gem_settings), GeminiEmbedder)

    ant_settings = Settings(
        llm_provider="anthropic",
        anthropic_api_key="sk-ant-test",
    )
    assert isinstance(create_llm_client(ant_settings), AnthropicLLMClient)

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiLLMClient(api_key="")
