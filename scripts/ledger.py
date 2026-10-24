#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""文献台账：把监测到的文献汇总成一份 CSV，并同步到 WorkBuddy 资料库（同一节点覆盖更新）。

设计要点
--------
1. 只收录**实际抓到**的字段，缺啥留空，绝不推测。
2. CSV 是「全量快照」：每次 build 重建，历史行保留（按 id/DOI/题名去重）。
3. 资料库同步走 library skill 的 import_csv.py：首次导入建节点并把 node_block_id 记进
   state/library_ledger.json，之后每次用 --database-id 覆盖重导入**同一节点**，不会堆重复文件。
4. 没装 library skill（或不在 WorkBuddy 环境）时，push 跳过并如实报告，不影响本地 CSV。

子命令
------
  build [--out 路径] [--min-score N] [--abstract-len 500]
  push  [--csv 路径] [--dry]        同步到资料库
  status                            查看本地 CSV 与资料库节点状态
"""
import argparse
import csv
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402

TZ = timezone(timedelta(hours=8))
DEFAULT_CSV = os.path.join(C.OUTPUTS, "文献监测台账.csv")
LEDGER_STATE = os.path.join(C.STATE, "library_ledger.json")

LIB_ROOT_CANDIDATES = [
    os.path.join(os.path.expanduser("~"), ".workbuddy", "plugins", "cache", "workbuddy-builtin",
                 "skills", "library"),
    r"D:\LenovoSoftstore\Install\WorkBuddy\resources\app.asar.unpacked\resources\plugins"
    r"\workbuddy-builtin\skills\library",
]

LEVEL_CN = {"critical": "重点必读", "high": "高度相关",
            "recommended": "一般相关", "archive": "仅索引"}

COLUMNS = ["序号", "来源", "标题", "作者", "期刊", "出版时间", "卷期", "页码", "DOI",
           "链接", "摘要", "关键词", "评分", "等级", "研究方向", "关联项目", "研究设计",
           "推荐理由", "首次发现", "最近更新", "状态"]


def now_iso():
    return datetime.now(TZ).isoformat(timespec="seconds")


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


def collect_rows():
    """汇总中英文两个队列（data/cnki_watch.json + data/en_watch.json）。"""
    rows = []
    cn = load_json(os.path.join(C.DATA, "cnki_watch.json"), {"items": []})
    for it in cn.get("items") or []:
        sd = it.get("score_detail") or {}
        rows.append({
            "来源": "中文（知网）",
            "标题": it.get("title") or "",
            "作者": (it.get("authors") or "").strip(";；"),
            "期刊": it.get("journal") or "",
            "出版时间": it.get("pub_date") or it.get("year") or "",
            "卷期": it.get("issue") or "",
            "页码": it.get("pages") or "",
            "DOI": it.get("doi") or "",
            "链接": it.get("url") or "",
            "摘要": it.get("abstract") or "",
            "关键词": "；".join(it.get("keywords") or []),
            "评分": it.get("score") if it.get("score") is not None else "",
            "等级": LEVEL_CN.get(sd.get("alert_level"), ""),
            "研究方向": "/".join(sd.get("directions") or []),
            "关联项目": "；".join(sd.get("project_names") or []),
            "研究设计": sd.get("evidence_design") or "",
            "推荐理由": sd.get("recommend_reason") or "",
            "首次发现": it.get("added_at") or "",
            "最近更新": it.get("updated_at") or "",
            "状态": it.get("status") or "",
        })
    en = load_json(os.path.join(C.DATA, "en_watch.json"), {"items": []})
    for it in en.get("items") or []:
        sd = it.get("score_detail") or {}
        rows.append({
            "来源": "英文（OpenAlex）",
            "标题": it.get("title_en") or it.get("title") or "",
            "作者": "；".join(it.get("authors") or []) if isinstance(it.get("authors"), list)
                   else (it.get("authors") or ""),
            "期刊": it.get("journal_name") or "",
            "出版时间": it.get("published_date") or "",
            "卷期": "Vol.%s No.%s" % (it.get("volume") or "-", it.get("issue") or "-"),
            "页码": it.get("pages") or "",
            "DOI": it.get("doi") or "",
            "链接": it.get("url") or "",
            "摘要": it.get("abstract_en") or "",
            "关键词": "；".join(str(x) for x in (it.get("keywords") or []) if x)
                   if isinstance(it.get("keywords"), list) else (it.get("keywords") or ""),
            "评分": it.get("score") if it.get("score") is not None else "",
            "等级": LEVEL_CN.get(sd.get("alert_level"), ""),
            "研究方向": "/".join(sd.get("directions") or []),
            "关联项目": "；".join(sd.get("project_names") or []),
            "研究设计": sd.get("evidence_design") or "",
            "推荐理由": sd.get("recommend_reason") or "",
            "首次发现": it.get("added_at") or "",
            "最近更新": it.get("updated_at") or "",
            "状态": it.get("status") or "",
        })
    return rows


def cmd_build(a):
    rows = collect_rows()
    if a.min_score:
        rows = [r for r in rows if (r["评分"] or 0) >= a.min_score]
    rows.sort(key=lambda r: -(r["评分"] if isinstance(r["评分"], (int, float)) else 0))
    out = a.out or DEFAULT_CSV
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for i, r in enumerate(rows, 1):
            r = dict(r)
            ab = (r.get("摘要") or "")
            if len(ab) > a.abstract_len:
                ab = ab[:a.abstract_len] + "…"
            r["摘要"] = ab
            rs = (r.get("推荐理由") or "")
            r["推荐理由"] = rs[:a.reason_len]
            r["序号"] = i
            w.writerow({k: r.get(k, "") for k in COLUMNS})
    n_cn = sum(1 for r in rows if r["来源"].startswith("中文"))
    print(json.dumps({"ok": True, "csv": out, "rows": len(rows),
                      "n_cn": n_cn, "n_en": len(rows) - n_cn,
                      "n_high": sum(1 for r in rows
                                    if isinstance(r["评分"], (int, float)) and r["评分"] >= 75)},
                     ensure_ascii=False))


def find_library():
    for p in LIB_ROOT_CANDIDATES:
        if os.path.exists(os.path.join(p, "database", "import_csv.py")):
            return p
    return None


def cmd_push(a):
    csv_path = a.csv or DEFAULT_CSV
    if not os.path.exists(csv_path):
        print(json.dumps({"ok": False, "detail": "CSV 不存在，先跑 build：%s" % csv_path},
                         ensure_ascii=False))
        return
    lib = find_library()
    if not lib:
        print(json.dumps({"ok": False, "detail": "未找到 WorkBuddy library skill，跳过资料库同步；"
                                                 "本地 CSV 已就绪：%s" % csv_path}, ensure_ascii=False))
        return
    st = load_json(LEDGER_STATE, {})
    script = os.path.join(lib, "database", "import_csv.py")
    cmd = [sys.executable, script, csv_path]
    if st.get("database_id"):
        cmd += ["--database-id", st["database_id"]]
    else:
        if a.space_id:
            cmd += ["--space-id", a.space_id]
        if a.parent_id:
            cmd += ["--parent-id", a.parent_id]
    if a.dry:
        print(json.dumps({"ok": True, "dry": True, "cmd": cmd}, ensure_ascii=False))
        return
    r = subprocess.run(cmd, cwd=lib, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    out = (r.stdout or "").strip()
    res = {"ok": r.returncode == 0, "returncode": r.returncode,
           "stdout": out[-1200:], "stderr": (r.stderr or "")[-400:]}
    # 记录节点 id，供后续覆盖更新
    m = None
    txt = out
    try:
        j = json.loads(txt)
        m = (j.get("database_id") or j.get("node_block_id") or
             (j.get("data") or {}).get("database_id"))
        res["url"] = j.get("url") or (j.get("data") or {}).get("url")
    except Exception:
        import re
        mm = re.search(r'"(?:database_id|node_block_id)"\s*:\s*"([^"]+)"', txt)
        m = mm.group(1) if mm else None
    if m:
        st["database_id"] = m
        st["last_push"] = now_iso()
        st["csv"] = csv_path
        if res.get("url"):
            st["url"] = res["url"]
        save_json(LEDGER_STATE, st)
        res["database_id"] = m
    res["state"] = LEDGER_STATE
    print(json.dumps(res, ensure_ascii=False, indent=1))


def cmd_status(a):
    st = load_json(LEDGER_STATE, {})
    exists = os.path.exists(DEFAULT_CSV)
    rows = 0
    if exists:
        with open(DEFAULT_CSV, encoding="utf-8-sig") as f:
            rows = max(0, sum(1 for _ in f) - 1)
    print(json.dumps({"csv": DEFAULT_CSV, "csv_exists": exists, "csv_rows": rows,
                      "library": st, "library_skill": find_library()},
                     ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description="文献台账 CSV（本地 + 资料库）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build")
    p.add_argument("--out", default="")
    p.add_argument("--min-score", type=float, default=0)
    p.add_argument("--abstract-len", type=int, default=500)
    p.add_argument("--reason-len", type=int, default=300)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("push")
    p.add_argument("--csv", default="")
    p.add_argument("--space-id", default="")
    p.add_argument("--parent-id", default="")
    p.add_argument("--dry", action="store_true")
    p.set_defaults(func=cmd_push)

    sub.add_parser("status").set_defaults(func=cmd_status)

    a = ap.parse_args()
    C.ensure_dirs()
    a.func(a)


if __name__ == "__main__":
    main()
