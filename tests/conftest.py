# 작성: 2026-10-24 22:58 KST
# 모든 테스트가 실제 DB(Supabase)에 접속하지 않도록, 저장소를 메모리 저장소로 바꿔 끼운다.
# (이 설정이 없으면 앱 화면 테스트가 .env 의 DATABASE_URL 로 진짜 DB 에 접속한다)
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import auth  # noqa: E402
import repository  # noqa: E402
import services  # noqa: E402


@pytest.fixture(autouse=True)
def memory_repo(monkeypatch):
    """테스트마다 새 메모리 저장소와 새 로그인 제한기를 쓴다. 테스트에서 이 이름으로 받아 직접 만지작거릴 수도 있다."""
    repo = repository.MemoryRepository()
    limiter = auth.LoginLimiter()
    monkeypatch.setattr(services, "get_repository", lambda: (repo, None))
    monkeypatch.setattr(services, "login_limiter", lambda: limiter)
    monkeypatch.setattr(services, "database_url", lambda: None)
    return repo
