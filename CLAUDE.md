# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

<!-- 작성: 2026-10-22 12:01 KST -->

## 개요

냉장고 사진에서 식재료를 인식하고 레시피를 추천하는 Streamlit 앱(OpenRouter 무료 모델 사용)이다. 단계별 PRD는 `docs/`에 있고, 현재 1단계(식재료 인식)까지 구현되어 있다. Streamlit Community Cloud 무료 배포를 전제로 한다.

- `src/app.py`: Streamlit 화면(업로드·카메라, 진행 단계 표시, 재료별 한 줄 수정, 확정). 확정 목록은 `st.session_state["confirmed"]`.
- `src/rows.py`: 식재료 행 관리 순수 로직(행 id 부여, 삭제, 수정값 수집). 행마다 고유 id를 위젯 key로 쓴다. 순번을 key로 쓰면 가운데 행을 지울 때 마지막 행이 지워진 것처럼 보인다.
- `src/recognizer.py`: 화면과 무관한 인식 로직(이미지 검증·축소, OpenRouter 호출·재시도, JSON 파싱).
- `src/test_openrouter.py`: API 연결을 확인하는 단발 스크립트.
- `tests/`: 단위 테스트. `docs/`: PRD(`PRD_step1.md`~`PRD_step3.md`).
- 루트: `.env`(키, git 제외), `.env.example`, `.streamlit/secrets.toml.example`, `requirements.txt`

## 명령

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt   # 최초 1회
.venv/Scripts/python -m streamlit run src/app.py                                   # 앱 실행
.venv/Scripts/python -m pytest tests -q                                            # 전체 테스트
.venv/Scripts/python -m pytest tests/test_recognizer.py -k parse -q                # 일부 테스트
PYTHONIOENCODING=utf-8 .venv/Scripts/python src/test_openrouter.py                 # API 연결 확인
```

- Windows 콘솔에서 한글이 깨지지 않도록 스크립트 실행 시 `PYTHONIOENCODING=utf-8`을 붙인다.
- 테스트는 가짜 응답으로 동작하므로 네트워크·키가 필요 없다.

## 구조와 주의점

- 모델: 이미지 기본 `minimax/minimax-m3.1-flash:free`(`recognizer.VISION_MODEL`), 대체 `nvidia/nemotron-3.5-super-vl:free` → `dots-studio/dots-3-note-preview:free`(`FALLBACK_MODELS`), 텍스트(2단계 예정) `nvidia/nemotron-3.5-lightning:free`.
- API 키 조회 순서: 앱은 `st.secrets` → 환경변수 → 프로젝트 루트 `.env`(`recognizer.get_api_key()`). 키 값은 화면·로그·오류 문구에 출력하지 않는다. `.env`와 `.streamlit/secrets.toml`은 git에서 제외된다.
- 업로드 이미지는 검증 후 긴 변 1024px·약 300KB 이하 JPEG로 줄여(`prepare_image`) base64 data URL로 보낸다. 이미지는 저장하지 않는다. 업로드 한도 10MB는 `.streamlit/config.toml`의 `maxUploadSize`가 담당한다.
- `max_tokens`는 2000이다. Nemotron VL 같은 추론형 모델은 답하기 전에 추론에 토큰을 많이 쓰므로, 300처럼 작게 잡으면 응답이 중간에 끊긴다.
- 모델이 형식에 어긋나게 답하면 같은 모델에 1회 다시 요청한다. 429·5xx는 2초 뒤 한 번만 재시도하고, 그래도 실패하거나 모델이 없으면(403·404·410) `recognizer.FALLBACK_MODELS`를 차례로 시도한다. 401(키 문제)은 대체하지 않는다. 진입점은 `recognize_detailed()`이며 사용한 모델과 용량 변화를 함께 돌려준다. `tests/`가 검증한다.
- 이미지 모델 순서는 같은 이미지로 직접 시험한 응답 시간으로 정했다(2026-10-22, 모델당 1회: minimax 7초, nemotron-3.5-super-vl 19초, dots 24초). 모델 가용성이 바뀌면 `/api/v1/models`에서 `:free` + 이미지 입력 모델을 다시 조사해 갱신한다. 제외한 모델: `nemotron-3-nano-omni`(175초), `thinkingmachines/inkling*`(agentic 전용이라 403), `google/gemma-4-*`(공유 풀 429). `dots`는 추론에 토큰을 많이 써서 `max_tokens`가 작으면 답이 잘려 파싱에 실패할 수 있다.
- 식재료가 아닌 단순 도형 이미지는 모델이 빈 목록을 돌려준다. 정상 동작이며 앱은 "찾지 못함" 안내를 보여 준다.
- Streamlit은 `import`한 모듈을 파일이 바뀌어도 다시 읽지 않는다. `recognizer.py`·`rows.py`를 고친 뒤에는 실행 중인 서버를 재시작해야 반영된다(배포 앱은 Reboot app).
- 식재료 목록은 `st.data_editor`가 아니라 행마다 `st.columns`(경고·이름·수량·삭제)로 그린다. 좁은 화면에서도 한 줄이 유지되도록 `app.py`의 `ONE_LINE_CSS`가 `flex-wrap: nowrap`을 강제한다. Streamlit 버전이 바뀌어 `data-testid`가 달라지면 이 CSS를 다시 확인한다.
- `st.camera_input`은 만들어 두기만 해도 페이지를 열 때 카메라 권한을 요청하므로 토글을 켰을 때만 만든다.
- 요청 제한은 IP가 아니라 세션 기준이다(Streamlit에서 IP를 안정적으로 얻기 어려움).
- 무료 배포 서버의 디스크는 영구 저장소가 아니다. 3단계 저장에는 외부 DB가 필요하다.

## 무료 모델 관련 알려진 동작

- `google/gemma-4-26b-a4b-it:free`, `google/gemma-4-31b-it:free`는 Google AI Studio 공유 풀 한도 때문에 반복적으로 HTTP 429가 났다. 키나 코드 문제가 아니다.
- `nvidia/nemotron-3-super-120b-a12b:free`는 Nvidia 쪽에서 404(함수 없음)가 났다.
- 429·404는 제공사 오류이고 인증 오류(401)와 구분된다.

## 저장소 관례

- 새 파일에는 KST(UTC+9) 기준 작성 일시를 주석으로 표시한다.
- 저장소에 올라가는 텍스트(주석, 커밋 메시지, 문서)는 한국어로 쓴다.
- `.gitignore`는 `.env`, `.env.*`(`.env.example` 제외), `.streamlit/secrets.toml`, `.venv/`, 캐시, macOS의 `.DS_Store`를 제외한다.
