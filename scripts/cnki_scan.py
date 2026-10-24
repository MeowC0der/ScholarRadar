#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文期刊（知网）目录发现 + 文献元数据抓取 —— 只抓基础信息，不下载 PDF。

通道：安装者自己的学校/单位 WebVPN（config/webvpn.json，由 setup.py 填写），
浏览器后台无头运行（cnki_browser），不弹窗、不打断日常工作。

子命令
------
  toc     进知网「出版物检索」按刊名找期刊详情页，抽最新一期目录（栏目/篇名/作者/链接）
  meta    打开每篇的详情页，抽 摘要 / 关键词 / 出版时间 / DOI / 基金 / 卷期页码
  run     toc + meta 一次跑完（推荐）

产物：state/cnki_toc_<日期>.json、state/cnki_meta_<日期>.json（按题名增量合并，绝不推测填充）
"""
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402
import cnki_browser  # noqa: E402
import webvpn  # noqa: E402

TZ = timezone(timedelta(hours=8))

EXTRACT_TOC = r"""() => {
  const out = [];
  document.querySelectorAll('dl').forEach(dl => {
    const dt = dl.querySelector('dt');
    const sec = dt ? (dt.innerText || '').trim() : '';
    dl.querySelectorAll('dd').forEach(dd => {
      const a = dd.querySelector('span.name a');
      if (!a) return;
      const get = cls => {
        const s = dd.querySelector('span.' + cls);
        return s ? (s.innerText || '').trim() : '';
      };
      out.push({section: sec, title: (a.innerText || '').trim(),
                authors: get('author'), pages: get('company'), href: a.href});
    });
  });
  return out;
}"""

ISSUE_TXT = r"""() => {
  const el = [...document.querySelectorAll('div,span,dt')]
    .map(e => (e.innerText || '').trim()).find(t => /^\d{4}年\d{1,2}期$/.test(t));
  return el || '';
}"""

EXTRACT_META = r"""() => {
  const meta = n => {
    const m = document.querySelector('meta[name="' + n + '"]');
    return m ? (m.getAttribute('content') || '').trim() : '';
  };
  const txt = sel => {
    const e = document.querySelector(sel);
    return e ? (e.innerText || '').trim() : '';
  };
  let abstract = meta('citation_abstract') || meta('DC.description') || meta('description');
  if (!abstract) {
    for (const sel of ['#ChDivSummary', '.abstract-text', 'div.abstract', 'div.brief',
                       '#abstract', '.abstract .text', 'div.xxy_text']) {
      const t = txt(sel);
      if (t && t.length > 10) { abstract = t; break; }
    }
  }
  let kw = [];
  const kwMeta = meta('citation_keywords') || meta('keywords');
  if (kwMeta) kw = kwMeta.split(/[;；,，]/).map(s => s.trim()).filter(Boolean);
  if (!kw.length) {
    const as = [...document.querySelectorAll('.keywords a, #catalog_KEYWORD a, .keyword a, p.keywords a')];
    kw = as.map(a => (a.innerText || '').trim().replace(/[;；]$/, '')).filter(Boolean);
  }
  let pub = meta('citation_publication_date') || meta('citation_date') ||
            meta('article:published_time') || meta('prism.publicationDate');
  const body = document.body ? (document.body.innerText || '') : '';
  if (!pub) {
    const m = body.match(/(出版日期|网络首发时间|发表时间)\s*[:：]?\s*(\d{4}-\d{1,2}-\d{1,2})/);
    if (m) pub = m[2];
  }
  let doi = meta('citation_doi') || meta('DC.Identifier');
  if (!doi) {
    const m = body.match(/DOI\s*[:：]?\s*(10\.\d{4,9}\/[^\s，,；;]+)/i);
    if (m) doi = m[1];
  }
  let fund = '';
  const fm = body.match(/基金项目\s*[:：]\s*([^\n]{0,300})/);
  if (fm) fund = fm[2].trim();
  return {
    abstract: (abstract || '').replace(/\s+/g, ' ').trim(),
    keywords: kw, pub_date: pub || '', doi: (doi || '').trim(), fund: fund,
    journal_meta: meta('citation_journal_title'), volume: meta('citation_volume'),
    issue_meta: meta('citation_issue'), firstpage: meta('citation_firstpage'),
    lastpage: meta('citation_lastpage'), authors_meta: meta('citation_author'),
    affiliation: meta('citation_author_institution'), url: location.href
  };
}"""

SLIDER_JS = """() => {
  const u = location.href;
  if (/\\/verify\\/home|blockPuzzle/.test(u)) return true;
  const box = document.querySelector('#puzzleBox, .nc_scale, .yidun, .tcaptcha');
  return !!(box && box.getBoundingClientRect().width > 0);
}"""


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


def today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def load_json(p, default):
    if not os.path.exists(p):
        return default
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(obj, open(p, "w", encoding="utf-8", newline="\n"), ensure_ascii=False, indent=1)


def norm_title(t):
    return re.sub(r"[\s\u3000]+", "", t or "")


def entry_url():
    """知网入口：优先 config/webvpn.json 的 cnki_entry。"""
    d = C.load("webvpn")
    e = (d.get("cnki_entry") or "").strip()
    if e:
        return e
    host = (d.get("host") or "").rstrip("/")
    return host


def wrap_detail(url):
    """把知网详情页 URL 包装成 WebVPN 可访问地址。"""
    if not url:
        return ""
    if "webvpn" in url:
        return url
    d = C.load("webvpn")
    h = (d.get("kns_hash") or "").strip()
    entry = (d.get("cnki_entry") or "")
    host = (d.get("host") or "").rstrip("/")
    if not h and "/https/" in entry:
        m = re.search(r"/https/([0-9a-f]+)/", entry)
        h = m.group(1) if m else ""
    if not (host and h):
        return ""
    m = re.match(r"https?://[^/]+(/.*)?$", url)
    path = (m.group(1) if m and m.group(1) else "/")
    return "%s/https/%s%s" % (host, h, path)


def bad_abstract(ab):
    a = (ab or "").strip()
    return a.startswith("中国知网知识发现网络平台") or "面向海内外读者提供中国学术文献" in a


# ------------------------------------------------------------------ toc
def scan_toc(ctx, navi, name):
    navi.fill("#txt_1_value1", name)
    navi.wait_for_timeout(random.uniform(1200, 2200))
    navi.click("#btnSearch")
    navi.wait_for_timeout(6000)
    if navi.evaluate(SLIDER_JS):
        return None, "blocked_slider"
    navi.click('li[productcode="ZNZEND0A"] a')
    navi.wait_for_timeout(5000)
    if navi.evaluate(SLIDER_JS):
        return None, "blocked_slider"
    before = len(ctx.pages)
    hit = navi.evaluate("""(j) => {
      const as = [...document.querySelectorAll('a')]
        .filter(e => (e.innerText || '').trim().startsWith(j));
      if (!as.length) return null;
      as[0].click();
      return (as[0].innerText || '').trim().slice(0, 40);
    }""", name)
    if not hit:
        return None, "no_hit"
    navi.wait_for_timeout(9000)
    pages = ctx.pages
    detail = pages[-1] if len(pages) > before else navi
    try:
        detail.wait_for_load_state("domcontentloaded", timeout=30000)
    except Exception:
        pass
    detail.wait_for_timeout(4000)
    if detail.evaluate(SLIDER_JS):
        detail.close()
        return None, "blocked_slider"
    issue = detail.evaluate(ISSUE_TXT)
    rows = detail.evaluate(EXTRACT_TOC)
    if not issue:
        y = detail.evaluate(r"""() => {
          const ys = [...document.querySelectorAll('a,li,span,div')]
            .filter(e => /^\d{4}$/.test((e.innerText || '').trim()))
            .map(e => ({el: e, y: parseInt((e.innerText || '').trim(), 10)}))
            .filter(o => o.y >= 2015 && o.y <= 2035);
          if (!ys.length) return null;
          ys.sort((a, b) => b.y - a.y); ys[0].el.click(); return ys[0].y;
        }""")
        if y:
            detail.wait_for_timeout(3500)
            no = detail.evaluate(r"""() => {
              const it = [...document.querySelectorAll('a,li,span,div')]
                .filter(e => /^No\.\d{1,2}$/.test((e.innerText || '').trim()))
                .map(e => ({el: e, n: parseInt((e.innerText || '').trim().replace('No.', ''), 10)}));
              if (!it.length) return null;
              it.sort((a, b) => b.n - a.n); it[0].el.click(); return it[0].n;
            }""")
            if no:
                detail.wait_for_timeout(6000)
                issue = detail.evaluate(ISSUE_TXT)
                rows2 = detail.evaluate(EXTRACT_TOC)
                if rows2:
                    rows = rows2
    url = detail.url
    detail.close()
    navi.wait_for_timeout(1200)
    return {"journal": name, "issue": issue, "url": url, "rows": rows}, "ok"


def cmd_toc(a):
    from playwright.sync_api import sync_playwright  # noqa: E402
    names = [x.strip() for x in a.journals.split(",") if x.strip()] if a.journals else \
        [j.get("name") for j in C.journals("cn")]
    if not names:
        print(json.dumps({"ok": False, "detail": "未提供刊名，且 profile.journals_cn 为空"},
                         ensure_ascii=False))
        return
    ok, msg = webvpn.ensure()
    if not ok:
        print(json.dumps({"ok": False, "detail": "WebVPN 不可用：%s" % msg}, ensure_ascii=False))
        return
    result = {"ts": now_iso(), "journals": [], "errors": [], "stopped": False}
    with sync_playwright() as p:
        b = cnki_browser.launch(p)
        ctx = cnki_browser.new_context(b, cookies=webvpn.browser_cookies(),
                                       viewport={"width": 1400, "height": 950})
        pg = ctx.new_page()
        pg.goto(entry_url(), timeout=90000, wait_until="domcontentloaded")
        pg.wait_for_timeout(3000)
        pg.query_selector("text=出版物检索").click()
        pg.wait_for_timeout(6000)
        navi = ctx.pages[-1]
        navi.wait_for_load_state("domcontentloaded")
        navi.wait_for_timeout(3000)
        for i, name in enumerate(names[:a.limit]):
            if "/login" in (navi.url or ""):
                result["stopped"] = True
                result["errors"].append({"journal": name, "reason": "vpn_session_expired"})
                break
            try:
                ent, st = scan_toc(ctx, navi, name)
            except Exception as e:
                ent, st = None, "error:%s:%s" % (type(e).__name__, str(e)[:160])
            if st != "ok":
                result["errors"].append({"journal": name, "reason": st})
                if st == "blocked_slider":
                    result["stopped"] = True
                    break
            else:
                result["journals"].append(ent)
            if i < min(len(names), a.limit) - 1:
                time.sleep(random.uniform(20, 40))
        b.close()
    outp = os.path.join(C.STATE, "cnki_toc_%s.json" % today())
    old = load_json(outp, None)
    if old:
        have = {j["journal"] for j in old.get("journals", [])}
        for j in result["journals"]:
            if j["journal"] not in have:
                old["journals"].append(j)
        old["errors"] = (old.get("errors") or []) + result["errors"]
        old["ts"] = result["ts"]
        result = old
    save_json(outp, result)
    print(json.dumps({"ok": True, "path": outp,
                      "journals": [{"journal": x["journal"], "issue": x.get("issue"),
                                    "n": len(x.get("rows") or [])} for x in result["journals"]],
                      "errors": result["errors"]}, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ meta
def cmd_meta(a):
    from playwright.sync_api import sync_playwright  # noqa: E402
    toc_path = a.toc or os.path.join(C.STATE, "cnki_toc_%s.json" % today())
    toc = load_json(toc_path, None)
    if not toc:
        print(json.dumps({"ok": False, "detail": "目录文件不存在：%s（先跑 toc）" % toc_path},
                         ensure_ascii=False))
        return
    targets = []
    for j in toc.get("journals", []):
        for r in (j.get("rows") or []):
            targets.append({"journal": j.get("journal"), "issue": j.get("issue"),
                            "section": r.get("section"), "title": r.get("title"),
                            "authors": r.get("authors"), "pages": r.get("pages"),
                            "href": r.get("href")})
    if not targets:
        print(json.dumps({"ok": False, "detail": "目录无条目"}, ensure_ascii=False))
        return
    meta_path = os.path.join(C.STATE, "cnki_meta_%s.json" % today())
    store = load_json(meta_path, {"ts": now_iso(), "items": []})
    store["items"] = [i for i in (store.get("items") or []) if not bad_abstract(i.get("abstract"))]
    done = {norm_title(i.get("title")) for i in store["items"] if i.get("status") == "ok"}
    todo = [t for t in targets if norm_title(t["title"]) not in done][:a.limit]
    if not todo:
        print(json.dumps({"ok": True, "detail": "全部已抓过，无需重复", "path": meta_path},
                         ensure_ascii=False))
        return
    ok, msg = webvpn.ensure()
    if not ok:
        print(json.dumps({"ok": False, "detail": "WebVPN 不可用：%s" % msg}, ensure_ascii=False))
        return
    result = {"items": [], "errors": [], "stopped": False}
    with sync_playwright() as p:
        b = cnki_browser.launch(p)
        ctx = cnki_browser.new_context(b, cookies=webvpn.browser_cookies(),
                                       viewport={"width": 1400, "height": 950})
        pg = ctx.new_page()
        try:
            pg.goto(entry_url(), timeout=90000, wait_until="domcontentloaded")
            pg.wait_for_timeout(5000)
            if pg.evaluate(SLIDER_JS):
                print(json.dumps({"ok": False, "detail": "预热即被滑块拦截，本次不抓取"},
                                 ensure_ascii=False))
                b.close()
                return
        except Exception as e:
            print("  [warn] 预热失败：%s" % str(e)[:100], flush=True)
        for n, t in enumerate(todo, 1):
            url = wrap_detail(t.get("href") or "")
            if not url:
                result["errors"].append({"title": t["title"], "reason": "url_not_wrappable"})
                continue
            try:
                pg.goto(url, timeout=90000, wait_until="domcontentloaded")
                pg.wait_for_timeout(4500)
                try:
                    pg.wait_for_selector("#ChDivSummary, .abstract-text, div.brief", timeout=15000)
                except Exception:
                    pass
                if pg.evaluate(SLIDER_JS):
                    result["errors"].append({"title": t["title"], "reason": "blocked_slider"})
                    result["stopped"] = True
                    break
                data = pg.evaluate(EXTRACT_META) or {}
            except Exception as e:
                result["errors"].append({"title": t["title"],
                                         "reason": "error:%s:%s" % (type(e).__name__, str(e)[:120])})
                continue
            data["page_title"] = pg.title()
            if bad_abstract(data.get("abstract")):
                data["abstract"] = ""
            item = dict(t)
            item.update(data)
            item["status"] = "ok" if (data.get("abstract") or data.get("keywords")) else "empty_meta"
            item["fetched_at"] = now_iso()
            result["items"].append(item)
            print("  [%d/%d] %s -> %s" % (n, len(todo), t["title"][:28], item["status"]), flush=True)
            if n < len(todo):
                time.sleep(random.uniform(max(6.0, a.delay * 0.7), a.delay * 1.3))
        b.close()
    have = {norm_title(i.get("title")) for i in store["items"]}
    for it in result["items"]:
        k = norm_title(it.get("title"))
        if k in have:
            for i, old in enumerate(store["items"]):
                if norm_title(old.get("title")) == k:
                    store["items"][i] = it
                    break
        else:
            store["items"].append(it)
    store["ts"] = now_iso()
    save_json(meta_path, store)
    print(json.dumps({"ok": True, "path": meta_path,
                      "n_ok": sum(1 for i in result["items"] if i["status"] == "ok"),
                      "n_empty": sum(1 for i in result["items"] if i["status"] == "empty_meta"),
                      "errors": result["errors"], "stopped": result["stopped"],
                      "n_store": len(store["items"])}, ensure_ascii=False, indent=1))


def cmd_run(a):
    cmd_toc(a)
    cmd_meta(a)


def main():
    ap = argparse.ArgumentParser(description="知网目录发现与元数据抓取（不下载 PDF）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("toc")
    p.add_argument("--journals", default="", help="逗号分隔刊名；缺省用 profile.journals_cn")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(func=cmd_toc)

    p = sub.add_parser("meta")
    p.add_argument("--toc", default="")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--delay", type=float, default=12.0)
    p.set_defaults(func=cmd_meta)

    p = sub.add_parser("run")
    p.add_argument("--journals", default="")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--toc", default="")
    p.add_argument("--meta-limit", type=int, default=30)
    p.add_argument("--delay", type=float, default=12.0)
    p.set_defaults(func=cmd_run)

    a = ap.parse_args()
    C.ensure_dirs()
    a.func(a)


if __name__ == "__main__":
    main()
