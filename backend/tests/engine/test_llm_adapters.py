"""Adapter unit tests with fake SDK clients (no network). They verify request shape, response parsing and
error mapping - not the behaviour of any real model."""
from types import SimpleNamespace as NS

import anthropic
import httpx
import openai
import pytest

from app.engine.llm_service import LLMError
from app.llm.anthropic_adapter import AnthropicProvider
from app.llm.base import ProviderError, TransientProviderError
from app.llm.openai_adapter import OpenAIProvider

KEY = "sk-test-NOT-A-REAL-KEY-abcdef0123456789"
SCHEMA = {"type": "object", "properties": {"terms": {"type": "array"}}, "required": ["terms"],
          "additionalProperties": False}


def _resp(status: int):
    return httpx.Response(status, request=httpx.Request("POST", "https://api.example.test/v1"))


class FakeOpenAI:
    calls: list = []
    result = None
    error: Exception | None = None

    def __init__(self, api_key, timeout, max_retries):
        assert api_key == KEY
        self.responses = NS(create=self._create)
        self.models = NS(retrieve=lambda m: NS(id=m), list=lambda: [NS(id="m2"), NS(id="m1")])

    def _create(self, **kw):
        FakeOpenAI.calls.append(kw)
        if FakeOpenAI.error:
            raise FakeOpenAI.error
        return FakeOpenAI.result


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.calls, FakeOpenAI.error = [], None
    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    return FakeOpenAI


def openai_result(text='{"terms": []}', status="completed", refusal=False):
    content = [NS(type="refusal", refusal="no")] if refusal else [NS(type="output_text", text=text)]
    return NS(status=status, output=[NS(type="message", content=content)], output_text=text,
              usage=NS(input_tokens=11, output_tokens=7))


def test_openai_request_uses_strict_json_schema_and_parses(fake_openai):
    fake_openai.result = openai_result()
    p = OpenAIProvider(api_key=KEY, model="model-x")
    assert p.extract_json("sys", "user", SCHEMA) == {"terms": []}
    call = fake_openai.calls[0]
    assert call["model"] == "model-x" and call["instructions"] == "sys" and call["store"] is False
    fmt = call["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["schema"] is SCHEMA
    assert p.last_usage.input_tokens == 11 and p.last_usage.output_tokens == 7
    assert KEY not in repr(p)


@pytest.mark.parametrize("result,code", [
    (openai_result(status="incomplete"), "truncated"),
    (openai_result(refusal=True), "refusal"),
])
def test_openai_incomplete_and_refusal(fake_openai, result, code):
    fake_openai.result = result
    with pytest.raises(ProviderError) as e:
        OpenAIProvider(api_key=KEY, model="m").extract_json("s", "u", SCHEMA)
    assert e.value.code == code


def test_openai_malformed_json_goes_to_bounded_retry(fake_openai):
    fake_openai.result = openai_result(text="{not json")
    with pytest.raises(LLMError, match="malformed JSON"):
        OpenAIProvider(api_key=KEY, model="m").extract_json("s", "u", SCHEMA)


@pytest.mark.parametrize("error,cls,code", [
    (lambda: openai.RateLimitError("q", response=_resp(429), body={"error": {"code": "insufficient_quota"}}),
     ProviderError, "quota_exceeded"),
    (lambda: openai.RateLimitError("r", response=_resp(429), body={"error": {"code": "rate_limit_exceeded"}}),
     TransientProviderError, "rate_limited"),
    (lambda: openai.AuthenticationError(f"bad key {KEY}", response=_resp(401), body=None), ProviderError, "invalid_key"),
    (lambda: openai.NotFoundError("nf", response=_resp(404), body=None), ProviderError, "model_not_found"),
    (lambda: openai.InternalServerError("ise", response=_resp(500), body=None), TransientProviderError,
     "provider_unavailable"),
])
def test_openai_error_mapping_never_echoes_provider_text(fake_openai, error, cls, code):
    fake_openai.error = error()
    with pytest.raises(cls) as e:
        OpenAIProvider(api_key=KEY, model="m").extract_json("s", "u", SCHEMA)
    assert e.value.code == code and KEY not in str(e.value) and e.value.__cause__ is None


def test_openai_connection_test_and_model_list(fake_openai):
    p = OpenAIProvider(api_key=KEY, model="m1")
    assert p.test_connection().ok and p.list_models() == ["m1", "m2"]
    fake_openai.error = None


class FakeAnthropic:
    error: Exception | None = None
    result = None
    calls: list = []
    headers: list = []

    def __init__(self, api_key, timeout, max_retries, default_headers=None):
        assert api_key == KEY
        FakeAnthropic.headers.append(default_headers)
        self.messages = NS(create=self._create)
        self.models = NS(retrieve=self._retrieve, list=lambda limit: NS(data=[NS(id="b"), NS(id="a")]))

    def _create(self, **kw):
        FakeAnthropic.calls.append(kw)
        if FakeAnthropic.error:
            raise FakeAnthropic.error
        return FakeAnthropic.result

    def _retrieve(self, model):
        if FakeAnthropic.error:
            raise FakeAnthropic.error
        return NS(id=model)


@pytest.fixture
def fake_anthropic(monkeypatch):
    FakeAnthropic.calls, FakeAnthropic.error, FakeAnthropic.headers = [], None, []
    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    return FakeAnthropic


def test_anthropic_request_and_parse(fake_anthropic):
    fake_anthropic.result = NS(stop_reason="end_turn", content=[NS(type="text", text='{"terms": []}')],
                               usage=NS(input_tokens=5, output_tokens=3))
    p = AnthropicProvider(api_key=KEY, model="claude-opus-5-5")
    assert p.extract_json("sys", "u", SCHEMA) == {"terms": []}
    call = fake_anthropic.calls[0]
    assert call["output_config"]["format"] == {"type": "json_schema", "schema": SCHEMA}
    assert call["model"] == "claude-opus-5-5" and call["system"] == "sys"


@pytest.mark.parametrize("stop,code", [("refusal", "refusal"), ("max_tokens", "truncated")])
def test_anthropic_stop_reasons(fake_anthropic, stop, code):
    fake_anthropic.result = NS(stop_reason=stop, content=[], usage=NS(input_tokens=1, output_tokens=1))
    with pytest.raises(ProviderError) as e:
        AnthropicProvider(api_key=KEY, model="m").extract_json("s", "u", SCHEMA)
    assert e.value.code == code


def test_anthropic_invalid_key_connection_result(fake_anthropic):
    fake_anthropic.error = anthropic.AuthenticationError(f"invalid x-api-key {KEY}", response=_resp(401), body=None)
    r = AnthropicProvider(api_key=KEY, model="m").test_connection()
    assert r.ok is False and r.code == "invalid_key" and KEY not in r.message


def _ok(fake):
    fake.result = NS(stop_reason="end_turn", content=[NS(type="text", text='{"terms": []}')],
                     usage=NS(input_tokens=5, output_tokens=3))


def test_opus_5_5_request_never_sends_thinking_controls(fake_anthropic):
    """Claude Opus 5.5 rejects {"type": "disabled"} and token budgets with a 400; depth is set via effort."""
    _ok(fake_anthropic)
    AnthropicProvider(api_key=KEY, model="claude-opus-5-5", effort="medium").extract_json("s", "u", SCHEMA)
    call = fake_anthropic.calls[0]
    assert "thinking" not in call and "thinking" not in call.get("extra_body", {})
    assert "budget_tokens" not in str(call) and "temperature" not in call
    assert call["output_config"]["effort"] == "medium" and call["model"] == "claude-opus-5-5"


def test_workspace_header_sent_only_when_configured(fake_anthropic):
    _ok(fake_anthropic)
    AnthropicProvider(api_key=KEY, model="claude-opus-5-5", workspace_id="wrkspc_01ABCdef234").test_connection()
    AnthropicProvider(api_key=KEY, model="claude-opus-5-5").test_connection()
    assert fake_anthropic.headers == [{"anthropic-workspace-id": "wrkspc_01ABCdef234"}, None]


def _bad_request(message):
    return anthropic.BadRequestError(message, response=_resp(400),
                                     body={"type": "error", "error": {"type": "invalid_request_error",
                                                                      "message": message}})


def test_unscoped_key_400_maps_to_workspace_required(fake_anthropic):
    # The exact message Anthropic returned for the user's key (request req_011Cg615vCGhituodnuSgc6M).
    fake_anthropic.error = _bad_request(
        "This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id "
        "header with the ID of the workspace to use. Add the header, or use an API key that is scoped to a "
        "workspace.")
    r = AnthropicProvider(api_key=KEY, model="claude-opus-5-5").test_connection()
    assert r.ok is False and r.code == "workspace_required" and "workspace ID" in r.message and KEY not in r.message


def test_other_400s_show_provider_detail_with_key_redacted(fake_anthropic):
    fake_anthropic.error = _bad_request(f"thinking.type: disabled is not supported for this model ({KEY})")
    r = AnthropicProvider(api_key=KEY, model="claude-opus-5-5").test_connection()
    assert r.code == "request_rejected" and "thinking.type" in r.message and KEY not in r.message
