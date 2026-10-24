# 작성: 2026-10-22 22:30 KST
# OpenRouter 호출의 공통 부분. 이미지 인식(recognizer.py)과 레시피 생성(recipe.py)이 함께 쓴다.
# 429·5xx 한 번 재시도, 모델이 없거나 쓸 수 없을 때의 구분, 대체 모델 순서대로 시도하기를 담당한다.
import json
import re
import time

import requests

URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SEC = 120
# 429·5xx 는 한 번만 더 시도하고, 그래도 안 되면 다음 모델로 넘어간다.
RETRY_DELAYS = (2,)


class ServiceError(Exception):
    """사용자에게 그대로 보여 줘도 되는 메시지를 담는 오류."""


class ParseError(ServiceError):
    pass


class RateLimitedError(ServiceError):
    pass


class ModelUnavailableError(ServiceError):
    """모델이 없거나(404), 이 키로 쓸 수 없거나(403·410), 이 요청을 받지 못하는(400) 경우. 다음 모델로 넘어갈 수 있다."""


def notify(on_event, kind, **info):
    """진행 상황을 화면 등에 알린다. on_event 가 없으면 아무 일도 하지 않는다."""
    if on_event:
        on_event({"kind": kind, **info})


def extract_json(text):
    """응답 텍스트에서 JSON 객체를 꺼낸다. 코드 블록 표시와 앞뒤 설명 문장은 허용한다."""
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ParseError("모델 응답에서 JSON 을 찾지 못했습니다.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        raise ParseError("모델 응답 형식이 올바르지 않습니다.")


def _status_of(response):
    """HTTP 상태를 돌려준다. OpenRouter 는 200 본문에 error 객체를 담아 보내기도 하므로 그 코드를 상태로 본다."""
    status = response.status_code
    if status != 200:
        return status, None
    try:
        body = response.json()
    except ValueError:
        return status, None
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = body["error"].get("code")
        return (code if isinstance(code, int) else 502), body
    return status, body


def chat(model, messages, api_key, max_tokens, post=requests.post, sleep=time.sleep, on_event=None,
         timeout=TIMEOUT_SEC, extra=None):
    """모델 하나를 호출하고 응답 텍스트를 돌려준다. 429·5xx 는 RETRY_DELAYS 만큼만 재시도한다.

    extra 는 요청 본문에 더할 항목(예: {"reasoning": {"enabled": False}})이다.
    """
    body = {"model": model, "max_tokens": max_tokens, "messages": messages, **(extra or {})}
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(len(RETRY_DELAYS) + 1):
        notify(on_event, "request", model=model, attempt=attempt + 1)
        try:
            r = post(URL, headers=headers, json=body, timeout=timeout)
        except requests.Timeout:
            raise ServiceError("응답이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.")
        except requests.RequestException:
            raise ServiceError("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        status, data = _status_of(r)
        if status == 200:
            try:
                content = (data if data is not None else r.json())["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise ParseError("모델 응답을 해석하지 못했습니다.")
            if not content:
                raise ParseError("모델이 빈 응답을 보냈습니다.")
            return content
        if status == 429 or status >= 500:
            if attempt < len(RETRY_DELAYS):
                notify(on_event, "retry", model=model, status=status, wait=RETRY_DELAYS[attempt])
                sleep(RETRY_DELAYS[attempt])
                continue
            raise RateLimitedError("지금 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.")
        if status == 401:
            # 키 설정 문제는 사용자에게 원인을 알리지 않는다. 같은 키라 다른 모델로 바꿔도 소용없다.
            # 키 값은 어디에도 남기지 않는다.
            raise ServiceError("서비스 설정에 문제가 있습니다. 관리자에게 문의해 주세요.")
        if status in (400, 403, 404, 410):
            raise ModelUnavailableError("선택한 모델을 지금 사용할 수 없습니다.")
        raise ServiceError(f"요청에 실패했습니다. (HTTP {status})")


def run_with_fallback(models, attempt, on_event=None, fall_on=(RateLimitedError, ModelUnavailableError)):
    """models 를 차례로 attempt(model)로 시도한다. fall_on 오류면 다음 모델로 넘어가고 fallback 을 알린다.

    성공하면 (사용한 모델, attempt 의 결과)를 돌려준다. 모두 실패하면 마지막 오류를 원인으로 RateLimitedError 를 낸다.
    401 같은 그 밖의 오류는 모델을 바꿔도 소용없으므로 그대로 올린다.
    """
    last_error = None
    for i, model in enumerate(models):
        try:
            return model, attempt(model)
        except fall_on as e:
            last_error = e
            if isinstance(e, ModelUnavailableError):
                reason = "unavailable"
            elif isinstance(e, ParseError):
                reason = "parse"
            else:
                reason = "rate_limited"
            notify(on_event, "fallback", model=model, reason=reason, unavailable=reason == "unavailable",
                   next_model=models[i + 1] if i + 1 < len(models) else None)
    raise RateLimitedError("지금 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.") from last_error
