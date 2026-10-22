# 작성: 2026-10-22 12:50 KST
# 1단계 화면: 냉장고 사진 업로드 → 식재료 인식 → 수정·확정
import time

import pandas as pd
import streamlit as st

import recognizer

RATE_LIMIT_COUNT = 5
RATE_LIMIT_WINDOW_SEC = 60
CONF_LABEL = {"high": "높음", "medium": "보통", "low": "낮음"}
CONF_VALUE = {v: k for k, v in CONF_LABEL.items()}


def get_key():
    """배포 환경의 st.secrets 를 먼저 보고, 없으면 환경변수·.env 를 본다."""
    try:
        key = st.secrets["OPENROUTER_API_KEY"]
        if key:
            return key
    except Exception:
        pass
    return recognizer.get_api_key()


def rate_limited():
    """세션당 분당 호출 수를 제한한다. 공유 무료 한도를 보호하기 위함이다."""
    now = time.time()
    calls = [t for t in st.session_state.get("calls", []) if now - t < RATE_LIMIT_WINDOW_SEC]
    st.session_state["calls"] = calls
    if len(calls) >= RATE_LIMIT_COUNT:
        return True
    calls.append(now)
    return False


def describe_event(event):
    """인식 진행 이벤트를 화면에 보일 한 줄로 바꾼다."""
    kind = event["kind"]
    if kind == "resize":
        return f"📐 사진 축소: {event['original_bytes'] // 1024}KB → {event['sent_bytes'] // 1024}KB"
    if kind == "request":
        return f"📡 {event['model']} 요청 ({event['attempt']}차 시도)"
    if kind == "retry":
        return f"⏳ HTTP {event['status']} 요청 제한 — {event['wait']}초 뒤 다시 시도"
    if kind == "parse_retry":
        return f"🔁 {event['model']} 응답 형식 오류 — 다시 요청"
    if kind == "fallback":
        reason = "사용 불가" if event["unavailable"] else "요청 제한이 계속됨"
        nxt = event["next_model"]
        return f"🔀 {event['model']} {reason} → 대체 모델 {nxt}로 전환" if nxt else f"🔀 {event['model']} {reason} — 더 시도할 모델이 없음"
    if kind == "done":
        return f"✅ {event['model']} 인식 완료 ({event['count']}개)"
    return str(event)


def to_frame(items):
    return pd.DataFrame(
        [
            {"이름": i["name"], "수량": i["quantity"], "신뢰도": CONF_LABEL[i["confidence"]]}
            for i in items
        ],
        columns=["이름", "수량", "신뢰도"],
    )


def from_frame(df):
    out = []
    for _, row in df.iterrows():
        name = str(row["이름"] or "").strip()
        if not name or name == "nan":
            continue
        qty = row["수량"]
        qty = "" if pd.isna(qty) else str(qty).strip()
        conf = CONF_VALUE.get(row["신뢰도"], "medium")
        out.append({"name": name, "quantity": qty, "confidence": conf})
    return out


st.set_page_config(page_title="냉장고 재료 인식", page_icon="🧊")
st.title("🧊 냉장고 재료 인식")
st.caption("냉장고 사진을 올리면 안에 있는 식재료를 찾아 드립니다.")

uploaded = st.file_uploader("냉장고 사진 (JPEG, PNG, WebP · 10MB 이하)", type=["jpg", "jpeg", "png", "webp"])
# 켜기 전에는 camera_input 을 만들지 않는다. 만들면 페이지를 열 때마다 카메라 권한을 요청한다.
shot = st.camera_input("카메라로 촬영") if st.toggle("카메라로 직접 촬영") else None

source = uploaded or shot
if source is not None:
    st.image(source, caption="미리보기", width=360)

just_ran = False
if st.button("식재료 인식", type="primary", disabled=source is None):
    st.session_state.pop("confirmed", None)
    st.session_state.pop("items", None)
    st.session_state.pop("run_info", None)
    if rate_limited():
        st.warning("요청이 너무 잦습니다. 1분 뒤에 다시 시도해 주세요.")
    else:
        log = []
        st.session_state["progress_log"] = log
        status = st.status("사진을 분석하는 중입니다. 최대 1~2분 걸릴 수 있어요.", expanded=True)

        def on_event(event):
            line = describe_event(event)
            log.append(line)
            status.write(line)

        try:
            result = recognizer.recognize_detailed(source.getvalue(), get_key(), on_event=on_event)
            st.session_state["items"] = result["items"]
            st.session_state["run_info"] = result
            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
            status.update(label=f"인식 완료 ({len(result['items'])}개)", state="complete")
            just_ran = True
        except recognizer.RecognitionError as e:
            st.session_state.pop("items", None)
            log.append(f"❌ {e}")
            status.update(label="인식 실패", state="error")
            st.error(str(e))

# 새로 실행하지 않은 화면(표 수정 등)에서도 직전 진행 기록을 볼 수 있게 한다.
if not just_ran and st.session_state.get("progress_log"):
    with st.expander("진행 기록"):
        for line in st.session_state["progress_log"]:
            st.write(line)

if "items" in st.session_state:
    items = st.session_state["items"]
    info = st.session_state.get("run_info")
    st.subheader("인식 결과")
    if info:
        st.caption(
            f"사진을 {info['original_bytes'] // 1024}KB → {info['sent_bytes'] // 1024}KB로 줄여 전송했습니다."
        )
        if info["model"] != recognizer.VISION_MODEL:
            st.info(f"기본 모델이 혼잡해서 대체 모델({info['model']})로 인식했습니다. 결과를 꼼꼼히 확인해 주세요.")
    if not items:
        st.info("식재료를 찾지 못했습니다. 사진이 어둡거나 가려졌을 수 있어요. 아래 표에 직접 추가해 보세요.")
    else:
        st.caption("신뢰도가 '낮음'인 항목은 사진과 비교해 확인해 주세요.")
    edited = st.data_editor(
        to_frame(items),
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        column_config={
            "신뢰도": st.column_config.SelectboxColumn("신뢰도", options=list(CONF_VALUE), default="보통"),
        },
        key=f"editor_{st.session_state.get('editor_version', 0)}",
    )
    if st.button("이 목록으로 확정"):
        confirmed = from_frame(edited)
        if confirmed:
            st.session_state["confirmed"] = confirmed
        else:
            st.session_state.pop("confirmed", None)
            st.warning("재료가 하나도 없습니다. 한 개 이상 입력해 주세요.")

if "confirmed" in st.session_state:
    names = ", ".join(i["name"] for i in st.session_state["confirmed"])
    st.success(f"확정됨: {names}")
    st.caption("다음 단계(레시피 생성)는 2단계에서 이어집니다.")
