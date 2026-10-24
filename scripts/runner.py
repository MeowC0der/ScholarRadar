#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""英文文献监测主流程：采集 → 入队去重 → 评分 → 高分清单 → 邮件。

子命令
------
  collect [--mode journals|questions|both] [--days N]   调 collector 抓原始文献
  sync                                                 把最新原始结果并入队列并打分
  digest [--min-score 75] [--limit 20]                 输出高分清单（供 Agent 深度解读）
  mail   [--min-score 60] [--send]                     生成/发送邮件
  run                                                  collect + sync + digest 一键
"""
import argparse
import glob
import html
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(BASE, "scripts")
sys.path.insert(0, SCRIPTS)
import config_loader as C  # noqa: E402
import relevance_engine as RE  # noqa: E402

TZ = timezone(timedelta(hours=8))
QUEUE = os.path.join(C.DATA, "en_watch.json")
LEVEL_CN = {"critical": "重点必读", "high": "高度相关",
            "recommended": "一般相关", "archive": "仅索引"}


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def load_q():
    return json.load(open(QUEUE, encoding="utf-8")) if os.path.exists(QUEUE) else {"items": []}


def save_q(d):
    C.ensure_dirs()
    json.dump(d, open(QUEUE, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)


def esc(s):
    return html.escape(str(s if s is not None else ""))


def run_py(name, args):
    cmd = [sys.executable, os.path.join(SCRIPTS, name)] + args
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout or "").strip()[-2000:])
    if r.returncode != 0:
        print("[stderr] " + (r.stderr or "")[-500:])
    return r.returncode


def latest_raw(since=None):
    files = sorted(glob.glob(os.path.join(C.DATA, "raw_en_*.json")))
    if since:
        files = [f for f in files if os.path.basename(f) >= "raw_en_%s" % since]
    return files[-1] if files else None


def cmd_collect(a):
    modes = ["journals", "questions"] if a.mode == "both" else [a.mode]
    rc = 0
    for m in modes:
        rc |= run_py("collector.py", [m, "--days", str(a.days), "--per-page", str(a.per_page)])
    print(json.dumps({"ok": rc == 0, "modes": modes, "days": a.days}, ensure_ascii=False))


def cmd_sync(a):
    f = a.raw or latest_raw()
    if not f or not os.path.exists(f):
        print(json.dumps({"ok": False, "detail": "没有原始采集文件，先跑 collect"},
                         ensure_ascii=False))
        return
    raw = json.load(open(f, encoding="utf-8"))
    q = load_q()
    seen = {(i.get("doi") or "").lower() or (i.get("title_en") or "").strip().lower()
            for i in q["items"]}
    added = 0
    for it in raw.get("items") or []:
        k = (it.get("doi") or "").lower() or (it.get("title_en") or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        r = RE.score(it, lang="en")
        it["score"] = r["total_score"]
        it["score_detail"] = r
        it["status"] = "new"
        it["added_at"] = now_iso()
        q["items"].append(it)
        added += 1
    q["items"].sort(key=lambda x: -(x.get("score") or 0))
    save_q(q)
    print(json.dumps({"ok": True, "raw": f, "added": added, "total": len(q["items"]),
                      "n_high": sum(1 for i in q["items"] if (i.get("score") or 0) >= 75)},
                     ensure_ascii=False))


def cmd_digest(a):
    q = load_q()
    items = [i for i in q["items"] if (i.get("score") or 0) >= a.min_score]
    out = []
    for i in items[:a.limit]:
        sd = i.get("score_detail") or {}
        out.append({"doi": i.get("doi"), "score": i.get("score"),
                    "level": LEVEL_CN.get(sd.get("alert_level"), ""),
                    "directions": sd.get("directions"), "design": sd.get("evidence_design"),
                    "projects": sd.get("project_names"),
                    "title": i.get("title_en"), "journal": i.get("journal_name"),
                    "authors": i.get("authors"), "published": i.get("published_date"),
                    "status": i.get("publication_status"),
                    "abstract": (i.get("abstract_en") or "")[:600],
                    "url": i.get("url"), "reason": sd.get("recommend_reason")})
    print(json.dumps({"count": len(items), "items": out}, ensure_ascii=False, indent=1))


def build_mail(items):
    rows = []
    for i in items:
        sd = i.get("score_detail") or {}
        ab = (i.get("abstract_en") or "")
        rows.append(
            '<div style="border:1px solid #e0e0e0;border-radius:5px;padding:11px 13px;margin:8px 0;">'
            '<div style="font-size:14.5px;font-weight:600;line-height:1.5;">%s</div>'
            '<div style="font-size:13px;color:#666;margin:3px 0;">%s · <i>%s</i> · %s · 评分 %s（%s）%s</div>'
            '<div style="font-size:13px;color:#444;margin-top:5px;line-height:1.6;">%s</div>'
            '<div style="font-size:13px;"><a href="%s" style="color:#0a58ca;">原文链接</a></div></div>'
            % (esc(i.get("title_en")),
               esc("；".join(i.get("authors") or [])[:120] or "作者未获取"),
               esc(i.get("journal_name") or ""), esc(i.get("published_date") or ""),
               esc(i.get("score")), esc(LEVEL_CN.get(sd.get("alert_level"), "")),
               (" · " + esc(sd.get("evidence_design"))) if sd.get("evidence_design") else "",
               esc(ab[:260] + ("…" if len(ab) > 260 else "")),
               esc(i.get("url") or "")))
    body = ('<div style="font-family:Microsoft YaHei,sans-serif;font-size:15px;line-height:1.8;'
            'color:#1a1a1a;max-width:760px;margin:0 auto;padding:18px;">'
            '<div style="font-size:18px;font-weight:700;margin-bottom:6px;">英文期刊新文献监测</div>'
            '<div style="font-size:13px;color:#666;margin-bottom:14px;">共 %d 篇；生成时间 %s（UTC+8）</div>'
            % (len(items), now_iso()) + "".join(rows) +
            '<div style="margin-top:26px;padding-top:12px;border-top:1px solid #e3e3e3;'
            'font-size:12px;color:#777;">数据来源 OpenAlex 官方 API；缺失字段一律留空。</div></div>')
    subject = "【英文期刊更新】%d 篇｜高分 %d 篇" % (
        len(items), sum(1 for i in items if (i.get("score") or 0) >= 75))
    return subject, body


def cmd_mail(a):
    q = load_q()
    items = [i for i in q["items"] if (i.get("score") or 0) >= a.min_score]
    if a.since:
        items = [i for i in items if (i.get("added_at") or "") >= a.since]
    if not items:
        print(json.dumps({"ok": False, "detail": "无符合条件的条目"}, ensure_ascii=False))
        return
    subject, body = build_mail(items)
    out = {"subject": subject, "count": len(items)}
    if a.send:
        import smtp_sender
        out.update(smtp_sender.send(subject, body, subtype="html"))
    else:
        C.ensure_dirs()
        p = os.path.join(C.OUTBOX, "en_mail_%s.html" % datetime.now(TZ).strftime("%Y%m%d_%H%M%S"))
        open(p, "w", encoding="utf-8").write(body)
        out.update({"ok": True, "detail": "未发送（未加 --send）", "path": p})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_run(a):
    cmd_collect(a)
    cmd_sync(a)
    cmd_digest(a)


def main():
    ap = argparse.ArgumentParser(description="英文文献监测主流程")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("collect")
    p.add_argument("--mode", default="both", choices=["journals", "questions", "both"])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--per-page", type=int, default=50)
    p.set_defaults(func=cmd_collect)

    p = sub.add_parser("sync")
    p.add_argument("--raw", default="")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("digest")
    p.add_argument("--min-score", type=float, default=75)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("mail")
    p.add_argument("--min-score", type=float, default=60)
    p.add_argument("--since", default="")
    p.add_argument("--send", action="store_true")
    p.set_defaults(func=cmd_mail)

    p = sub.add_parser("run")
    p.add_argument("--mode", default="both", choices=["journals", "questions", "both"])
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--per-page", type=int, default=50)
    p.add_argument("--min-score", type=float, default=75)
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_run)

    a = ap.parse_args()
    C.ensure_dirs()
    a.func(a)


if __name__ == "__main__":
    main()
