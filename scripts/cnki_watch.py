#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文文献监测队列：合并元数据 → 评分 → 分级推送 → 邮件。

不下载任何 PDF：只保存 标题 / 作者 / 摘要 / 关键词 / 出版时间 / 刊名卷期 / DOI / 链接。

子命令
------
  sync    把 state/cnki_meta_*.json 抓到的元数据并入队列并打分（幂等，按题名+刊名去重）
  list    列出队列（--status / --since / --min-score）
  add     手动加一条
  set     改状态（如 已读 / 忽略）
  digest  输出高分条目（供 Agent 做深度解读）
  mail    生成邮件正文 HTML，加 --send 经 SMTP 实发
"""
import argparse
import glob
import hashlib
import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402
import relevance_engine as RE  # noqa: E402

TZ = timezone(timedelta(hours=8))
QUEUE = os.path.join(C.DATA, "cnki_watch.json")

LEVEL_CN = {"critical": "重点必读", "high": "高度相关",
            "recommended": "一般相关", "archive": "仅索引"}


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def load_q():
    return json.load(open(QUEUE, encoding="utf-8")) if os.path.exists(QUEUE) else {"items": []}


def save_q(d):
    C.ensure_dirs()
    json.dump(d, open(QUEUE, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)


def item_id(title, journal, year):
    return hashlib.sha1(re.sub(r"\s+", "", "%s|%s|%s" % (title, journal, year))
                        .encode("utf-8")).hexdigest()[:12]


def esc(s):
    return html.escape(str(s if s is not None else ""))


def norm(t):
    return re.sub(r"[\s\u3000]+", "", t or "")


# ------------------------------------------------------------------ sync
def cmd_sync(a):
    files = sorted(glob.glob(os.path.join(C.STATE, "cnki_meta_*.json")))
    if a.since:
        files = [f for f in files if os.path.basename(f) >= "cnki_meta_%s.json" % a.since]
    q = load_q()
    items = q["items"]
    idx = {(norm(i.get("title")), (i.get("journal") or "").strip()): i for i in items}
    added = updated = 0
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for m in (d.get("items") or []):
            if not m.get("title"):
                continue
            j = (m.get("journal") or "").strip()
            key = (norm(m["title"]), j)
            it = idx.get(key)
            if it is None:
                it = {"id": item_id(m["title"], j, (m.get("pub_date") or "")[:4]),
                      "title": m["title"], "journal": j, "authors": (m.get("authors") or "").strip(";；"),
                      "year": (m.get("pub_date") or "")[:4], "issue": m.get("issue") or "",
                      "pages": "%s-%s" % (m.get("firstpage") or "", m.get("lastpage") or "")
                      if (m.get("firstpage") or m.get("lastpage")) else (m.get("pages") or ""),
                      "url": m.get("href") or "", "status": "new", "added_at": now_iso()}
                items.append(it)
                idx[key] = it
                added += 1
            for src, dst in (("abstract", "abstract"), ("keywords", "keywords"),
                             ("pub_date", "pub_date"), ("doi", "doi"), ("fund", "fund")):
                if m.get(src):
                    it[dst] = m[src]
            if m.get("issue") and not it.get("issue"):
                it["issue"] = m["issue"]
            it["updated_at"] = now_iso()
            updated += 1
    # 打分
    for it in items:
        r = RE.score({"title": it.get("title"), "title_zh": it.get("title"),
                      "abstract": it.get("abstract") or "", "abstract_zh": it.get("abstract") or "",
                      "keywords": it.get("keywords") or [], "journal_name": it.get("journal")},
                     lang="zh")
        it["score"] = r["total_score"]
        it["score_detail"] = r
    items.sort(key=lambda x: -(x.get("score") or 0))
    save_q(q)
    print(json.dumps({"ok": True, "added": added, "updated": updated, "total": len(items),
                      "n_high": sum(1 for i in items if (i.get("score") or 0) >= 75),
                      "queue": QUEUE}, ensure_ascii=False))


# ------------------------------------------------------------------ list / add / set
def cmd_list(a):
    q = load_q()
    items = q["items"]
    if a.status:
        items = [i for i in items if i.get("status") == a.status]
    if a.since:
        items = [i for i in items if (i.get("added_at") or "") >= a.since]
    if a.min_score:
        items = [i for i in items if (i.get("score") or 0) >= a.min_score]
    print(json.dumps({"count": len(items),
                      "items": [{"id": i.get("id"), "score": i.get("score"),
                                 "level": LEVEL_CN.get((i.get("score_detail") or {}).get("alert_level"), ""),
                                 "title": i.get("title"), "journal": i.get("journal"),
                                 "authors": i.get("authors"), "pub_date": i.get("pub_date"),
                                 "status": i.get("status")} for i in items[:a.limit]]},
                     ensure_ascii=False, indent=1))


def cmd_add(a):
    q = load_q()
    it = {"id": item_id(a.title, a.journal, a.year), "title": a.title, "journal": a.journal,
          "year": a.year, "issue": a.issue, "authors": a.authors, "url": a.url,
          "abstract": a.abstract, "keywords": [k for k in re.split(r"[；;,，]", a.keywords) if k],
          "pub_date": a.pub_date, "status": "new", "added_at": now_iso()}
    r = RE.score({"title": it["title"], "title_zh": it["title"], "abstract_zh": it["abstract"],
                  "keywords": it["keywords"], "journal_name": it["journal"]}, lang="zh")
    it["score"], it["score_detail"] = r["total_score"], r
    q["items"].append(it)
    save_q(q)
    print(json.dumps({"ok": True, "item": {"id": it["id"], "score": it["score"]}}, ensure_ascii=False))


def cmd_set(a):
    q = load_q()
    for it in q["items"]:
        if it.get("id") == a.id:
            if a.status:
                it["status"] = a.status
            if a.note:
                it["note"] = a.note
            it["updated_at"] = now_iso()
            save_q(q)
            print(json.dumps({"ok": True, "item": it}, ensure_ascii=False))
            return
    print(json.dumps({"ok": False, "detail": "未找到 id=%s" % a.id}, ensure_ascii=False))


def cmd_digest(a):
    q = load_q()
    items = [i for i in q["items"] if (i.get("score") or 0) >= a.min_score]
    out = [{"id": i.get("id"), "score": i.get("score"),
            "level": LEVEL_CN.get((i.get("score_detail") or {}).get("alert_level"), ""),
            "directions": (i.get("score_detail") or {}).get("directions"),
            "design": (i.get("score_detail") or {}).get("evidence_design"),
            "projects": (i.get("score_detail") or {}).get("project_names"),
            "title": i.get("title"), "journal": i.get("journal"), "authors": i.get("authors"),
            "pub_date": i.get("pub_date"), "abstract": (i.get("abstract") or "")[:600],
            "keywords": i.get("keywords"), "url": i.get("url"),
            "reason": (i.get("score_detail") or {}).get("recommend_reason")}
           for i in items[:a.limit]]
    print(json.dumps({"count": len(items), "items": out}, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ mail
def build_mail(items, title_prefix="中文期刊（CSSCI）新刊监测"):
    by_j = {}
    for it in items:
        by_j.setdefault(it.get("journal") or "未标注期刊", []).append(it)
    rows = []
    for j in sorted(by_j):
        rows.append('<div style="margin:16px 0 6px;font-size:15px;font-weight:700;">%s'
                    '<span style="font-weight:400;color:#666;">（%d 篇）</span></div>'
                    % (esc(j), len(by_j[j])))
        for it in by_j[j]:
            sd = it.get("score_detail") or {}
            kw = it.get("keywords") or []
            kwtxt = ("关键词：" + esc("；".join(kw[:8]))) if kw else "关键词：未获取"
            ab = (it.get("abstract") or "")
            abtxt = ('<div style="font-size:13px;color:#444;margin-top:5px;line-height:1.6;">'
                     '摘要：%s</div>' % esc(ab[:260] + ("…" if len(ab) > 260 else ""))) if ab else \
                    '<div style="font-size:13px;color:#999;margin-top:5px;">摘要：未获取</div>'
            link = ('<a href="%s" style="color:#0a58ca;">知网链接</a>' % esc(it["url"])) if it.get("url") else ""
            rows.append(
                '<div style="border:1px solid #e0e0e0;border-radius:5px;padding:11px 13px;margin:8px 0;">'
                '<div style="font-size:14.5px;font-weight:600;line-height:1.5;">%s</div>'
                '<div style="font-size:13px;color:#666;margin:3px 0;">%s · %s%s · 评分 %s（%s）%s</div>'
                '<div style="font-size:13px;color:#555;">%s</div>%s<div style="font-size:13px;">%s</div>'
                '</div>'
                % (esc(it.get("title")), esc(it.get("authors") or "作者未获取"),
                   esc(str(it.get("pub_date") or it.get("year") or "")),
                   (" 第" + esc(str(it["issue"])) + "期") if it.get("issue") else "",
                   esc(it.get("score")), esc(LEVEL_CN.get(sd.get("alert_level"), "")),
                   (" · " + esc(sd.get("evidence_design"))) if sd.get("evidence_design") else "",
                   kwtxt, abtxt, link))
    body = ('<div style="font-family:Microsoft YaHei,sans-serif;font-size:15px;line-height:1.8;'
            'color:#1a1a1a;max-width:760px;margin:0 auto;padding:18px;">'
            '<div style="font-size:18px;font-weight:700;margin-bottom:6px;">%s</div>'
            '<div style="font-size:13px;color:#666;margin-bottom:14px;">共 %d 篇新论文；'
            '生成时间 %s（UTC+8）</div>' % (esc(title_prefix), len(items), now_iso()) +
            "".join(rows) +
            '<div style="margin-top:26px;padding-top:12px;border-top:1px solid #e3e3e3;'
            'font-size:12px;color:#777;">本邮件由学术文献监测 Skill 生成；题名与元数据来自知网实际页面'
            '（经使用者本人学校 WebVPN 机构认证），未获取到的字段一律留空，不做推测填充。</div></div>')
    subject = "【中文期刊更新】新论文 %d 篇｜高分 %d 篇" % (
        len(items), sum(1 for i in items if (i.get("score") or 0) >= 75))
    return subject, body


def cmd_mail(a):
    q = load_q()
    items = [i for i in q["items"] if (i.get("score") or 0) >= a.min_score]
    if a.since:
        items = [i for i in items if (i.get("added_at") or "") >= a.since]
    if not items:
        print(json.dumps({"ok": False, "detail": "无符合条件的条目，未生成邮件"}, ensure_ascii=False))
        return
    subject, body = build_mail(items)
    out = {"subject": subject, "count": len(items)}
    if a.send:
        import smtp_sender
        out.update(smtp_sender.send(subject, body, subtype="html"))
    else:
        C.ensure_dirs()
        p = os.path.join(C.OUTBOX, "cnki_mail_%s.html" % datetime.now(TZ).strftime("%Y%m%d_%H%M%S"))
        open(p, "w", encoding="utf-8").write(body)
        out.update({"ok": True, "detail": "未发送（未加 --send）", "path": p})
    print(json.dumps(out, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description="中文文献监测队列")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync")
    p.add_argument("--since", default="")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("list")
    p.add_argument("--status", default="")
    p.add_argument("--since", default="")
    p.add_argument("--min-score", type=float, default=0)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("add")
    for f in ("title", "journal", "year", "issue", "authors", "url", "abstract", "keywords", "pub_date"):
        p.add_argument("--" + f.replace("_", "-"), default="")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("set")
    p.add_argument("--id", required=True)
    p.add_argument("--status", default="")
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("digest")
    p.add_argument("--min-score", type=float, default=75)
    p.add_argument("--limit", type=int, default=30)
    p.set_defaults(func=cmd_digest)

    p = sub.add_parser("mail")
    p.add_argument("--min-score", type=float, default=60)
    p.add_argument("--since", default="")
    p.add_argument("--send", action="store_true")
    p.set_defaults(func=cmd_mail)

    a = ap.parse_args()
    C.ensure_dirs()
    a.func(a)


if __name__ == "__main__":
    main()
