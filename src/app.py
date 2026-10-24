# 작성: 2026-10-22 12:23 KST
# 1·2단계 화면: 냉장고 사진 업로드 → 식재료 인식 → 수정·확정 → 조건 선택 → 레시피 생성
import re
import time

import streamlit as st

import llm
import recipe
import recognizer
import rows as rows_mod

RATE_LIMIT_COUNT = 5
RATE_LIMIT_WINDOW_SEC = 60


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


def cause_text(event):
    """형식 오류의 원인(어떤 문제였는지와 응답 앞부분)을 한 줄로 만든다. 모델 글자라서 이스케이프한다."""
    text = md_safe(event.get("cause") or "알 수 없음")
    if event.get("snippet"):
        text += f", 응답 앞부분 “{md_safe(event['snippet'])}”"
    return text


def start_progress(title, log):
    """진행 상자를 만들고, 이벤트를 한 줄씩 기록하는 함수와 끝내는 함수를 돌려준다. 총 소요 시간도 남긴다."""
    status = st.status(title, expanded=True)
    started = time.time()

    def on_event(event):
        line = describe_event(event)
        log.append(line)
        status.write(line)

    def finish(label, state):
        seconds = time.time() - started
        line = f"⏱ 총 {seconds:.1f}초"
        log.append(line)
        status.write(line)
        status.update(label=f"{label} · {seconds:.0f}초", state=state)

    return on_event, finish


def describe_event(event):
    """인식 진행 이벤트를 화면에 보일 한 줄로 바꾼다."""
    kind = event["kind"]
    if kind == "resize":
        return f"📐 사진 축소: {event['original_bytes'] // 1024}KB → {event['sent_bytes'] // 1024}KB"
    if kind == "request":
        return f"📡 {event['model']} 요청 ({event['attempt']}차 시도)"
    if kind == "response":
        return f"↳ {event['status']} 응답 ({event['seconds']}초)"
    if kind == "retry":
        return f"⏳ HTTP {event['status']} 요청 제한 — {event['wait']}초 뒤 다시 시도"
    if kind == "parse_retry":
        return f"🔁 {event['model']} 응답 형식 오류 — 다시 요청 (원인: {cause_text(event)})"
    if kind == "daily_limit":
        return (f"⛔ 하루 무료 호출 한도를 모두 썼어요 — 다른 모델도 같은 한도를 쓰므로 더 시도하지 않습니다 "
                f"({event['reset']}에 초기화)")
    if kind == "fallback":
        reason = {"unavailable": "사용 불가", "parse": f"응답 형식 오류가 계속됨 (원인: {cause_text(event)})"}.get(
            event.get("reason"), "요청 제한이 계속됨"
        )
        nxt = event["next_model"]
        return f"🔀 {event['model']} {reason} → 대체 모델 {nxt}로 전환" if nxt else f"🔀 {event['model']} {reason} — 더 시도할 모델이 없음"
    if kind == "round":
        return f"🍳 레시피 {event['need']}개 요청 ({event['round']}번째)" if event["round"] > 1 else f"🍳 레시피 {event['need']}개 요청"
    if kind == "excluded":
        return f"🚫 '{event['title']}' 제외: {event['reason']}"
    if kind == "done":
        return f"✅ {event['model']} {event.get('what', '인식')} 완료 ({event['count']}개)"
    return str(event)


def delete_row(row_id):
    """삭제 단추의 콜백. 지운 행의 위젯 값도 함께 정리한다."""
    st.session_state["rows"] = rows_mod.remove_row(st.session_state["rows"], row_id)
    st.session_state.pop(rows_mod.name_key(row_id), None)
    st.session_state.pop(rows_mod.qty_key(row_id), None)


def add_row():
    row_id = st.session_state.get("next_id", 0)
    st.session_state["rows"].append(rows_mod.blank_row(row_id))
    st.session_state["next_id"] = row_id + 1


DIFFICULTY_LABEL = recipe.DIFFICULTY_KO  # easy/medium/hard → 초급/중급/고급
# 조리 시간 선택지: (이름, 최소 분, 최대 분). "이상"은 최소 시간, "이내"는 최대 시간이다.
TIME_CHOICES = (("제한 없음", None, None), ("15분 이내", None, 15), ("30분 이내", None, 30), ("30분 이상", 30, None))
RECIPE_STATE_KEYS = ("recipe_result", "recipe_error", "recipe_log")


def clear_recipes():
    """재료가 바뀌면 이전 레시피는 이번 재료의 결과가 아니므로 모두 지운다."""
    for key in RECIPE_STATE_KEYS:
        st.session_state.pop(key, None)


def md_safe(text):
    """모델이 준 글자를 마크다운·링크·수식으로 해석하지 않도록 이스케이프한다. 모델 출력은 믿지 않는다."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$])", r"\\\1", str(text))


def recipe_options():
    """레시피 조건 입력 위젯을 그리고 선택값을 돌려준다."""
    st.selectbox("요리 종류", [None, *recipe.CUISINES], format_func=lambda v: "제한 없음" if v is None else v, key="opt_cuisine")
    st.selectbox(
        "난이도", [None, *recipe.DIFFICULTIES],
        format_func=lambda v: "제한 없음" if v is None else DIFFICULTY_LABEL[v], key="opt_difficulty",
    )
    st.selectbox("조리 시간", [c[0] for c in TIME_CHOICES], key="opt_time")
    st.number_input("인원수", min_value=1, max_value=10, value=2, step=1, key="opt_servings")
    st.multiselect(
        "알레르기", list(recipe.ALLERGEN_TERMS), accept_new_options=True, key="opt_allergies",
        placeholder="없음 (직접 입력도 가능)",
    )
    st.multiselect(
        "식단 제한", ["채식", "비건", "페스코"], accept_new_options=True, key="opt_diet", placeholder="없음",
    )
    st.radio(
        "추가 재료 사용", recipe.EXTRA_CHOICES, index=1, horizontal=True, key="opt_extra",
        help="불가: 가진 재료만 / 소량: 소금·간장 같은 기본 양념류만 / 허용: 자유롭게",
    )
    st.slider("추천 개수", 1, 5, 3, key="opt_count")
    _, min_minutes, max_minutes = next(c for c in TIME_CHOICES if c[0] == st.session_state["opt_time"])
    return {
        "cuisine": st.session_state["opt_cuisine"],
        "difficulty": st.session_state["opt_difficulty"],
        "servings": st.session_state["opt_servings"],
        "min_minutes": min_minutes,
        "max_minutes": max_minutes,
        "allergies": st.session_state["opt_allergies"],
        "restrictions": st.session_state["opt_diet"],
        "extra": st.session_state["opt_extra"],
        "count": st.session_state["opt_count"],
    }


def generate_recipes_clicked(confirmed, options):
    """레시피 생성 단추를 눌렀을 때. 진행 단계를 보여 주고 결과나 실패를 session_state 에 남긴다."""
    clear_recipes()
    if rate_limited():
        st.warning("요청이 너무 잦습니다. 1분 뒤에 다시 시도해 주세요.")
        return
    log = []
    st.session_state["recipe_log"] = log
    on_event, finish = start_progress("레시피를 만드는 중입니다. 최대 1~2분 걸릴 수 있어요.", log)
    try:
        result = recipe.generate_recipes(confirmed, options, get_key(), on_event=on_event)
    except llm.ServiceError as e:
        log.append(f"❌ {e}")
        st.session_state["recipe_error"] = str(e)
        finish("레시피 생성 실패", "error")
    else:
        st.session_state["recipe_result"] = result
        finish(f"레시피 {len(result['recipes'])}개 완료", "complete")
    # 단추 이름("다시 생성")과 결과·진행 기록을 한 번에 새로 그린다. 진행 기록은 접힌 영역에 남는다.
    st.rerun()


def render_recipes(result):
    recipes = result["recipes"]
    st.subheader(f"추천 레시피 {len(recipes)}개")
    if result["model"] and result["model"] != recipe.TEXT_MODEL:
        st.info(f"기본 모델을 쓸 수 없어 대체 모델({result['model']})로 만들었습니다. 내용을 꼼꼼히 확인해 주세요.")
    if not recipes:
        st.warning("조건에 맞는 레시피가 없어요. 조건을 완화하고 다시 생성해 보세요.")
    elif len(recipes) < result["requested"]:
        st.caption(f"요청한 {result['requested']}개 중 {len(recipes)}개만 조건에 맞았어요.")
    if result.get("note"):  # 하루 한도 소진 등으로 일부만 받고 멈춘 이유
        st.warning(md_safe(result["note"]))
    for i, r in enumerate(recipes):
        with st.container(border=True):
            st.markdown(f"**{i + 1}. {md_safe(r['title'])}**")
            lack = "부족한 재료 없음" if not r["missing"] else f"부족한 재료 {len(r['missing'])}개"
            kind = f"{r['cuisine']} · " if r.get("cuisine") else ""
            st.caption(f"{kind}⏱ {r['time_minutes']}분 · {DIFFICULTY_LABEL[r['difficulty']]} · {r['servings']}인분 · {lack}")
            if r["summary"]:
                st.write(md_safe(r["summary"]))
            if r["missing"]:
                st.markdown(" ".join(f":red-badge[🛒 {md_safe(m)}]" for m in r["missing"]))
            with st.expander("자세히 보기", key=f"recipe_detail_{i}"):
                st.markdown("**재료**")
                for ing in r["ingredients"]:
                    mark = "✅" if ing["have"] else "🛒"
                    st.markdown(f"- {mark} {md_safe(ing['name'])} {md_safe(ing['amount'])}")
                st.markdown("**만드는 법**")
                for n, step in enumerate(r["steps"], 1):
                    st.markdown(f"{n}\\. {md_safe(step)}")
    if result["excluded"]:
        with st.expander(f"조건 때문에 제외한 레시피 {len(result['excluded'])}개", key="recipe_excluded"):
            for title, reason in result["excluded"]:
                st.write(f"- {md_safe(title)}: {md_safe(reason)}")


def recipe_section(confirmed):
    """2단계: 확정된 재료로 조건을 고르고 레시피를 생성한다."""
    st.divider()
    st.subheader("🍳 레시피 추천")
    st.markdown("가진 재료: " + " ".join(f":gray-badge[{md_safe(i['name'])}]" for i in confirmed))
    options = recipe_options()
    st.caption("⚠️ 알레르기·식단 정보는 AI가 틀릴 수 있어요. 재료와 조리법을 직접 꼭 확인하세요.")
    has_result = "recipe_result" in st.session_state or "recipe_error" in st.session_state
    if st.button("다시 생성" if has_result else "레시피 생성", type="primary", key="recipe_go"):
        generate_recipes_clicked(confirmed, options)
    if st.session_state.get("recipe_log"):
        with st.expander("레시피 진행 기록", key="recipe_log_box"):
            for line in st.session_state["recipe_log"]:
                st.write(line)
    if "recipe_error" in st.session_state:
        st.error(f"❌ 레시피 생성에 실패했어요. {st.session_state['recipe_error']} 이전 결과는 보여 주지 않습니다.")
    if "recipe_result" in st.session_state:
        render_recipes(st.session_state["recipe_result"])


# 좁은 화면(휴대폰)에서도 이름·수량·삭제가 한 줄로 유지되게 한다. Streamlit 은 기본적으로 세로로 쌓는다.
ONE_LINE_CSS = """
<style>
div[data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.5rem !important; }
div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] { min-width: 0 !important; }
</style>
"""

st.set_page_config(page_title="냉장고 재료 인식", page_icon="🧊")
st.markdown(ONE_LINE_CSS, unsafe_allow_html=True)
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
    st.session_state.pop("rows", None)
    st.session_state.pop("run_info", None)
    clear_recipes()
    if rate_limited():
        st.warning("요청이 너무 잦습니다. 1분 뒤에 다시 시도해 주세요.")
    else:
        log = []
        st.session_state["progress_log"] = log
        on_event, finish = start_progress("사진을 분석하는 중입니다. 최대 1~2분 걸릴 수 있어요.", log)

        try:
            result = recognizer.recognize_detailed(source.getvalue(), get_key(), on_event=on_event)
            # id 는 계속 늘려서, 이전 인식 결과의 위젯 값이 새 행에 섞이지 않게 한다.
            new_rows, st.session_state["next_id"] = rows_mod.make_rows(
                result["items"], st.session_state.get("next_id", 0)
            )
            st.session_state["rows"] = new_rows
            st.session_state["run_info"] = result
            finish(f"인식 완료 ({len(result['items'])}개)", "complete")
            just_ran = True
        except recognizer.RecognitionError as e:
            st.session_state.pop("rows", None)
            log.append(f"❌ {e}")
            finish("인식 실패", "error")
            st.error(str(e))

# 새로 실행하지 않은 화면(표 수정 등)에서도 직전 진행 기록을 볼 수 있게 한다.
if not just_ran and st.session_state.get("progress_log"):
    with st.expander("진행 기록"):
        for line in st.session_state["progress_log"]:
            st.write(line)

if "rows" in st.session_state:
    rows_state = st.session_state["rows"]
    info = st.session_state.get("run_info")
    st.subheader("인식 결과")
    if info:
        st.caption(
            f"사진을 {info['original_bytes'] // 1024}KB → {info['sent_bytes'] // 1024}KB로 줄여 전송했습니다."
        )
        if info["model"] != recognizer.VISION_MODEL:
            st.info(f"기본 모델을 쓸 수 없어(혼잡하거나 서비스가 끝남) 대체 모델({info['model']})로 인식했습니다. 결과를 꼼꼼히 확인해 주세요.")
    if not rows_state:
        st.info("식재료를 찾지 못했습니다. 사진이 어둡거나 가려졌을 수 있어요. 아래 '재료 추가'로 직접 넣어 보세요.")
    else:
        st.caption("⚠️ 표시는 신뢰도가 낮은 항목입니다. 사진과 비교해 확인하고, 이름과 수량을 고치거나 🗑로 지울 수 있어요.")

    # 한 줄 = [신뢰도 경고] [재료 이름] [수량] [삭제]
    LINE = [0.5, 4, 2.5, 1]
    head = st.columns(LINE, vertical_alignment="center")
    head[1].caption("재료 이름")
    head[2].caption("수량")
    for row in rows_state:
        c_warn, c_name, c_qty, c_del = st.columns(LINE, vertical_alignment="center")
        c_warn.write("⚠️" if row["confidence"] == "low" else "")
        c_name.text_input(
            "재료 이름", value=row["name"], key=rows_mod.name_key(row["id"]),
            label_visibility="collapsed", placeholder="재료 이름",
        )
        c_qty.text_input(
            "수량", value=row["quantity"], key=rows_mod.qty_key(row["id"]),
            label_visibility="collapsed", placeholder="예: 2개",
        )
        c_del.button("🗑", key=f"del_{row['id']}", on_click=delete_row, args=(row["id"],), help="이 재료 삭제")
    st.button("＋ 재료 추가", on_click=add_row)

    if st.button("이 목록으로 확정"):
        confirmed = rows_mod.collect_confirmed(rows_state, st.session_state)
        if confirmed:
            st.session_state["confirmed"] = confirmed
            clear_recipes()  # 재료를 다시 확정했으면 이전 레시피는 지운다
        else:
            st.session_state.pop("confirmed", None)
            clear_recipes()
            st.warning("재료가 하나도 없습니다. 한 개 이상 입력해 주세요.")

if "confirmed" in st.session_state:
    names = ", ".join(i["name"] for i in st.session_state["confirmed"])
    st.success(f"확정됨: {names}")
    recipe_section(st.session_state["confirmed"])
