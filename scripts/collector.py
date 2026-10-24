#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""英文文献采集（OpenAlex 官方 API，公开合法接口）

子命令
------
  journals    按 config/profile.json 的 journals_en 清单，抓最近 N 天的新论文
  questions   按 profile 里各研究方向的关键词/研究问题，做问题驱动检索
  crossref    用 Crossref 校验期刊 ISSN 与最新卷期（补全清单用）

依赖配置：config/openalex.json（api_key / mailto，可留空）、config/profile.json
输出：data/raw_en_<时间戳>.json（原始）+ stdout 汇总
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402

OA = "https://api.openalex.org"
CR = "https://api.crossref.org"
TZ = timezone(timedelta(hours=8))
UA = "academic-lit-monitor/1.0 (mailto:%s)"


def oa_params(extra=None):
    oa = C.load("openalex")
    p = dict(extra or {})
    if oa.get("mailto"):
        p["mailto"] = oa["mailto"]
    if oa.get("api_key"):
        p["api_key"] = oa["api_key"]
    return p


def http_json(url, params=None, timeout=40, headers=None):
    if params:
        url += "&" + urllib.parse.urlencode(params) if "?" in url else "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA % (C.load("openalex").get("mailto") or "unknown")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def inverted_to_text(inv):
    if not inv:
        return ""
    pos = {}
    for w, idxs in inv.items():
        for i in idxs:
            pos[i] = w
    return " ".join(pos[k] for k in sorted(pos))


def work_to_item(w):
    loc = (w.get("primary_location") or {})
    src = loc.get("source") or {}
    auths = []
    for a in (w.get("authorships") or []):
        nm = (a.get("author") or {}).get("display_name")
        if nm:
            auths.append(nm)
    return {
        "article_uid": (w.get("doi") or w.get("id") or "").replace("https://doi.org/", ""),
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "title_en": w.get("title") or w.get("display_name") or "",
        "abstract_en": inverted_to_text(w.get("abstract_inverted_index")),
        "authors": auths,
        "author_affil": "",
        "journal_name": src.get("display_name") or "",
        "issn": ",".join(src.get("issn_l") and [src.get("issn_l")] or (src.get("issn") or [])),
        "volume": w.get("biblio", {}).get("volume"),
        "issue": w.get("biblio", {}).get("issue"),
        "pages": "-".join([str(w.get("biblio", {}).get("first_page") or ""),
                           str(w.get("biblio", {}).get("last_page") or "")]).strip("-"),
        "published_date": w.get("publication_date") or "",
        "url": w.get("doi") or (loc.get("landing_page_url") or ""),
        "publication_status": "preprint" if w.get("type") == "preprint" else (
            "online_first" if w.get("publication_date") else "unknown"),
        "preprint_status": "preprint" if w.get("type") == "preprint" else "published",
        "article_type": w.get("type") or "",
        "source_api": "openalex",
        "keywords": [str(k.get("keyword")) for k in (w.get("keywords") or [])
                     if isinstance(k, dict) and k.get("keyword")],
    }


def fetch_works(filters, per_page=50, max_pages=3, sort="publication_date:desc"):
    out, cursor = [], "*"
    f = dict(filters)
    for _ in range(max_pages):
        params = oa_params({"filter": ",".join("%s:%s" % (k, v) for k, v in f.items()),
                            "per-page": per_page, "cursor": cursor, "sort": sort})
        j = http_json(OA + "/works", params)
        res = j.get("results") or []
        out += [work_to_item(w) for w in res]
        cursor = (j.get("meta") or {}).get("next_cursor")
        if not res or not cursor:
            break
        time.sleep(1.0)
    return out


def dedup(items):
    seen, out = set(), []
    for it in items:
        k = (it.get("doi") or "").lower() or (it.get("title_en") or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def cmd_journals(a):
    js = C.journals("en")
    if not js:
        print(json.dumps({"ok": False, "detail": "profile.journals_en 为空，先跑 setup.py gen-profile"},
                         ensure_ascii=False))
        return
    since = a.since or (datetime.now(TZ) - timedelta(days=a.days)).strftime("%Y-%m-%d")
    all_items, errors = [], []
    for j in js[:a.limit_journals]:
        issn = (j.get("issn") or "").strip()
        name = (j.get("name") or "").strip()
        if issn:
            f = {"primary_location.source.issn": issn, "from_publication_date": since}
        else:
            f = {"primary_location.source.display_name.search": name, "from_publication_date": since}
        try:
            got = fetch_works(f, per_page=a.per_page, max_pages=a.pages)
        except Exception as e:
            errors.append({"journal": name, "reason": "%s: %s" % (type(e).__name__, str(e)[:120])})
            continue
        for it in got:
            it.setdefault("journal_name", name)
        all_items += got
        print("  %-40s %d 篇" % (name[:40], len(got)), flush=True)
        time.sleep(1.0)
    items = dedup(all_items)
    out = save(items, "journals_%s" % since)
    print(json.dumps({"ok": True, "since": since, "n_journals": len(js),
                      "n_items": len(items), "errors": errors, "out": out}, ensure_ascii=False))


def cmd_questions(a):
    dirs = C.directions()
    if not dirs:
        print(json.dumps({"ok": False, "detail": "profile.directions 为空"}, ensure_ascii=False))
        return
    since = a.since or (datetime.now(TZ) - timedelta(days=a.days)).strftime("%Y-%m-%d")
    all_items = []
    for d in dirs:
        kws = [k for k in (d.get("keywords_en") or []) if k]
        qs = [q for q in (d.get("research_questions") or []) if q]
        probe = " ".join(kws[:a.n_keywords]) or (qs[0] if qs else "")
        if not probe:
            continue
        try:
            got = fetch_works({"title_and_abstract.search": probe,
                               "from_publication_date": since},
                              per_page=a.per_page, max_pages=1,
                              sort="relevance_score:desc")
        except Exception as e:
            print("  [error] %s: %s" % (d.get("code"), str(e)[:100]), flush=True)
            continue
        for it in got:
            it["hit_direction"] = d.get("code")
        all_items += got
        print("  %s %-24s %d 篇" % (d.get("code"), (d.get("name_zh") or "")[:24], len(got)), flush=True)
        time.sleep(1.0)
    items = dedup(all_items)
    out = save(items, "questions_%s" % since)
    print(json.dumps({"ok": True, "n_items": len(items), "out": out}, ensure_ascii=False))


def cmd_crossref(a):
    """按刊名查 ISSN，用来补全 profile.journals_en"""
    out = []
    for name in [x.strip() for x in a.names.split(";") if x.strip()]:
        try:
            j = http_json(CR + "/journals", {"query": name, "rows": 1},
                          headers={"User-Agent": UA % (C.load("openalex").get("mailto") or "x")})
            it = (j.get("message", {}).get("items") or [{}])[0]
            out.append({"query": name, "name": (it.get("title") or [""])[0],
                        "issn": ",".join(it.get("ISSN") or [])})
        except Exception as e:
            out.append({"query": name, "error": str(e)[:120]})
        time.sleep(1.0)
    print(json.dumps(out, ensure_ascii=False, indent=1))


def save(items, tag):
    C.ensure_dirs()
    p = os.path.join(C.DATA, "raw_en_%s_%s.json"
                     % (tag, datetime.now(TZ).strftime("%Y%m%d_%H%M%S")))
    json.dump({"ts": datetime.now(TZ).isoformat(timespec="seconds"), "items": items},
              open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return p


def main():
    ap = argparse.ArgumentParser(description="英文文献采集（OpenAlex / Crossref）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("journals", "questions"):
        p = sub.add_parser(name)
        p.add_argument("--since", default="")
        p.add_argument("--days", type=int, default=7)
        p.add_argument("--per-page", type=int, default=50)
        p.add_argument("--pages", type=int, default=2)
        p.add_argument("--limit-journals", type=int, default=60)
        p.add_argument("--n-keywords", type=int, default=8)
        p.set_defaults(func=cmd_journals if name == "journals" else cmd_questions)

    p = sub.add_parser("crossref")
    p.add_argument("--names", required=True, help="分号分隔的刊名")
    p.set_defaults(func=cmd_crossref)

    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
