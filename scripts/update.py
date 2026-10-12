"""行车账本 公开数据更新脚本（GitHub Actions 每天 08:30、20:30 北京时间运行，需求 12.3）。

只用 Python 标准库。环境变量 JUHE_KEY：聚合数据"今日油价"Key（存在仓库 Secrets，不进仓库）。
生成：
  oil/latest.json       各省各油品今日最高零售价
  oil/history.json      各省各油品历次价格（只在变化时追加）
  oil/adjustments.json  调价记录（窗口日、涨 / 跌 / 搁浅、汽油每吨幅度）+ 下次窗口
  holiday/<年>.json     法定节假日（来自 holiday-cn，镜像一份供 App 国内访问）
所有文件带 schemaVersion 与 updatedAt。App 只读这些文件，失败时才直连接口。
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = 1
TZ = dt.timezone(dt.timedelta(hours=8))
PROVINCES = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西", "山东",
    "河南", "湖北", "湖南", "广东", "广西", "海南", "四川", "贵州", "云南", "西藏", "陕西", "甘肃", "青海", "宁夏", "新疆", "内蒙古",
]
GRADES = {"92h": "92", "95h": "95", "98h": "98", "0h": "0"}
ANCHOR = dt.date(2026, 1, 6)  # 2026 年第 1 轮调价窗口
# 2026 年已公布的调价（窗口日，汽油元/吨；None = 不作调整），与 App 内置一致
SEED_2026 = [
    ("01-06", None), ("01-20", 85), ("02-03", 205), ("02-24", 175), ("03-09", 695), ("03-23", 1160), ("04-07", 420),
    ("04-21", -555), ("05-08", 320), ("05-21", 75), ("06-04", -525), ("06-18", -515), ("07-03", -950), ("07-17", 300),
    ("07-31", 685), ("08-14", -230), ("08-28", 375), ("09-11", 260), ("09-24", 395),
]


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": "vehicle-logbook-data/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def load(path, default):
    p = ROOT / path
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(path, data):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=False) + "\n", encoding="utf-8")


def normalize(name):
    return next((p for p in PROVINCES if name.strip().startswith(p)), None)


# ---------- 节假日与调价窗口 ----------

def update_holidays(today):
    years = [today.year] + ([today.year + 1] if today.month >= 11 else [])
    for y in [today.year - 1] + years:
        path = f"holiday/{y}.json"
        old = load(path, None)
        if old and old.get("days") and y < today.year:
            continue  # 往年的不再变
        try:
            d = json.loads(http_get(f"https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{y}.json"))
        except Exception as e:  # noqa: BLE001 —— 节假日失败不影响油价
            print(f"节假日 {y} 获取失败：{e}", file=sys.stderr)
            continue
        if d.get("days"):
            save(path, {"schemaVersion": SCHEMA, "year": y, "source": "holiday-cn", "days": d["days"]})


def special_days():
    out = {}
    for p in (ROOT / "holiday").glob("*.json"):
        for d in json.loads(p.read_text(encoding="utf-8")).get("days", []):
            out[dt.date.fromisoformat(d["date"])] = d["isOffDay"]
    return out


def is_workday(d, special):
    return (not special[d]) if d in special else d.weekday() < 5


def next_window(w, special):
    n = 0
    while n < 10:
        w += dt.timedelta(days=1)
        if is_workday(w, special):
            n += 1
    return w


def cycle(today, anchor, special):
    """返回 (上一个窗口, 下一个窗口)；今天是窗口日时下一个窗口 = 今天。"""
    last, nxt = anchor, next_window(anchor, special)
    while nxt < today:
        last, nxt = nxt, next_window(nxt, special)
    return last, nxt


# ---------- 油价 ----------

def fetch_prices(key):
    body = json.loads(http_get("https://apis.juhe.cn/gnyj/query?key=" + key))
    if body.get("error_code") != 0 or not body.get("result"):
        raise SystemExit(f"油价接口错误：{body.get('error_code')} {body.get('reason')}")
    out = {}
    for r in body["result"]:
        p = normalize(r.get("city", ""))
        if not p:
            continue
        prices = {}
        for f, g in GRADES.items():
            try:
                v = float(str(r.get(f, "")).strip())
            except ValueError:
                continue
            if v > 0:
                prices[g] = f"{v:.2f}"
        if prices:
            out[p] = prices
    if len(out) < 25:
        raise SystemExit(f"油价接口只返回了 {len(out)} 个省，不更新")
    return out


def main():
    key = os.environ.get("JUHE_KEY", "").strip()
    if not key:
        raise SystemExit("缺少环境变量 JUHE_KEY")
    now = dt.datetime.now(TZ)
    today = now.date()
    stamp = now.isoformat(timespec="seconds")

    update_holidays(today)
    special = special_days()

    adj = load("oil/adjustments.json", {"schemaVersion": SCHEMA, "items": []})
    items = {i["window"]: i for i in adj["items"]}
    for d, v in SEED_2026:
        w = f"2026-{d}"
        items.setdefault(w, {"window": w, "direction": "stranded" if v is None else ("up" if v > 0 else "down"), "gasolinePerTon": v, "source": "公告"})
    anchor = max([dt.date.fromisoformat(w) for w in items] + [ANCHOR])
    last_window, _ = cycle(today, anchor, special)
    effective = last_window + dt.timedelta(days=1)

    prices = fetch_prices(key)
    history = load("oil/history.json", {"schemaVersion": SCHEMA, "provinces": {}})
    deltas = []  # 92 号变化（元/升）
    for p, grades in prices.items():
        hp = history["provinces"].setdefault(p, {})
        for g, v in grades.items():
            pts = hp.setdefault(g, [])
            if pts and pts[-1][1] == v:
                continue
            # 生效日：上次窗口次日；同一窗口内再变（接口修正）记到今天
            eff = effective if (not pts or dt.date.fromisoformat(pts[-1][0]) < effective) else today
            eff = min(eff, today)
            if pts and g == "92":
                deltas.append(float(v) - float(pts[-1][1]))
            if pts and pts[-1][0] == eff.isoformat():
                pts[-1] = [eff.isoformat(), v]  # 同一天修正
            else:
                pts.append([eff.isoformat(), v])

    # 多数省份 92 号同时变化 → 一次调价（官方记录已有的不覆盖）
    if len(deltas) >= 10:
        w = (effective - dt.timedelta(days=1)).isoformat()
        avg = sum(deltas) / len(deltas)
        per_ton = round(avg * 1360 / 5) * 5
        items.setdefault(w, {
            "window": w, "direction": "stranded" if abs(per_ton) < 50 else ("up" if per_ton > 0 else "down"),
            "gasolinePerTon": per_ton, "source": "价格变化推算",
        })
    # 窗口过去两天价格仍没变：记为搁浅
    lw = last_window.isoformat()
    if lw not in items and (today - last_window).days >= 2 and not deltas:
        items[lw] = {"window": lw, "direction": "stranded", "gasolinePerTon": None, "source": "价格未变推算"}

    anchor = max([dt.date.fromisoformat(w) for w in items] + [ANCHOR])
    _, nxt = cycle(today, anchor, special)
    save("oil/latest.json", {"schemaVersion": SCHEMA, "updatedAt": stamp, "source": "聚合数据", "provinces": prices})
    history["updatedAt"] = stamp
    save("oil/history.json", history)
    save("oil/adjustments.json", {
        "schemaVersion": SCHEMA, "updatedAt": stamp,
        "items": sorted(items.values(), key=lambda i: i["window"], reverse=True),
        "nextWindow": nxt.isoformat(),
        # 趋势预测（国际原油变化率估算）待接入公开原油价格源，暂不提供
        "trend": None,
    })
    print(f"{stamp} 更新完成：{len(prices)} 个省，92 号变化 {len(deltas)} 个省，下次窗口 {nxt}")


if __name__ == "__main__":
    main()
