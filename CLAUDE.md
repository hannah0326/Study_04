# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- 작성: 2026-10-22 11:30 KST -->

## 개요

OpenRouter API 연동을 확인하는 작은 학습용 저장소다. 빌드·린트·테스트 설정은 없다.

- `src/`: 코드. 현재는 단일 스크립트 `src/test_openrouter.py`뿐이다.
- `docs/`: 문서. 냉장고 사진 레시피 앱의 단계별 PRD(`PRD_step1.md`~`PRD_step3.md`)가 있다.
- 루트: `.env`(키, git 제외), `.env.example`, `.gitignore`, `CLAUDE.md`

## 실행

```bash
PYTHONIOENCODING=utf-8 python src/test_openrouter.py
```

- Windows 콘솔에서 한글이 깨지지 않도록 `PYTHONIOENCODING=utf-8`을 붙인다.
- 의존성은 `requests`, `Pillow`이며 별도 requirements 파일은 없다. `python-dotenv`는 설치되어 있지 않다.

## 구조와 주의점

- `src/test_openrouter.py`는 텍스트 호출과 이미지 호출을 한 번씩 보낸다. 모델은 파일 상단의 `TEXT_MODEL`, `IMAGE_MODEL` 상수로 바꾼다.
  - 현재 텍스트: `nvidia/nemotron-3.5-lightning:free`
  - 현재 이미지: `nvidia/nemotron-3.5-super-vl:free`
- API 키는 프로젝트 루트 `.env`의 `OPENROUTER_API_KEY`에서 `load_key()`가 직접 파싱해 읽는다. `.env.example`은 값이 빈 템플릿이다. `.env`는 `.gitignore`로 제외된다. 키 값은 화면에 출력하지 않는다.
- 이미지는 Pillow로 테스트 이미지(빨간 원, 파란 사각형, "HELLO 123")를 만들어 base64 data URL로 전송한다.
- `max_tokens`는 2000이다. Nemotron VL 같은 추론형 모델은 답하기 전에 추론에 토큰을 많이 쓰므로, 300처럼 작게 잡으면 응답이 중간에 끊긴다.

## 무료 모델 관련 알려진 동작

- `google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free`는 Google AI Studio 공유 풀 한도 때문에 반복적으로 HTTP 429가 났다. 키나 코드 문제가 아니다.
- `nvidia/nemotron-3-super-120b-a12b:free`는 Nvidia 쪽에서 404(함수 없음)가 났다.
- 429·404는 제공사 오류이고 인증 오류(401)와 구분된다.

## 저장소 관례

- 새 파일에는 KST(UTC+9) 기준 작성 일시를 주석으로 표시한다.
- 저장소에 올라가는 텍스트(주석, 커밋 메시지, 문서)는 한국어로 쓴다.
- `.gitignore`는 `.env`, `.env.*`(`.env.example` 제외), macOS의 `.DS_Store`를 제외한다.
