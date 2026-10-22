# 작성: 2026-10-22 21:30 KST
# 식재료 목록의 행 관리. 화면(Streamlit)과 무관한 순수 로직이라 단위 테스트가 가능하다.
#
# 행마다 고유 id 를 준다. 위젯 key 를 목록 순번으로 만들면 가운데 행을 지울 때
# 마지막 행이 지워진 것처럼 보이는 문제가 생기기 때문이다.


def name_key(row_id):
    return f"name_{row_id}"


def qty_key(row_id):
    return f"qty_{row_id}"


def make_rows(items, start_id=0):
    """인식 결과(items)를 id 가 붙은 행 목록으로 바꾼다. (행 목록, 다음 id)를 돌려준다."""
    rows = []
    next_id = start_id
    for item in items:
        rows.append(
            {
                "id": next_id,
                "name": item["name"],
                "quantity": item["quantity"],
                "confidence": item["confidence"],
            }
        )
        next_id += 1
    return rows, next_id


def blank_row(row_id):
    """사용자가 직접 추가하는 빈 행. 직접 입력한 재료라 신뢰도는 높음으로 둔다."""
    return {"id": row_id, "name": "", "quantity": "", "confidence": "high"}


def remove_row(rows, row_id):
    return [r for r in rows if r["id"] != row_id]


def collect_confirmed(rows, values):
    """화면에서 수정된 값(values: 위젯 key → 값)을 읽어 확정할 목록을 만든다. 이름이 빈 행은 버린다."""
    out = []
    for row in rows:
        name = str(values.get(name_key(row["id"]), row["name"]) or "").strip()
        if not name:
            continue
        quantity = str(values.get(qty_key(row["id"]), row["quantity"]) or "").strip()
        out.append({"name": name, "quantity": quantity, "confidence": row["confidence"]})
    return out
