# -*- coding: utf-8 -*-
"""建库与灌数据。运行：python products/server/seed.py

数据是仿真的，但结构、字段与 PRD 第 7 节 / 第 5 节完全一致，
换成真实数据时只替换本文件，接口与前端都不用改。
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE / "app.db"

random.seed(20261107)

START = date(2026, 9, 8)
DAYS = 60
EVENT = {"id": "prov2026", "name": "省锦标赛", "d": "2026-11-17", "place": "哈尔滨"}

SCHEMA = """
DROP TABLE IF EXISTS athletes;
DROP TABLE IF EXISTS sessions;
DROP TABLE IF EXISTS daily_metrics;
DROP TABLE IF EXISTS decisions;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS taper_plans;
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS profiles;
DROP TABLE IF EXISTS metrics;
DROP TABLE IF EXISTS referrals;
DROP TABLE IF EXISTS followups;
DROP TABLE IF EXISTS cameras;
DROP TABLE IF EXISTS camera_logs;

CREATE TABLE athletes(
  id TEXT PRIMARY KEY, name TEXT, initial TEXT, group_name TEXT,
  age INT, sex TEXT, event TEXT, consent INT DEFAULT 1);

CREATE TABLE sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id TEXT, d TEXT,
  type TEXT, duration INT, srpe INT, load REAL);

CREATE TABLE daily_metrics(
  athlete_id TEXT, d TEXT,
  fi INT, acwr REAL, monotony REAL, strain REAL,
  hrv REAL, hrv_delta REAL, rhr REAL, rhr_delta REAL, tli INT,
  load REAL, recovery REAL,
  level TEXT, reason TEXT, suggested_pct INT,
  stale INT DEFAULT 0, coverage INT DEFAULT 28,
  PRIMARY KEY(athlete_id, d));

CREATE TABLE decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT, athlete_id TEXT, d TEXT,
  level TEXT, suggested_pct INT, reason TEXT, decided_by TEXT,
  note TEXT, created_at TEXT);

CREATE TABLE events(id TEXT PRIMARY KEY, name TEXT, d TEXT, place TEXT);
CREATE TABLE taper_plans(event_id TEXT, d TEXT, target_pct INT);

CREATE TABLE devices(
  device_id TEXT PRIMARY KEY, athlete_id TEXT, battery INT,
  sample_rate INT, synced INT, last_sync TEXT);

CREATE TABLE students(
  id TEXT PRIMARY KEY, class_id TEXT, name TEXT, initial TEXT,
  level TEXT, behavior TEXT, tested INT, trend TEXT, consent INT);

CREATE TABLE profiles(student_id TEXT, dim TEXT, pct INT, ord INT);
CREATE TABLE metrics(student_id TEXT, key TEXT, label TEXT, value REAL,
                     unit TEXT, pct INT, ord INT);
CREATE TABLE referrals(id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT,
  level TEXT, reason TEXT, created_by TEXT, created_at TEXT);
CREATE TABLE followups(id INTEGER PRIMARY KEY AUTOINCREMENT, student_id TEXT,
  sleep TEXT, focus TEXT, mood TEXT, visit TEXT, created_at TEXT);
CREATE TABLE cameras(device_id TEXT PRIMARY KEY, room TEXT, online INT, collecting INT,
  angle INT, video_retention TEXT, face_feature TEXT);
CREATE TABLE camera_logs(device_id TEXT, ts TEXT, event TEXT);
"""

SURNAME = list("王李张刘陈杨黄赵吴周徐孙马朱胡郭何高林罗郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘于蒋蔡余杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤")


def norm(x, lo, hi):
    return max(lo, min(hi, x))


def build():
    if DB.exists():
        DB.unlink()
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)

    # ---------------- 冰衡：25 名运动员 ----------------
    conn.execute("INSERT INTO events VALUES(?,?,?,?)",
                 (EVENT["id"], EVENT["name"], EVENT["d"], EVENT["place"]))

    # 减量计划：D-10 ~ D-0
    plan = [100, 95, 88, 80, 75, 70, 65, 62, 60, 55, 0]
    ev = datetime.fromisoformat(EVENT["d"]).date()
    for i, pct in enumerate(plan):
        d = (ev - timedelta(days=10 - i)).isoformat()
        conn.execute("INSERT INTO taper_plans VALUES(?,?,?)", (EVENT["id"], d, pct))

    athletes = []
    for i in range(25):
        aid = f"A{i+1:03d}"
        initial = SURNAME[i % len(SURNAME)]
        name = f"{initial}某"
        grp = "重点班" if i < 12 else "普通班"
        age = 14 + i % 5
        sex = "F" if i % 3 else "M"
        evt = ["500m", "1000m", "1500m"][i % 3]
        athletes.append((aid, name, initial, grp, age, sex, evt))
        conn.execute("INSERT INTO athletes VALUES(?,?,?,?,?,?,?,1)", athletes[-1])

    for ai, (aid, name, initial, grp, age, sex, evt) in enumerate(athletes):
        base_k = random.uniform(11.0, 16.0)
        k4 = random.uniform(0.15, 0.22)
        hrv0 = random.uniform(48, 68)
        rhr0 = random.uniform(50, 60)
        fi = 32.0
        load_hist: list[float] = []

        for t in range(DAYS):
            d = START + timedelta(days=t)
            wd = d.weekday()
            week = t // 7
            # 三周一小周期；最后两周进减量
            if wd == 6:
                minutes, srpe, typ = 0, 0, "恢复"
            else:
                base = 110
                if wd in (2, 5):
                    base = 150
                if (week + 1) % 3 == 2:
                    base = 80
                # 赛前两周减量
                # 赛前减量是 C3 页面的独立计划，不回溯改写历史负荷
                # 少数运动员最后一周突击加练（真实世界里常见），自然产生超阈
                if t >= DAYS - 5 and ai % 5 == 0:
                    base = int(base * 2.0)
                minutes = max(0, int(base * random.uniform(.9, 1.1)))
                srpe = random.randint(4, 8) if minutes else 0
                typ = ["冰上专项", "陆地体能", "速度课"][t % 3] if wd in (1, 3, 5) else "冰上专项"
            load = minutes * srpe * 0.9
            if minutes:
                conn.execute(
                    "INSERT INTO sessions(athlete_id,d,type,duration,srpe,load) "
                    "VALUES(?,?,?,?,?,?)", (aid, d.isoformat(), typ, minutes, srpe, round(load, 1)))

            # 疲劳状态：负荷驱动 + 自放大 + 恢复
            grow = base_k * (load / 700) * math.exp(0.022 * fi) * (1 - fi / 100)
            fi = norm(fi + grow - k4 * fi, 4, 96)

            load_hist.append(load)
            acute = sum(load_hist[-7:]) / max(len(load_hist[-7:]), 1)
            chronic = sum(load_hist[-28:]) / max(len(load_hist[-28:]), 1)
            if chronic < 30:
                acwr = 1.0
            else:
                acwr = norm(acute / chronic + random.gauss(0, .05), 0.45, 2.1)
            monotony = norm(1.5 + random.gauss(0, .3) + (0.45 if (week + 1) % 3 == 2 else 0), 0.8, 3.2)
            strain = round(load * monotony / 100, 1)

            hrv = norm(hrv0 * (1 - 0.0035 * fi) + random.gauss(0, 1.8), 20, 90)
            rhr = norm(rhr0 + 0.10 * fi + random.gauss(0, 1.2), 40, 90)
            tli = int(norm(70 + 0.25 * fi + random.gauss(0, 6), 20, 99))

            hrv_d = round((hrv / hrv0 - 1) * 100, 1)
            rhr_d = round(rhr - rhr0, 0)

            # 分级（多指标融合，单一指标不直接判红）
            score = 0.0
            score += norm((acwr - 0.90) / 0.70, 0, 1) * 45
            score += norm((monotony - 1.40) / 1.20, 0, 1) * 15
            score += norm((fi - 30) / 55, 0, 1) * 25
            score += norm((rhr_d) / 10, 0, 1) * 15
            fi_show = int(round(score)) if t > 13 else int(round(fi * 0.6))

            coverage = min(28, t + 1)
            stale = 1 if (ai % 11 == 0 and wd == 0) else 0

            if coverage < 10:
                level, reason, pct = "unknown", f"慢性负荷历史仅 {coverage} 天（<10），暂不判定", 100
            elif stale:
                level, reason, pct = "unknown", "昨日未打卡，数据缺失，建议补录晨脉", 100
            elif fi_show >= 70 or acwr >= 1.5:
                level, reason = "red", f"疲劳指数 {fi_show}/100 · ACWR {acwr:.2f}"
                pct = 0
            elif fi_show >= 50 or acwr >= 1.3 or monotony >= 2.0:
                level = "yellow"
                if acwr >= 1.3:
                    reason = f"ACWR {acwr:.2f} 进入超阈区（1.3–1.5）"
                elif monotony >= 2.0:
                    reason = f"单调性 {monotony:.1f} ≥ 2.0，训练结构单一"
                else:
                    reason = f"疲劳指数 {fi_show}/100，建议降负荷"
                pct = 60 if fi_show >= 60 else 70
            elif acwr < 0.8:
                level, reason, pct = "under", f"ACWR {acwr:.2f} 低于 0.8，负荷偏低，可适度加量", 110
            else:
                level, reason, pct = "green", f"ACWR {acwr:.2f} 在安全区 0.8–1.3", 100

            recovery = norm(100 - fi * 0.55 + random.gauss(0, 4), 5, 100)

            conn.execute("""
                INSERT INTO daily_metrics(athlete_id,d,fi,acwr,monotony,strain,hrv,hrv_delta,
                    rhr,rhr_delta,tli,load,recovery,level,reason,suggested_pct,stale,coverage)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (aid, d.isoformat(), fi_show, round(acwr, 3), round(monotony, 2), strain,
                  round(hrv, 1), hrv_d, round(rhr, 0), rhr_d, tli, round(load, 1),
                  round(recovery, 1), level, reason, pct, stale, coverage))

    # 设备
    conn.execute("INSERT INTO devices VALUES(?,?,?,?,?,?)",
                 ("IMU-07", athletes[0][0], 86, 200, 1,
                  datetime.now().strftime("%Y-%m-%d %H:%M")))

    # ---------------- 知行：一个班 36 人 ----------------
    CLASS = "G3-2"
    students = [
        ("S001", "李某某", "李", "risk", "离座 6 次 · 头姿正向率 41%", 1, "3,5,6,6,7"),
        ("S002", "张某某", "张", "amber", "离座 3 次 · 头姿正向率 52%", 1, "2,3,3,4,3"),
        ("S003", "王某某", "王", "ok", "离座 1 次 · 头姿正向率 78%", 1, "1,1,2,1,1"),
        ("S004", "赵某某", "赵", "mute", "未完成测评", 0, ""),
    ]
    others = [(f"S{i:03d}", f"{SURNAME[(i*7) % len(SURNAME)]}某某", SURNAME[(i*7) % len(SURNAME)],
               "ok", "课堂表现平稳", 1, "1,1,1,2,1") for i in range(5, 37)]
    for sid, nm, ini, lv, beh, tested, tr in students + others:
        conn.execute("INSERT INTO students VALUES(?,?,?,?,?,?,?,?,1)",
                     (sid, CLASS, nm, ini, lv, beh, tested, tr))

    # S001 的剖面与指标
    dims = [("持续注意", 15, 1), ("抑制", 8, 2), ("记忆", 42, 3), ("延迟", 22, 4), ("活动", 71, 5)]
    for dim, pct, ord_ in dims:
        conn.execute("INSERT INTO profiles VALUES(?,?,?,?)", ("S001", dim, pct, ord_))
    mets = [("cv_rt", "CV-RT", 0.38, "", 15, 1), ("dprime", "d′", 1.62, "", 18, 2),
            ("ssrt", "SSRT", 212, "ms", 8, 3), ("span", "最大跨度", 4, "", 42, 4)]
    for k, lb, v, u, p, o in mets:
        conn.execute("INSERT INTO metrics VALUES(?,?,?,?,?,?,?)", ("S001", k, lb, v, u, p, o))
    conn.execute("""INSERT INTO referrals(student_id,level,reason,created_by,created_at)
                    VALUES(?,?,?,?,?)""",
                 ("S001", "risk", "抑制第 8 + 注意第 15 百分位，低于 15 阈值",
                  "王老师", datetime.now().isoformat(timespec="seconds")))

    # 摄像头
    conn.execute("INSERT INTO cameras VALUES(?,?,?,?,?,?,?)",
                 ("ZX-01", "教室 302", 1, 1, 38, "课后删除", "不提取"))
    for ts, evt in [("08:00", "启动 · 自检通过"), ("08:05", "采集开始（第 1 节）"),
                    ("08:50", "采集结束 · 视频已销毁"), ("09:00", "采集开始（第 2 节）")]:
        conn.execute("INSERT INTO camera_logs VALUES(?,?,?)", ("ZX-01", ts, evt))

    conn.commit()

    # 统计
    c = conn.execute("SELECT level, COUNT(*) FROM daily_metrics "
                     "WHERE d=(SELECT MAX(d) FROM daily_metrics) GROUP BY level").fetchall()
    print("建库完成 →", DB)
    print("  运动员", conn.execute("SELECT COUNT(*) FROM athletes").fetchone()[0],
          "| 记录", conn.execute("SELECT COUNT(*) FROM daily_metrics").fetchone()[0],
          "| 课次", conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    print("  最新一天分级：", dict(c))
    print("  学生", conn.execute("SELECT COUNT(*) FROM students").fetchone()[0])
    conn.close()


if __name__ == "__main__":
    build()
