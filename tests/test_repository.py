# 작성: 2026-10-24 23:00 KST
# 저장소 계약 테스트. 같은 테스트를 메모리 저장소와(RUN_LIVE_DB=1 이면) 실제 Postgres 에 모두 돌려서 두 구현이 같은 규칙을 지키는지 확인한다.
# 실제 DB 쪽은 시험용 임시 스키마(app_test_<무작위>)를 만들고 끝나면 지운다. 실제 앱의 `app` 스키마는 건드리지 않는다.
import datetime as dt
import os
import secrets

import pytest

import db
import repository

LIVE = os.environ.get("RUN_LIVE_DB") == "1"
UTC = dt.timezone.utc


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.skipif(not LIVE, reason="RUN_LIVE_DB=1 일 때만 실제 DB 로 시험"))])
def repo(request):
    if request.param == "memory":
        yield repository.MemoryRepository()
        return
    url = db.database_url()
    database = db.Database(url)
    schema = "app_test_" + secrets.token_hex(4)
    repo = repository.PostgresRepository(database, schema=schema)
    repo.init()
    try:
        yield repo
    finally:
        with database.transaction() as cur:
            cur.execute(f'drop schema if exists "{schema}" cascade')
        database.close()


def sample_recipe(title="달걀 볶음", names=("달걀", "양배추"), minutes=20, difficulty="easy", cuisine="한식"):
    return {"title": title, "summary": "요약", "cuisine": cuisine, "servings": 2, "time_minutes": minutes, "difficulty": difficulty,
            "ingredients": [{"name": n, "amount": "1개", "have": True} for n in names], "missing": ["소금"], "steps": ["볶는다."]}


def make_user(repo, email="a@example.com", provider="password"):
    return repo.create_user(email, provider, "이름", password_hash="$argon2id$x" if provider == "password" else None)


# --- 사용자 ----------------------------------------------------------------------------------
def test_create_and_find_users(repo):
    u = make_user(repo)
    assert u["email"] == "a@example.com" and u["provider"] == "password" and u["default_servings"] == 2
    assert u["diet_restrictions"] == [] and u["allergies"] == [] and u["created_at"] is not None
    assert "password_hash" not in u and "google_sub" not in u
    assert repo.get_user(u["id"])["email"] == "a@example.com"
    assert repo.get_user_by_email("a@example.com")["id"] == u["id"]
    assert repo.get_user_by_email("none@example.com") is None and repo.get_user(999999) is None


def test_credentials_include_the_hash_only_when_asked_for_them(repo):
    u = make_user(repo)
    cred = repo.get_credentials("a@example.com")
    assert cred["id"] == u["id"] and cred["provider"] == "password" and cred["password_hash"] == "$argon2id$x"
    assert repo.get_credentials("none@example.com") is None


def test_email_must_be_unique(repo):
    make_user(repo)
    with pytest.raises(repository.DuplicateEmailError):
        make_user(repo)
    with pytest.raises(repository.DuplicateEmailError):
        repo.create_user("a@example.com", "google", "구글", google_sub="s")


def test_google_user_has_no_password_and_keeps_its_subject(repo):
    u = repo.create_user("g@example.com", "google", "구글", google_sub="sub-9")
    cred = repo.get_credentials("g@example.com")
    assert u["provider"] == "google" and cred["password_hash"] is None and cred["google_sub"] == "sub-9"


def test_a_password_account_requires_a_hash(repo):
    with pytest.raises(Exception):
        repo.create_user("p@example.com", "password", "이름")        # 해시 없는 비밀번호 계정은 만들 수 없다


def test_update_profile_cleans_the_values(repo):
    u = make_user(repo)
    p = repo.update_profile(u["id"], "  새 이름  ", 99, ["채식", "채식", " ", "비건"], ["우유"] * 3 + ["견과류"])
    assert p["display_name"] == "새 이름" and p["default_servings"] == 10
    assert p["diet_restrictions"] == ["채식", "비건"] and p["allergies"] == ["우유", "견과류"]
    assert repo.get_user(u["id"])["allergies"] == ["우유", "견과류"]
    assert repo.update_profile(u["id"], "x", "엉뚱", [], [])["default_servings"] == 2
    assert repo.update_profile(987654, "x", 2, [], []) is None


def test_touch_login_records_the_time(repo):
    u = make_user(repo)
    assert u["last_login_at"] is None
    repo.touch_login(u["id"])
    assert repo.get_user(u["id"])["last_login_at"] is not None


# --- 로그인 세션 -----------------------------------------------------------------------------
def test_sessions_work_until_they_expire_and_can_be_deleted(repo):
    u = make_user(repo)
    soon = dt.datetime.now(UTC) + dt.timedelta(days=1)
    repo.create_session(u["id"], "hash-ok", soon)
    repo.create_session(u["id"], "hash-old", dt.datetime.now(UTC) - dt.timedelta(minutes=1))
    assert repo.user_for_session("hash-ok")["id"] == u["id"]
    assert repo.user_for_session("hash-old") is None and repo.user_for_session("nope") is None
    repo.purge_expired_sessions()
    repo.delete_session("hash-ok")
    assert repo.user_for_session("hash-ok") is None


def test_delete_sessions_of_one_user_leaves_the_others(repo):
    a, b = make_user(repo), make_user(repo, "b@example.com")
    future = dt.datetime.now(UTC) + dt.timedelta(days=1)
    repo.create_session(a["id"], "ha", future)
    repo.create_session(b["id"], "hb", future)
    repo.delete_sessions_of(a["id"])
    assert repo.user_for_session("ha") is None and repo.user_for_session("hb")["id"] == b["id"]


# --- 레시피 저장 -----------------------------------------------------------------------------
def test_save_and_list_newest_first_with_pantry_and_memo(repo):
    u = make_user(repo)
    first = repo.save_recipe(u["id"], sample_recipe("첫째"), ["달걀", "양배추"])
    second = repo.save_recipe(u["id"], sample_recipe("둘째", names=("당근", "양파")), ["당근"])
    rows = repo.list_recipes(u["id"])
    assert [r["title"] for r in rows] == ["둘째", "첫째"]
    assert rows[1]["id"] == first and rows[0]["id"] == second
    assert rows[1]["pantry"] == ["달걀", "양배추"] and rows[1]["memo"] == ""
    assert rows[1]["recipe"]["steps"] == ["볶는다."] and rows[1]["created_at"] is not None
    assert repo.count_recipes(u["id"]) == 2


def test_the_same_recipe_cannot_be_saved_twice_even_if_ingredients_are_reordered(repo):
    u = make_user(repo)
    repo.save_recipe(u["id"], sample_recipe("달걀 볶음", names=("달걀", "양배추")), [])
    for variant in (sample_recipe("달걀 볶음", names=("양배추", "달걀")), sample_recipe(" 달걀  볶음 ", names=("계란", "양배추"))):
        with pytest.raises(repository.DuplicateRecipeError):
            repo.save_recipe(u["id"], variant, [])
    repo.save_recipe(u["id"], sample_recipe("달걀 볶음", names=("달걀", "양배추", "당근")), [])   # 재료 구성이 다르면 다른 레시피
    assert repo.count_recipes(u["id"]) == 2


def test_two_users_may_save_the_same_recipe(repo):
    a, b = make_user(repo), make_user(repo, "b@example.com")
    repo.save_recipe(a["id"], sample_recipe(), [])
    repo.save_recipe(b["id"], sample_recipe(), [])
    assert repo.count_recipes(a["id"]) == repo.count_recipes(b["id"]) == 1


def test_recipe_fingerprints_tell_which_ones_are_saved(repo):
    u = make_user(repo)
    r = sample_recipe()
    assert repo.recipe_fingerprints(u["id"]) == set()
    repo.save_recipe(u["id"], r, [])
    assert repository.recipe_fingerprint(r) in repo.recipe_fingerprints(u["id"])


def test_the_save_limit_is_enforced(repo, monkeypatch):
    monkeypatch.setattr(repository, "MAX_RECIPES_PER_USER", 3)
    u = make_user(repo)
    for i in range(3):
        repo.save_recipe(u["id"], sample_recipe(f"레시피 {i}", names=(f"재료{i}",)), [])
    with pytest.raises(repository.RecipeLimitError) as e:
        repo.save_recipe(u["id"], sample_recipe("넷째", names=("재료9",)), [])
    assert "3개" in str(e.value) and repo.count_recipes(u["id"]) == 3


def test_filters_by_title_time_and_difficulty(repo):
    u = make_user(repo)
    repo.save_recipe(u["id"], sample_recipe("달걀 볶음", minutes=15, difficulty="easy", names=("달걀",)), [])
    repo.save_recipe(u["id"], sample_recipe("양배추 전", minutes=30, difficulty="medium", names=("양배추",)), [])
    repo.save_recipe(u["id"], sample_recipe("당근 스튜", minutes=50, difficulty="hard", names=("당근",)), [])
    titles = lambda **kw: sorted(r["title"] for r in repo.list_recipes(u["id"], **kw))  # noqa: E731
    assert titles(query="달걀") == ["달걀 볶음"] and titles(query="  양배 ") == ["양배추 전"] and titles(query="없음") == []
    assert titles(max_minutes=15) == ["달걀 볶음"] and titles(max_minutes=30) == ["달걀 볶음", "양배추 전"]
    assert titles(min_minutes=30) == ["당근 스튜", "양배추 전"]
    assert titles(difficulty="hard") == ["당근 스튜"] and titles(difficulty="medium", min_minutes=30) == ["양배추 전"]
    assert titles() == ["달걀 볶음", "당근 스튜", "양배추 전"]


def test_title_search_treats_percent_and_underscore_as_plain_text(repo):
    u = make_user(repo)
    repo.save_recipe(u["id"], sample_recipe("100% 달걀"), [])
    repo.save_recipe(u["id"], sample_recipe("일반 요리", names=("당근",)), [])
    assert [r["title"] for r in repo.list_recipes(u["id"], query="%")] == ["100% 달걀"]
    assert repo.list_recipes(u["id"], query="_") == []


def test_sql_looking_text_is_stored_as_plain_text(repo):
    u = make_user(repo)
    evil = "x'); drop table users; --"
    repo.save_recipe(u["id"], sample_recipe(evil), [evil])
    rows = repo.list_recipes(u["id"])
    assert rows[0]["title"] == evil and rows[0]["pantry"] == [evil]
    assert repo.get_user(u["id"]) is not None                          # 사용자 테이블이 멀쩡하다
    assert repo.get_user_by_email("' or '1'='1") is None


def test_memo_is_saved_and_trimmed(repo):
    u = make_user(repo)
    rid = repo.save_recipe(u["id"], sample_recipe(), [])
    assert repo.update_memo(u["id"], rid, "  맛있다  ") is True
    assert repo.list_recipes(u["id"])[0]["memo"] == "맛있다"
    repo.update_memo(u["id"], rid, "가" * 900)
    assert len(repo.list_recipes(u["id"])[0]["memo"]) == repository.MAX_MEMO_LEN


def test_delete_a_recipe(repo):
    u = make_user(repo)
    rid = repo.save_recipe(u["id"], sample_recipe(), [])
    assert repo.delete_recipe(u["id"], rid) is True
    assert repo.delete_recipe(u["id"], rid) is False and repo.count_recipes(u["id"]) == 0


# --- 다른 사용자의 데이터는 ID 를 알아도 건드릴 수 없다 ------------------------------------
def test_users_cannot_see_change_or_delete_each_others_recipes(repo):
    a, b = make_user(repo), make_user(repo, "b@example.com")
    rid = repo.save_recipe(a["id"], sample_recipe("A의 레시피"), [])
    assert repo.list_recipes(b["id"]) == [] and repo.count_recipes(b["id"]) == 0
    assert repo.recipe_fingerprints(b["id"]) == set()
    assert repo.update_memo(b["id"], rid, "해킹") is False             # 남의 레시피 메모를 못 바꾼다
    assert repo.delete_recipe(b["id"], rid) is False                   # 남의 레시피를 못 지운다
    mine = repo.list_recipes(a["id"])
    assert len(mine) == 1 and mine[0]["memo"] == ""


# --- 삭제 ----------------------------------------------------------------------------------
def test_deleting_a_user_removes_their_recipes_and_sessions_but_not_others(repo):
    a, b = make_user(repo), make_user(repo, "b@example.com")
    future = dt.datetime.now(UTC) + dt.timedelta(days=1)
    repo.save_recipe(a["id"], sample_recipe("A"), [])
    repo.save_recipe(b["id"], sample_recipe("B", names=("당근",)), [])
    repo.create_session(a["id"], "ha", future)
    repo.create_session(b["id"], "hb", future)
    assert repo.delete_user(a["id"]) is True
    assert repo.get_user(a["id"]) is None and repo.user_for_session("ha") is None
    assert [r["title"] for r in repo.list_recipes(b["id"])] == ["B"] and repo.user_for_session("hb") is not None
    assert repo.delete_user(a["id"]) is False


# --- 지문 ----------------------------------------------------------------------------------
def test_fingerprint_ignores_order_spacing_and_synonyms_but_not_content():
    base = repository.recipe_fingerprint(sample_recipe("달걀 볶음", names=("달걀", "양배추")))
    assert base == repository.recipe_fingerprint(sample_recipe("달걀볶음", names=("양배추", "달걀")))
    assert base == repository.recipe_fingerprint(sample_recipe("달걀 볶음", names=("계란", "양배추")))
    assert base != repository.recipe_fingerprint(sample_recipe("달걀 볶음", names=("달걀", "당근")))
    assert base != repository.recipe_fingerprint(sample_recipe("양배추 볶음", names=("달걀", "양배추")))


def test_filter_recipes_helper_handles_missing_minutes():
    rows = [{"title": "시간 없음", "recipe": {}}, {"title": "있음", "recipe": {"time_minutes": 20, "difficulty": "easy"}}]
    assert [r["title"] for r in repository.filter_recipes(rows)] == ["시간 없음", "있음"]
    assert [r["title"] for r in repository.filter_recipes(rows, max_minutes=30)] == ["있음"]
    assert [r["title"] for r in repository.filter_recipes(rows, min_minutes=10)] == ["있음"]


# --- 스키마 (실제 DB 에서만) ---------------------------------------------------------------
@pytest.mark.skipif(not LIVE, reason="RUN_LIVE_DB=1 일 때만 실제 DB 로 시험")
def test_schema_init_is_idempotent_and_row_level_security_is_on():
    database = db.Database(db.database_url())
    schema = "app_test_" + secrets.token_hex(4)
    repo = repository.PostgresRepository(database, schema=schema)
    try:
        repo.init()
        repository.PostgresRepository(database, schema=schema).init()   # 두 번째 실행도 오류 없이 끝난다
        rows = database.run("select c.relname, c.relrowsecurity from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                            "where n.nspname = %s and c.relkind = 'r' order by 1", (schema,))
        assert {r["relname"]: r["relrowsecurity"] for r in rows} == {"auth_sessions": True, "saved_recipes": True, "users": True}
        grants = database.run("select grantee from information_schema.role_table_grants where table_schema = %s "
                              "and grantee in ('anon', 'authenticated')", (schema,))
        assert grants == []                                             # 공개 API 역할에는 아무 권한도 없다
    finally:
        with database.transaction() as cur:
            cur.execute(f'drop schema if exists "{schema}" cascade')
        database.close()
