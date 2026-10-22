# 작성: 2026-10-22 12:40 KST
# 1단계: 냉장고 사진에서 식재료를 인식한다. (화면과 분리된 순수 로직)
import base64
import io
import json
import os
import re
import time

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

URL = "https://openrouter.ai/api/v1/chat/completions"
VISION_MODEL = "nvidia/nemotron-3.5-super-vl:free"
# 기본 모델이 429 등으로 계속 실패하면 순서대로 시도한다.
# OpenRouter 가 인기 순위를 API 로 주지 않아, 덜 알려진 모델 순으로 직접 정한 목록이다.
# (2026-10-22 실제 이미지 호출로 동작 확인. inkling 계열은 agentic 전용이라 제외)
FALLBACK_MODELS = (
    "dots-studio/dots-3-note-preview:free",
    "minimax/minimax-m3.1-flash:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# 모델에 보내는 사진은 작게 줄인다. 한 변은 MAX_SIDE 이하, 용량은 TARGET_BYTES 안팎을 목표로 한다.
MAX_SIDE = 1024
TARGET_BYTES = 300 * 1024
JPEG_QUALITIES = (85, 75, 65, 55)
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
# 추론형 모델이라 작게 잡으면 응답이 중간에 끊긴다.
MAX_TOKENS = 2000
TIMEOUT_SEC = 120
# 429·5xx 는 한 번만 더 시도하고, 그래도 안 되면 다음 모델로 넘어간다.
RETRY_DELAYS = (2,)

CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

PROMPT = (
    "이 냉장고 사진에 보이는 식재료를 찾아 아래 JSON 형식으로만 답하세요. "
    "다른 설명이나 코드 블록 표시는 쓰지 마세요.\n"
    '{"ingredients": [{"name": "달걀", "quantity": "6개", "confidence": "high"}]}\n'
    "- name: 한국어 일반 명칭\n"
    "- quantity: 대략적인 수량, 알 수 없으면 빈 문자열\n"
    "- confidence: high, medium, low 중 하나\n"
    "- 용기, 선반, 가구 등 식재료가 아닌 것은 제외하세요."
)


class RecognitionError(Exception):
    """사용자에게 그대로 보여 줘도 되는 메시지를 담는 오류."""


class ImageError(RecognitionError):
    pass


class ParseError(RecognitionError):
    pass


class RateLimitedError(RecognitionError):
    pass


class ModelUnavailableError(RecognitionError):
    """모델이 없거나(404) 이 키로 쓸 수 없는 경우(403·410 등). 다음 모델로 넘어갈 수 있다."""


def get_api_key():
    """환경변수를 먼저 보고, 없으면 프로젝트 루트 .env 를 본다. 값은 출력하지 않는다."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(root, ".env"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("OPENROUTER_API_KEY="):
                    return line.split("=", 1)[1].strip().strip("\"'") or None
    except OSError:
        pass
    return None


def prepare_image(raw):
    """업로드 바이트를 검증하고, 회전을 반영해 긴 변 MAX_SIDE 이하, 용량 TARGET_BYTES 안팎의 JPEG 로 줄인다."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageError("파일이 너무 큽니다. 10MB 이하의 사진을 올려 주세요.")
    try:
        img = Image.open(io.BytesIO(raw))
        fmt = img.format
        if fmt not in ALLOWED_FORMATS:
            raise ImageError("JPEG, PNG, WebP 형식의 사진만 올릴 수 있습니다.")
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
    except RecognitionError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ImageError("이미지 파일을 읽을 수 없습니다. 다른 사진을 올려 주세요.")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    # 용량이 목표를 넘으면 화질을 낮추고, 그래도 크면 크기를 줄인다.
    for _ in range(4):
        for quality in JPEG_QUALITIES:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= TARGET_BYTES:
                return buf.getvalue()
        img = img.resize((max(1, int(img.width * 0.8)), max(1, int(img.height * 0.8))))
    return buf.getvalue()


def _extract_json(text):
    text = re.sub(r"```(?:json)?", "", text or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ParseError("모델 응답에서 식재료 목록을 찾지 못했습니다.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        raise ParseError("모델 응답 형식이 올바르지 않습니다.")


def parse_ingredients(text):
    """모델 응답 텍스트를 검증하고 이름 기준으로 중복을 합친 목록으로 만든다."""
    data = _extract_json(text)
    items = data.get("ingredients") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ParseError("모델 응답에 ingredients 목록이 없습니다.")
    merged = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        quantity = str(item.get("quantity") or "").strip()
        conf = str(item.get("confidence") or "").strip().lower()
        if conf not in CONFIDENCE_ORDER:
            conf = "medium"
        if name in merged:
            cur = merged[name]
            if not cur["quantity"]:
                cur["quantity"] = quantity
            if CONFIDENCE_ORDER[conf] > CONFIDENCE_ORDER[cur["confidence"]]:
                cur["confidence"] = conf
        else:
            merged[name] = {"name": name, "quantity": quantity, "confidence": conf}
    return list(merged.values())


def _notify(on_event, kind, **info):
    """진행 상황을 화면 등에 알린다. on_event 가 없으면 아무 일도 하지 않는다."""
    if on_event:
        on_event({"kind": kind, **info})


def call_model(jpeg_bytes, api_key, model=VISION_MODEL, post=requests.post, sleep=time.sleep, on_event=None):
    """비전 모델 하나를 호출하고 응답 텍스트를 돌려준다. 429·5xx 는 RETRY_DELAYS 만큼만 재시도한다."""
    data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode()
    body = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }
        ],
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    for attempt in range(len(RETRY_DELAYS) + 1):
        _notify(on_event, "request", model=model, attempt=attempt + 1)
        try:
            r = post(URL, headers=headers, json=body, timeout=TIMEOUT_SEC)
        except requests.Timeout:
            raise RecognitionError("응답이 너무 오래 걸립니다. 잠시 후 다시 시도해 주세요.")
        except requests.RequestException:
            raise RecognitionError("서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.")
        if r.status_code == 200:
            try:
                return r.json()["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError):
                raise ParseError("모델 응답을 해석하지 못했습니다.")
        if r.status_code == 429 or r.status_code >= 500:
            if attempt < len(RETRY_DELAYS):
                _notify(on_event, "retry", model=model, status=r.status_code, wait=RETRY_DELAYS[attempt])
                sleep(RETRY_DELAYS[attempt])
                continue
            raise RateLimitedError("지금 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요.")
        if r.status_code == 401:
            # 키 설정 문제는 사용자에게 원인을 알리지 않는다. 같은 키라 다른 모델로 바꿔도 소용없다.
            # 키 값은 어디에도 남기지 않는다.
            raise RecognitionError("서비스 설정에 문제가 있습니다. 관리자에게 문의해 주세요.")
        if r.status_code in (403, 404, 410):
            raise ModelUnavailableError("선택한 모델을 지금 사용할 수 없습니다.")
        raise RecognitionError(f"요청에 실패했습니다. (HTTP {r.status_code})")


def _recognize_with_model(jpeg, api_key, model, post, sleep, on_event=None):
    """모델 하나로 인식한다. 응답 형식이 깨지면 같은 모델에 1회 다시 요청한다."""
    last_error = None
    for n in range(2):
        if n:
            _notify(on_event, "parse_retry", model=model)
        try:
            text = call_model(jpeg, api_key, model=model, post=post, sleep=sleep, on_event=on_event)
            return parse_ingredients(text)
        except ParseError as e:
            last_error = e
    raise ParseError("모델 응답을 해석하지 못했습니다. 다시 시도해 주세요.") from last_error


def recognize_detailed(raw_image, api_key, post=requests.post, sleep=time.sleep, on_event=None):
    """업로드 바이트 → 결과 정보.

    기본 모델이 429·5xx(한 번 재시도 후)나 사용 불가로 실패하면 FALLBACK_MODELS 를 차례로 시도한다.
    돌려주는 값: items(식재료 목록), model(실제 사용한 모델), original_bytes, sent_bytes
    on_event 를 주면 진행 상황(resize, request, retry, parse_retry, fallback, done)을 dict 로 알려 준다.
    """
    if not api_key:
        raise RecognitionError("서비스 설정에 문제가 있습니다. 관리자에게 문의해 주세요.")
    jpeg = prepare_image(raw_image)
    _notify(on_event, "resize", original_bytes=len(raw_image), sent_bytes=len(jpeg))
    models = (VISION_MODEL, *FALLBACK_MODELS)
    last_error = None
    for i, model in enumerate(models):
        try:
            items = _recognize_with_model(jpeg, api_key, model, post, sleep, on_event)
        except (RateLimitedError, ModelUnavailableError) as e:
            last_error = e
            nxt = models[i + 1] if i + 1 < len(models) else None
            _notify(on_event, "fallback", model=model, next_model=nxt,
                    unavailable=isinstance(e, ModelUnavailableError))
            continue
        _notify(on_event, "done", model=model, count=len(items))
        return {"items": items, "model": model, "original_bytes": len(raw_image), "sent_bytes": len(jpeg)}
    raise RateLimitedError(
        "지금 요청이 몰려 있습니다. 잠시 후 다시 시도해 주세요."
    ) from last_error


def recognize(raw_image, api_key, post=requests.post, sleep=time.sleep):
    """업로드 바이트 → 식재료 목록."""
    return recognize_detailed(raw_image, api_key, post=post, sleep=sleep)["items"]
