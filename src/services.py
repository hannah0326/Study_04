# 작성: 2026-10-24 22:55 KST
# 3단계: 저장소(Supabase)와 로그인 제한기를 Streamlit 에 연결한다.
# DB 에 연결하지 못해도 1·2단계(재료 인식·레시피 추천)는 그대로 쓸 수 있어야 하므로, 실패는 예외 대신 (None, 메시지)로 돌려준다.
import logging
import time

import streamlit as st

import auth
import db
import repository

logger = logging.getLogger("fridge_app")

NOT_CONFIGURED = "저장소가 설정되지 않아 로그인과 저장을 쓸 수 없어요. (관리자: DATABASE_URL 이 필요합니다)"
RETRY_AFTER_SEC = 30  # 연결에 실패하면 이 시간 동안은 다시 시도하지 않는다(화면을 열 때마다 몇 초씩 기다리지 않게)

_failure = {"at": 0.0, "message": None}


def database_url():
    """Streamlit Secrets → 환경변수 → .env 순서로 접속 문자열을 찾는다."""
    secret = None
    try:
        secret = st.secrets.get("DATABASE_URL")
    except Exception:  # noqa: BLE001 - secrets 파일이 없으면 환경변수·.env 로 넘어간다
        pass
    return db.database_url(secret)


@st.cache_resource(show_spinner=False)
def _open_repository(url):
    """연결 풀과 스키마를 준비한다. 실패하면 예외가 나므로 캐시에 남지 않고 다음에 다시 시도할 수 있다."""
    database = db.Database(url)
    repo = repository.PostgresRepository(database)
    repo.init()
    return repo


def get_repository():
    """(저장소, None) 또는 (None, 사용자에게 보일 메시지)를 돌려준다."""
    url = database_url()
    if not url:
        return None, NOT_CONFIGURED
    if _failure["message"] and time.time() - _failure["at"] < RETRY_AFTER_SEC:
        return None, _failure["message"]
    try:
        repo = _open_repository(url)
    except db.StorageError as e:
        message = str(e)
    except Exception as e:  # noqa: BLE001 - 접속 정보가 섞일 수 있으므로 가려서 서버 로그에만 남긴다
        logger.error("저장소 준비 실패: %s: %s", type(e).__name__, db.redact(e, url))
        message = db.STORAGE_DOWN_MESSAGE
    else:
        _failure["message"] = None
        return repo, None
    _failure.update(at=time.time(), message=message)
    return None, message


@st.cache_resource(show_spinner=False)
def login_limiter():
    """서버 전체가 함께 쓰는 로그인 실패 제한기."""
    return auth.LoginLimiter()
