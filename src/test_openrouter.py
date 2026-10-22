# 작성: 2026-10-22 11:00 KST
# OpenRouter API 동작 테스트: 텍스트 인식과 이미지 인식을 각각 호출한다.
import base64
import io
import os
import sys

import requests
from PIL import Image, ImageDraw

URL = "https://openrouter.ai/api/v1/chat/completions"
TEXT_MODEL = "nvidia/nemotron-3.5-lightning:free"
IMAGE_MODEL = "nvidia/nemotron-3.5-super-vl:free"


def load_key():
    """프로젝트 루트(src 의 상위 폴더)의 .env 에서 키를 읽는다. 값은 절대 출력하지 않는다."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(root, ".env")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip("\"'")
    sys.exit(".env 에 OPENROUTER_API_KEY 가 없습니다.")


def make_test_image():
    """빨간 원, 파란 사각형, 'HELLO 123' 글자가 있는 테스트 이미지를 만든다."""
    img = Image.new("RGB", (400, 200), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((20, 40, 120, 140), fill="red")
    d.rectangle((150, 40, 250, 140), fill="blue")
    d.text((280, 85), "HELLO 123", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def call(key, model, content):
    r = requests.post(
        URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": 2000},
        timeout=120,
    )
    print(f"HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        print(r.text[:500])
        return
    if "error" in data:
        print("오류:", data["error"])
        return
    print("실제 모델:", data.get("model"))
    print("응답:", data["choices"][0]["message"].get("content"))


if __name__ == "__main__":
    key = load_key()
    print("== 텍스트 테스트 ==", TEXT_MODEL)
    call(key, TEXT_MODEL, "한국의 수도는 어디인가요? 한 문장으로 한국어로 답하세요.")
    print("\n== 이미지 테스트 ==", IMAGE_MODEL)
    call(key, IMAGE_MODEL, [
        {"type": "text", "text": "이 이미지에 어떤 도형과 글자가 있나요? 색상도 알려 주세요. 한국어로 답하세요."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + make_test_image()}},
    ])
