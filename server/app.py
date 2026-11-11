# -*- coding: utf-8 -*-
"""冰衡 / 知行 —— 后端服务（FastAPI + SQLite）

一个进程同时服务两个产品：
  /bingheng       冰衡（短道速滑训练决策）
  /zhixing        知行（儿童注意力与行为筛查）
  /api/bh/*       冰衡接口
  /api/zx/*       知行接口
  /docs           自动生成的接口文档

启动：python products/server/app.py
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB = HERE / "app.db"

app = FastAPI(title="冰衡 · 知行 API", version="1.0",
              description="两个产品的统一后端。数据本地 SQLite，不出网。")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])


# ---------------------------------------------------------------- 数据库
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def rows(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    with db() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict[str, Any] | None:
    r = rows(sql, args)
    return r[0] if r else None


# ---------------------------------------------------------------- 静态页
@app.get("/", include_in_schema=False)
def index():
    return JSONResponse({
        "name": "冰衡 / 知行 API",
        "pages": {"冰衡": "/bingheng", "知行": "/zhixing"},
        "docs": "/docs",
    })


@app.get("/bingheng", include_in_schema=False)
def page_bh():
    return FileResponse(ROOT / "bingheng.html", media_type="text/html")


@app.get("/zhixing", include_in_schema=False)
def page_zx():
    return FileResponse(ROOT / "zhixing.html", media_type="text/html")


# ================================================================ 冰衡
class DecisionIn(BaseModel):
    athlete_id: str
    level: str                       # green / yellow / red / under
    suggested_pct: int | None = None
    reason: str | None = None
    decided_by: str = "coach"
    note: str | None = None


@app.get("/api/bh/today")
def bh_today(day: str | None = Query(None, description="基准日 YYYY-MM-DD")):
    """今日决策卡：三档统计 + 排序后的名单。"""
    base = day or (one("SELECT MAX(d) AS d FROM daily_metrics") or {}).get("d")
    if not base:
        return {"date": None, "cards": {}, "athletes": [], "note": "暂无数据"}

    items = rows("""
        SELECT m.athlete_id, a.name, a.initial, a.group_name, a.age, a.event,
               m.fi, m.acwr, m.hrv_delta, m.rhr_delta,
               m.level, m.reason, m.suggested_pct, m.stale, m.coverage
        FROM daily_metrics m JOIN athletes a ON a.id = m.athlete_id
        WHERE m.d = ?
        ORDER BY CASE m.level
            WHEN 'red' THEN 0 WHEN 'yellow' THEN 1 WHEN 'under' THEN 2
            WHEN 'unknown' THEN 3 ELSE 4 END, m.fi DESC
    """, (base,))

    cards = {"green": 0, "yellow": 0, "red": 0, "under": 0, "unknown": 0}
    for it in items:
        cards[it["level"]] = cards.get(it["level"], 0) + 1

    # 全队平均疲劳指数 + 近 7 日负荷
    avg = one("SELECT ROUND(AVG(fi),0) AS v FROM daily_metrics WHERE d=?", (base,))
    load7 = one("""SELECT ROUND(SUM(load),0) AS v FROM sessions
                   WHERE d > date(?, '-7 day') AND d <= ?""", (base, base))
    return {
        "date": base,
        "cards": cards,
        "avg_fi": int(avg["v"] or 0),
        "week_load": int(load7["v"] or 0),
        "athletes": items,
    }


@app.get("/api/bh/weekly")
def bh_weekly(days: int = 28):
    """周负荷：ACWR 曲线数据 + 异常名单 + 训练构成。"""
    base = (one("SELECT MAX(d) AS d FROM daily_metrics") or {}).get("d")
    if not base:
        return {"days": [], "acwr": [], "alerts": [], "compose": []}

    start = (datetime.fromisoformat(base) - timedelta(days=days - 1)).date().isoformat()
    curve = rows("""
        SELECT d, ROUND(AVG(acwr),3) AS acwr FROM daily_metrics
        WHERE d BETWEEN ? AND ? GROUP BY d ORDER BY d
    """, (start, base))

    alerts = rows("""
        SELECT m.athlete_id, a.name, a.initial, m.acwr, m.monotony, m.level, m.reason
        FROM daily_metrics m JOIN athletes a ON a.id = m.athlete_id
        WHERE m.d = ? AND m.level IN ('red','yellow')
        ORDER BY m.acwr DESC LIMIT 10
    """, (base,))

    compose = rows("""
        SELECT type, ROUND(SUM(load),0) AS load FROM sessions
        WHERE d BETWEEN ? AND ? GROUP BY type ORDER BY load DESC
    """, (start, base))
    total = sum(c["load"] or 0 for c in compose) or 1
    for c in compose:
        c["pct"] = round((c["load"] or 0) / total * 100)

    return {"anchor": base, "days": [c["d"] for c in curve],
            "acwr": [c["acwr"] for c in curve], "alerts": alerts, "compose": compose}


@app.get("/api/bh/athlete/{aid}")
def bh_athlete(aid: str, days: int = 21):
    """个体负荷—恢复曲线 + 指标卡 + 判断依据。"""
    a = one("SELECT * FROM athletes WHERE id=?", (aid,))
    if not a:
        raise HTTPException(404, f"运动员 {aid} 不存在")

    base = (one("SELECT MAX(d) AS d FROM daily_metrics WHERE athlete_id=?", (aid,)) or {}).get("d")
    if not base:
        raise HTTPException(404, "该运动员暂无数据")

    start = (datetime.fromisoformat(base) - timedelta(days=days - 1)).date().isoformat()
    series = rows("""
        SELECT d, load, recovery FROM daily_metrics
        WHERE athlete_id=? AND d BETWEEN ? AND ? ORDER BY d
    """, (aid, start, base))

    m = one("SELECT * FROM daily_metrics WHERE athlete_id=? AND d=?", (aid, base))
    return {
        "athlete": a, "anchor": base,
        "series": series,
        "metrics": {
            "fi": m["fi"], "acwr": m["acwr"], "hrv": m["hrv"],
            "hrv_delta": m["hrv_delta"], "rhr": m["rhr"],
            "rhr_delta": m["rhr_delta"], "tli": m["tli"],
            "level": m["level"], "reason": m["reason"],
        },
    }


@app.post("/api/bh/decisions")
def bh_decide(payload: DecisionIn):
    """教练决策留痕：谁、何时、依据什么、决定什么。"""
    base = (one("SELECT MAX(d) AS d FROM daily_metrics") or {}).get("d")
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO decisions(athlete_id, d, level, suggested_pct, reason,
                                  decided_by, note, created_at)
            VALUES(?,?,?,?,?,?,?,?)
        """, (payload.athlete_id, base, payload.level, payload.suggested_pct,
              payload.reason, payload.decided_by, payload.note,
              datetime.now().isoformat(timespec="seconds")))
        return {"ok": True, "id": cur.lastrowid}


@app.get("/api/bh/decisions")
def bh_decisions(limit: int = 20):
    return {"items": rows("""
        SELECT d.*, a.name FROM decisions d LEFT JOIN athletes a ON a.id=d.athlete_id
        ORDER BY d.id DESC LIMIT ?
    """, (limit,))}


@app.get("/api/bh/taper")
def bh_taper():
    """赛前减量计划。"""
    ev = one("SELECT * FROM events ORDER BY d LIMIT 1")
    if not ev:
        raise HTTPException(404, "暂无赛事")
    base = (one("SELECT MAX(d) AS d FROM daily_metrics") or {}).get("d")
    days_left = (datetime.fromisoformat(ev["d"]).date()
                 - datetime.fromisoformat(base).date()).days
    plan = rows("SELECT d, target_pct FROM taper_plans WHERE event_id=? ORDER BY d", (ev["id"],))
    return {"event": ev, "days_left": max(days_left, 0), "plan": plan}


@app.get("/api/bh/devices/{device_id}")
def bh_device(device_id: str):
    d = one("SELECT * FROM devices WHERE device_id=?", (device_id,))
    if not d:
        raise HTTPException(404, "设备不存在")
    return d


# ================================================================ 知行
class FollowupIn(BaseModel):
    student_id: str
    sleep: str | None = None
    focus: str | None = None
    mood: str | None = None
    visit: str | None = None


@app.get("/api/zx/class/{class_id}")
def zx_class(class_id: str):
    """班级看板：KPI + 名单。"""
    st = rows("""
        SELECT s.id, s.name, s.initial, s.level, s.behavior, s.tested, s.trend
        FROM students s WHERE s.class_id=? ORDER BY
          CASE s.level WHEN 'risk' THEN 0 WHEN 'amber' THEN 1 WHEN 'mute' THEN 3 ELSE 2 END
    """, (class_id,))
    if not st:
        raise HTTPException(404, "班级不存在")

    for s in st:
        s["trend"] = [int(x) for x in (s["trend"] or "").split(",") if x != ""]
        s["behaviors"] = s["behavior"]
    kpi = {
        "total": len(st),
        "done": sum(1 for s in st if s["tested"]),
        "watch": sum(1 for s in st if s["level"] == "amber"),
        "refer": sum(1 for s in st if s["level"] == "risk"),
    }
    return {"class_id": class_id, "kpi": kpi, "students": st}


@app.get("/api/zx/student/{sid}")
def zx_student(sid: str):
    """学生详情：五维剖面 + 四项指标 + 建议。"""
    s = one("SELECT * FROM students WHERE id=?", (sid,))
    if not s:
        raise HTTPException(404, "学生不存在")
    dims = rows("SELECT dim, pct FROM profiles WHERE student_id=? ORDER BY ord", (sid,))
    metrics = rows("""SELECT key, label, value, unit, pct FROM metrics
                      WHERE student_id=? ORDER BY ord""", (sid,))
    ref = one("SELECT * FROM referrals WHERE student_id=?", (sid,))
    return {"student": s, "dimensions": dims, "metrics": metrics, "referral": ref}


class ReferralIn(BaseModel):
    student_id: str
    level: str
    reason: str | None = None
    created_by: str = "teacher"


@app.post("/api/zx/referrals")
def zx_create_referral(payload: ReferralIn):
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO referrals(student_id, level, reason, created_by, created_at)
            VALUES(?,?,?,?,?)
        """, (payload.student_id, payload.level, payload.reason,
              payload.created_by, datetime.now().isoformat(timespec="seconds")))
        return {"ok": True, "id": cur.lastrowid}


@app.post("/api/zx/followups")
def zx_followup(payload: FollowupIn):
    with db() as conn:
        conn.execute("""
            INSERT INTO followups(student_id, sleep, focus, mood, visit, created_at)
            VALUES(?,?,?,?,?,?)
        """, (payload.student_id, payload.sleep, payload.focus, payload.mood,
              payload.visit, datetime.now().isoformat(timespec="seconds")))
        return {"ok": True}


@app.get("/api/zx/camera/{device_id}")
def zx_camera(device_id: str):
    d = one("SELECT * FROM cameras WHERE device_id=?", (device_id,))
    if not d:
        raise HTTPException(404, "设备不存在")
    logs = rows("SELECT ts, event FROM camera_logs WHERE device_id=? ORDER BY ts", (device_id,))
    return {"device": d, "logs": logs}


class PrivacyIn(BaseModel):
    device_id: str
    on: bool


@app.post("/api/zx/camera/privacy")
def zx_privacy(payload: PrivacyIn):
    with db() as conn:
        conn.execute("UPDATE cameras SET collecting=? WHERE device_id=?",
                     (1 if payload.on else 0, payload.device_id))
        conn.execute("INSERT INTO camera_logs(device_id, ts, event) VALUES(?,?,?)",
                     (payload.device_id, datetime.now().strftime("%H:%M"),
                      "恢复采集" if payload.on else "滑片遮挡 · 断采"))
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "db": DB.exists(),
            "athletes": (one("SELECT COUNT(*) c FROM athletes") or {}).get("c"),
            "students": (one("SELECT COUNT(*) c FROM students") or {}).get("c")}


if __name__ == "__main__":
    import uvicorn
    print("冰衡 → http://127.0.0.1:8770/bingheng")
    print("知行 → http://127.0.0.1:8770/zhixing")
    print("接口 → http://127.0.0.1:8770/docs")
    uvicorn.run(app, host="127.0.0.1", port=8770, log_level="warning")
