"""赛段中立时段试算接口测试。夹具 client 见 conftest.py。"""
from __future__ import annotations

from datetime import datetime, timezone


def post(client, event_no, runner, station, occurred_at, corrects=None):
    body = {
        "event_no": event_no,
        "runner_id": runner,
        "station_seq": station,
        "occurred_at": occurred_at,
    }
    if corrects is not None:
        body["corrects"] = corrects
    return client.post("/api/checkins", json=body)


def neutralized(client, runner, windows):
    return client.post(
        f"/api/runners/{runner}/splits/neutralized",
        json={"windows": [{"start": s, "end": e} for s, e in windows]},
    )


def segment(data, frm, to):
    return next(
        s for s in data["segments"]
        if s["from_station"] == frm and s["to_station"] == to
    )


def utc(y, m, d, hh, mm, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


# 种子数据 R001：08:00 / 08:32 / 09:12 / 09:55 / 10:45 / 11:30，总用时 12600 秒
# 分段：1→2 1920，2→3 2400，3→4 2580，4→5 3000，5→6 2700

# ---------- 基本扣除 ----------

def test_neutralized_basic_deduction(client):
    r = neutralized(client, "R001", [("2026-09-25T08:10:00", "2026-09-25T08:20:00")])
    assert r.status_code == 200
    data = r.json()
    assert data["runner_id"] == "R001"
    assert data["station_count"] == 6
    assert data["complete"] is True

    s12 = segment(data, 1, 2)
    assert s12["status"] == "ok"
    assert s12["raw_seconds"] == 32 * 60
    assert s12["deducted_seconds"] == 10 * 60
    assert s12["net_seconds"] == 22 * 60
    # 其余分段未被覆盖，扣除为 0
    for frm in range(2, 6):
        seg = segment(data, frm, frm + 1)
        assert seg["deducted_seconds"] == 0
        assert seg["net_seconds"] == seg["raw_seconds"]
    # 全部分段有效，给出净总秒数
    assert data["net_total_seconds"] == 12600 - 600
    assert data["net_total"] == "3:20:00"


def test_neutralized_window_spanning_segments_no_double_count(client):
    # 时间窗 08:30–09:00 横跨分段 1→2 末尾与 2→3 开头，按分段裁剪扣除
    r = neutralized(client, "R001", [("2026-09-25T08:30:00", "2026-09-25T09:00:00")])
    assert r.status_code == 200
    data = r.json()
    assert segment(data, 1, 2)["deducted_seconds"] == 2 * 60      # 08:30–08:32
    assert segment(data, 2, 3)["deducted_seconds"] == 28 * 60     # 08:32–09:00
    # 跨段窗口被逐段裁剪，合计恰好等于窗口长度，不重复扣秒
    assert data["net_total_seconds"] == 12600 - 30 * 60


def test_neutralized_deduction_capped_by_segment(client):
    # 时间窗完整覆盖分段 1→2 并延伸进 2→3：净秒数不为负
    r = neutralized(client, "R001", [("2026-09-25T07:00:00", "2026-09-25T08:40:00")])
    assert r.status_code == 200
    data = r.json()
    s12 = segment(data, 1, 2)
    assert s12["deducted_seconds"] == s12["raw_seconds"]
    assert s12["net_seconds"] == 0
    assert segment(data, 2, 3)["deducted_seconds"] == 8 * 60  # 08:32–08:40
    assert data["net_total_seconds"] == 12600 - (32 + 8) * 60


def test_neutralized_window_outside_race_deducts_nothing(client):
    r = neutralized(client, "R001", [("2026-09-26T08:00:00", "2026-09-26T09:00:00")])
    assert r.status_code == 200
    data = r.json()
    assert all(s["deducted_seconds"] == 0 for s in data["segments"])
    assert data["net_total_seconds"] == 12600


# ---------- 时间窗归一化与合并 ----------

def test_neutralized_windows_normalized_to_utc(client):
    # +08:00 的 16:10–16:20 即 UTC 08:10–08:20
    r = neutralized(
        client, "R001",
        [("2026-09-25T16:10:00+08:00", "2026-09-25T16:20:00+08:00")],
    )
    assert r.status_code == 200
    data = r.json()
    assert segment(data, 1, 2)["deducted_seconds"] == 10 * 60
    (w,) = data["windows"]
    assert datetime.fromisoformat(w["start"]) == utc(2026, 9, 25, 8, 10)
    assert datetime.fromisoformat(w["end"]) == utc(2026, 9, 25, 8, 20)


def test_neutralized_merges_overlapping_and_touching_windows(client):
    # 08:10–08:20 与 08:15–08:25 重叠、与 08:25–08:30 相接：合并为 08:10–08:30
    r = neutralized(
        client, "R001",
        [
            ("2026-09-25T08:25:00", "2026-09-25T08:30:00"),
            ("2026-09-25T08:10:00", "2026-09-25T08:20:00"),
            ("2026-09-25T08:15:00", "2026-09-25T08:25:00"),
        ],
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["windows"]) == 1
    (w,) = data["windows"]
    assert datetime.fromisoformat(w["start"]) == utc(2026, 9, 25, 8, 10)
    assert datetime.fromisoformat(w["end"]) == utc(2026, 9, 25, 8, 30)
    # 重叠部分只扣一次
    assert segment(data, 1, 2)["deducted_seconds"] == 20 * 60
    assert data["net_total_seconds"] == 12600 - 20 * 60


# ---------- 校验 ----------

def test_neutralized_rejects_end_not_after_start(client):
    # 终点早于起点
    r = neutralized(client, "R001", [("2026-09-25T08:20:00", "2026-09-25T08:10:00")])
    assert r.status_code == 422
    # 终点等于起点
    r = neutralized(client, "R001", [("2026-09-25T08:10:00", "2026-09-25T08:10:00")])
    assert r.status_code == 422
    # 空窗口列表
    assert neutralized(client, "R001", []).status_code == 422


def test_neutralized_unknown_runner_404(client):
    r = neutralized(client, "NOBODY", [("2026-09-25T08:00:00", "2026-09-25T09:00:00")])
    assert r.status_code == 404


# ---------- 待定分段保持待定 ----------

def test_neutralized_missing_station_segments_stay_pending(client):
    # R003 缺第 4 站：分段 3→4、4→5 待定
    r = neutralized(client, "R003", [("2026-09-25T08:20:00", "2026-09-25T08:30:00")])
    assert r.status_code == 200
    data = r.json()
    assert data["complete"] is False
    assert data["net_total_seconds"] is None
    assert data["net_total"] is None

    s12 = segment(data, 1, 2)
    assert s12["status"] == "ok"
    assert s12["raw_seconds"] == 40 * 60
    assert s12["deducted_seconds"] == 10 * 60
    assert s12["net_seconds"] == 30 * 60

    for frm, to in ((3, 4), (4, 5)):
        seg = segment(data, frm, to)
        assert seg["status"] == "pending"
        assert "站点 4" in seg["reason"]
        assert seg["raw_seconds"] is None
        assert seg["deducted_seconds"] is None
        assert seg["net_seconds"] is None


def test_neutralized_time_regression_segment_stays_pending(client):
    # R006 第 3 站时间早于第 2 站：分段 2→3 待定
    r = neutralized(client, "R006", [("2026-09-25T08:30:00", "2026-09-25T08:40:00")])
    assert r.status_code == 200
    data = r.json()
    assert data["complete"] is False
    assert data["net_total_seconds"] is None

    s12 = segment(data, 1, 2)
    assert s12["raw_seconds"] == 70 * 60
    assert s12["deducted_seconds"] == 10 * 60
    assert s12["net_seconds"] == 60 * 60

    s23 = segment(data, 2, 3)
    assert s23["status"] == "pending"
    assert "时间倒退" in s23["reason"]
    assert s23["raw_seconds"] is None
    assert s23["deducted_seconds"] is None
    assert s23["net_seconds"] is None


# ---------- 无副作用、反映最新数据 ----------

def test_neutralized_has_no_side_effects(client):
    pub = client.post("/api/publications").json()
    before_splits = client.get("/api/runners/R001/splits").json()
    before_checkins = client.get("/api/checkins").json()

    r = neutralized(client, "R001", [("2026-09-25T08:10:00", "2026-09-25T08:20:00")])
    assert r.status_code == 200

    # 实时成绩、打卡记录与已发布版本均不受影响
    assert client.get("/api/runners/R001/splits").json() == before_splits
    assert client.get("/api/checkins").json() == before_checkins
    assert client.get("/api/publications/latest").json() == pub


def test_neutralized_reflects_latest_checkins(client):
    for k in range(1, 7):
        assert post(
            client, f"N-{k}", "TN1", k,
            f"2026-09-25T{8 + (k - 1) // 2:02d}:{(k - 1) % 2 * 30:02d}:00",
        ).status_code == 201
    windows = [("2026-09-25T08:10:00", "2026-09-25T08:20:00")]

    # 初始：分段 1→2 为 08:00–08:30，扣除 600 秒
    data = neutralized(client, "TN1", windows).json()
    assert segment(data, 1, 2)["raw_seconds"] == 30 * 60
    assert segment(data, 1, 2)["deducted_seconds"] == 10 * 60
    assert data["net_total_seconds"] == 5 * 30 * 60 - 600

    # 更正第 1 站打卡后重新请求：按最新数据重算
    post(client, "N-1b", "TN1", 1, "2026-09-25T08:05:00", corrects="N-1")
    data = neutralized(client, "TN1", windows).json()
    assert segment(data, 1, 2)["raw_seconds"] == 25 * 60
    assert segment(data, 1, 2)["deducted_seconds"] == 10 * 60
    assert data["net_total_seconds"] == (25 + 4 * 30) * 60 - 600

    # 撤销第 2 站后：分段 1→2、2→3 待定，净总秒数不再给出
    client.post("/api/checkins/N-2/revoke")
    data = neutralized(client, "TN1", windows).json()
    assert data["complete"] is False
    assert data["net_total_seconds"] is None
    assert segment(data, 1, 2)["status"] == "pending"
    assert segment(data, 2, 3)["status"] == "pending"

    # 补传第 2 站后恢复有效，仍按最新打卡扣除
    post(client, "N-2b", "TN1", 2, "2026-09-25T08:35:00")
    data = neutralized(client, "TN1", windows).json()
    assert data["complete"] is True
    assert segment(data, 1, 2)["raw_seconds"] == 30 * 60
    assert segment(data, 1, 2)["deducted_seconds"] == 10 * 60
    assert data["net_total_seconds"] == (30 + 25 + 3 * 30) * 60 - 600
