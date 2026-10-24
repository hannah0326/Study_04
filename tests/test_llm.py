# 작성: 2026-10-22 22:31 KST
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import llm  # noqa: E402

MESSAGES = [{"role": "user", "content": "안녕"}]


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def ok(text="안녕하세요"):
    return Resp(200, {"choices": [{"message": {"content": text}}]})


class FakePost:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)


def chat(post, **kw):
    return llm.chat("m/a:free", MESSAGES, "KEY", 100, post=post, sleep=lambda s: None, **kw)


def test_chat_returns_content_and_sends_expected_body():
    post = FakePost([ok("결과")])
    assert chat(post) == "결과"
    sent = post.calls[0]
    assert sent["json"] == {"model": "m/a:free", "max_tokens": 100, "messages": MESSAGES}
    assert sent["headers"]["Authorization"] == "Bearer KEY"


def test_chat_merges_extra_body_for_reasoning_off():
    post = FakePost([ok()])
    chat(post, extra={"reasoning": {"enabled": False}})
    assert post.calls[0]["json"]["reasoning"] == {"enabled": False}


def test_error_object_inside_http_200_is_treated_as_its_code():
    # OpenRouter 는 200 본문에 error 를 담아 보내기도 한다.
    post = FakePost([Resp(200, {"error": {"code": 429, "message": "x"}}), ok("재시도 성공")])
    assert chat(post) == "재시도 성공"
    assert len(post.calls) == 2


def test_error_object_with_unavailable_code_marks_model_unavailable():
    with pytest.raises(llm.ModelUnavailableError):
        chat(FakePost([Resp(200, {"error": {"code": 404}})]))


def test_error_object_without_numeric_code_is_retried_as_server_error():
    post = FakePost([Resp(200, {"error": {"message": "?"}}), Resp(200, {"error": {"message": "?"}})])
    with pytest.raises(llm.RateLimitedError):
        chat(post)
    assert len(post.calls) == 2


@pytest.mark.parametrize("status", [400, 403, 404, 410])
def test_bad_request_and_missing_model_fall_back_to_next_model(status):
    with pytest.raises(llm.ModelUnavailableError):
        chat(FakePost([Resp(status)]))


def test_missing_choices_or_null_content_is_parse_error():
    for body in ({}, {"choices": []}, {"choices": [{"message": {"content": None}}]}):
        with pytest.raises(llm.ParseError):
            chat(FakePost([Resp(200, body)]))


def test_retry_once_then_rate_limited():
    post = FakePost([Resp(429), Resp(503)])
    waits = []
    with pytest.raises(llm.RateLimitedError):
        llm.chat("m", MESSAGES, "K", 10, post=post, sleep=waits.append)
    assert waits == [2] and len(post.calls) == 2


def test_401_message_hides_details():
    with pytest.raises(llm.ServiceError) as e:
        chat(FakePost([Resp(401)]))
    assert "401" not in str(e.value) and "KEY" not in str(e.value)


# --- 대체 모델 순서 ---
def test_run_with_fallback_returns_first_success_without_events():
    events = []
    model, result = llm.run_with_fallback(["a", "b"], lambda m: m.upper(), events.append)
    assert (model, result) == ("a", "A") and events == []


def test_run_with_fallback_walks_models_and_reports_reasons():
    def attempt(m):
        if m == "a":
            raise llm.RateLimitedError("x")
        if m == "b":
            raise llm.ModelUnavailableError("x")
        return "성공"

    events = []
    model, result = llm.run_with_fallback(["a", "b", "c"], attempt, events.append)
    assert (model, result) == ("c", "성공")
    assert [(e["model"], e["reason"], e["next_model"]) for e in events] == [("a", "rate_limited", "b"), ("b", "unavailable", "c")]


def test_run_with_fallback_does_not_catch_other_errors():
    def attempt(m):
        raise llm.ServiceError("키 문제")

    with pytest.raises(llm.ServiceError) as e:
        llm.run_with_fallback(["a", "b"], attempt)
    assert not isinstance(e.value, llm.RateLimitedError)


def test_run_with_fallback_can_also_fall_back_on_parse_error():
    def attempt(m):
        if m == "a":
            raise llm.ParseError("x")
        return "ok"

    events = []
    model, _ = llm.run_with_fallback(
        ["a", "b"], attempt, events.append, fall_on=(llm.RateLimitedError, llm.ModelUnavailableError, llm.ParseError)
    )
    assert model == "b" and events[0]["reason"] == "parse"


def test_run_with_fallback_all_failed_raises_friendly_error_with_cause():
    def attempt(m):
        raise llm.RateLimitedError("x")

    events = []
    with pytest.raises(llm.RateLimitedError) as e:
        llm.run_with_fallback(["a", "b"], attempt, events.append)
    assert "잠시 후" in str(e.value) and e.value.__cause__ is not None
    assert events[-1]["next_model"] is None


# --- JSON 추출 ---
@pytest.mark.parametrize(
    "text",
    ['{"a": 1}', '```json\n{"a": 1}\n```', '설명입니다.\n{"a": 1}\n끝'],
)
def test_extract_json_accepts_fences_and_prose(text):
    assert llm.extract_json(text) == {"a": 1}


@pytest.mark.parametrize("bad", ["", None, "없음", "{깨진", "[1, 2]"])
def test_extract_json_rejects_bad_text(bad):
    with pytest.raises(llm.ParseError):
        llm.extract_json(bad)
