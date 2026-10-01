from app.models.models import Segment, Vendor


def _coords(payload):
    return {p["vendor_name"]: (p["start_m"], p["end_m"]) for p in payload["placements"]}


def test_keep_placed_rejected_without_successful_run(client, seeded):
    sid = seeded["segment_id"]
    r = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true")
    assert r.status_code == 409
    # 禁止半成功：不落任何运行，图与放不下口径不变
    assert client.get(f"/api/allocate/runs?segment_id={sid}").json() == []


def test_seed_scenario_narrow_unplaced_then_keep_placed(client, seeded, db_session):
    sid = seeded["segment_id"]
    r1 = client.post(f"/api/allocate/run?segment_id={sid}").json()
    assert r1["keep_placed"] is False
    placed1 = _coords(r1)
    assert "巨型舞台车" not in placed1
    assert any(x["vendor_name"] == "巨型舞台车" for x in r1["rejected"])

    # 把未落宽摊改窄，再勾保留重跑
    stage = db_session.query(Vendor).filter_by(name="巨型舞台车").one()
    stage.stall_width_m = 4.5
    db_session.commit()
    r2 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true").json()
    assert r2["keep_placed"] is True
    placed2 = {p["vendor_name"]: p for p in r2["placements"]}

    # 已落坐标保持，且标记为锁区
    for name, (start, end) in placed1.items():
        assert (placed2[name]["start_m"], placed2[name]["end_m"]) == (start, end)
        assert placed2[name]["locked"] is True
    # 改窄后的宽摊落入剩余空档，不侵入任何锁区
    stage2 = placed2["巨型舞台车"]
    assert stage2["locked"] is False
    assert stage2["end_m"] - stage2["start_m"] == 4.5
    for name, (start, end) in placed1.items():
        assert stage2["end_m"] <= start or stage2["start_m"] >= end
    # 放不下不得再点名已锁成功摊为被挤掉
    assert r2["rejected"] == []
    # 仅剩余空档变化
    assert r2["free_spans"] != r1["free_spans"]


def test_lock_conflict_and_no_fit_reasons_via_api(client, seeded, db_session):
    sid = seeded["segment_id"]
    r1 = client.post(f"/api/allocate/run?segment_id={sid}").json()
    day_id = db_session.get(Segment, sid).market_day_id
    db_session.add(Vendor(market_day_id=day_id, name="流动大篷车", stall_width_m=7.0, priority=9))
    db_session.add(Vendor(market_day_id=day_id, name="超宽花车", stall_width_m=40.0, priority=9))
    db_session.commit()
    r2 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true").json()
    reasons = {x["vendor_name"]: x["reason"] for x in r2["rejected"]}
    # 低优先宽摊顶不掉已锁摊：锁区冲突，且不得改写成空档不够
    assert "锁区冲突" in reasons["流动大篷车"]
    assert "空档" not in reasons["流动大篷车"]
    # 真放不下的仍是空档不够
    assert reasons["超宽花车"] == "无连续空档可放下且不跨越挡柱"
    # 已锁摊起止未被静默挪动
    assert _coords(r2) == _coords(r1)


def test_consecutive_keep_placed_runs_do_not_drift(client, seeded):
    sid = seeded["segment_id"]
    client.post(f"/api/allocate/run?segment_id={sid}")
    r2 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true").json()
    r3 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true").json()
    assert _coords(r3) == _coords(r2)
    assert all(p["locked"] for p in r3["placements"])


def test_keep_true_and_false_results_do_not_share_cache(client, seeded):
    sid = seeded["segment_id"]
    r1 = client.post(f"/api/allocate/run?segment_id={sid}").json()
    r2 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true").json()
    assert any(p["locked"] for p in r2["placements"])

    # 勾假重跑：整段重算，勾真跑出的色块不再被当成锁区，与绿仓一致
    r3 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=false").json()
    assert r3["keep_placed"] is False
    assert all(not p["locked"] for p in r3["placements"])
    assert _coords(r3) == _coords(r1)

    # 旧运行点回不污染：保留运行仍带锁区，非保留运行仍无锁区
    r2_again = client.get(f"/api/allocate/runs/{r2['id']}").json()
    assert r2_again["keep_placed"] is True
    assert any(p["locked"] for p in r2_again["placements"])
    r1_again = client.get(f"/api/allocate/runs/{r1['id']}").json()
    assert all(not p["locked"] for p in r1_again["placements"])

    # 再勾真：锁区来自最近一次成功运行（r3），不是勾真那次的缓存
    r4 = client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true").json()
    assert all(p["locked"] for p in r4["placements"])
    assert _coords(r4) == _coords(r3)


def test_runs_list_and_detail_share_same_data(client, seeded):
    sid = seeded["segment_id"]
    client.post(f"/api/allocate/run?segment_id={sid}")
    client.post(f"/api/allocate/run?segment_id={sid}&keep_placed=true")
    runs = client.get(f"/api/allocate/runs?segment_id={sid}").json()
    assert len(runs) == 2
    assert runs[0]["id"] > runs[1]["id"]  # 最新在前
    keep = runs[0]
    assert keep["keep_placed"] is True
    assert keep["locked"] == keep["placed"]  # 第二轮落摊全部来自锁区
    detail = client.get(f"/api/allocate/runs/{keep['id']}").json()
    assert detail["keep_placed"] is True
    assert len(detail["placements"]) == keep["placed"]
    assert sum(1 for p in detail["placements"] if p["locked"]) == keep["locked"]
    # latest 与最近一次运行同口径
    latest = client.get(f"/api/allocate/latest?segment_id={sid}").json()
    assert latest["id"] == keep["id"]
    assert latest["keep_placed"] is True
    assert client.get("/api/allocate/runs/99999").status_code == 404
