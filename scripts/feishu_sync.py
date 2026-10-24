# -*- coding: utf-8 -*-
"""飞书联动（可选）：把高分文献写成日历日程 / 多维表格记录。

凭据来自 config/feishu.json（setup.py 填写）：
  {"app_id": "...", "app_secret": "...", "calendar_id": "...",
   "base_token": "...", "table_id": "..."}

子命令
------
  check                        验证 tenant_access_token 是否拿得到
  calendar --file items.json   把条目写成当天日程（标题=文献题名，描述=评分+摘要+链接）
  bitable  --file items.json   把条目写入多维表格（需 base_token + table_id）
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402

API = "https://open.feishu.cn/open-apis"
TZ = timezone(timedelta(hours=8))


def conf():
    d = C.load("feishu")
    if not (d.get("app_id") and d.get("app_secret")):
        raise RuntimeError("未配置飞书：setup.py set feishu --app-id ... --app-secret ...")
    return d


def token():
    c = conf()
    body = {"app_id": c["app_id"], "app_secret": c["app_secret"]}
    req = urllib.request.Request(API + "/auth/v3/tenant_access_token/internal",
                                 data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read().decode("utf-8"))
    if j.get("code") != 0 or not j.get("tenant_access_token"):
        raise RuntimeError("取 token 失败：%s" % j.get("msg"))
    return j["tenant_access_token"]


def api(method, path, body=None, tk=None):
    tk = tk or token()
    req = urllib.request.Request(API + path,
                                 data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + tk},
                                 method=method)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode("utf-8"))


def cmd_check(a):
    try:
        tk = token()
        print(json.dumps({"ok": True, "token_prefix": tk[:6] + "***"}, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "detail": str(e)[:200]}, ensure_ascii=False))


def _load(a):
    d = json.load(open(a.file, encoding="utf-8"))
    return d.get("items") if isinstance(d, dict) else d


def cmd_calendar(a):
    c = conf()
    if not c.get("calendar_id"):
        print(json.dumps({"ok": False, "detail": "缺 calendar_id"}, ensure_ascii=False))
        return
    items = _load(a)[:a.limit]
    day = datetime.now(TZ).replace(hour=9, minute=0, second=0, microsecond=0)
    out = []
    for i, it in enumerate(items):
        start = day + timedelta(minutes=30 * i)
        end = start + timedelta(minutes=25)
        desc = ("评分 %s｜%s\n%s\n%s" % (it.get("score"), it.get("journal") or it.get("journal_name") or "",
                                         (it.get("abstract") or it.get("abstract_en") or "")[:300],
                                         it.get("url") or ""))
        body = {"summary": (it.get("title") or it.get("title_en") or "")[:80],
                "description": desc,
                "start_time": {"timestamp": str(int(start.timestamp()))},
                "end_time": {"timestamp": str(int(end.timestamp()))}}
        try:
            r = api("POST", "/calendar/v4/calendars/%s/events" % c["calendar_id"], body)
            out.append({"title": body["summary"], "ok": r.get("code") == 0,
                        "msg": r.get("msg")})
        except Exception as e:
            out.append({"title": body["summary"], "ok": False, "msg": str(e)[:120]})
    print(json.dumps({"ok": True, "n": len(out), "items": out}, ensure_ascii=False, indent=1))


def cmd_bitable(a):
    c = conf()
    if not (c.get("base_token") and c.get("table_id")):
        print(json.dumps({"ok": False, "detail": "缺 base_token / table_id"}, ensure_ascii=False))
        return
    items = _load(a)[:a.limit]
    recs = []
    for it in items:
        recs.append({"fields": {
            "文献题名": it.get("title") or it.get("title_en") or "",
            "期刊": it.get("journal") or it.get("journal_name") or "",
            "评分": it.get("score"),
            "研究方向": "/".join((it.get("score_detail") or {}).get("directions") or []),
            "链接": it.get("url") or "",
        }})
    r = api("POST", "/bitable/v1/apps/%s/tables/%s/records/batch_create"
            % (c["base_token"], c["table_id"]), {"records": recs})
    print(json.dumps({"ok": r.get("code") == 0, "msg": r.get("msg"),
                      "n": len(recs)}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="飞书联动（可选）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(func=cmd_check)
    for nm, fn in (("calendar", cmd_calendar), ("bitable", cmd_bitable)):
        p = sub.add_parser(nm)
        p.add_argument("--file", required=True)
        p.add_argument("--limit", type=int, default=10)
        p.set_defaults(func=fn)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
