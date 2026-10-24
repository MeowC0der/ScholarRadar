#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""安装向导 / 配置自检 —— 首次安装本 Skill 后必须先跑它。

本 Skill 不含任何个人信息：邮箱、学校 WebVPN、研究方向、OpenAlex Key、大模型 Key、
飞书凭据，全部由安装者本人填写，落盘到 skill 目录下 config/*.json（仅本机可见）。

子命令
------
  wizard                交互问答式配置（人在终端时推荐）
  status                查看各项配置是否已填写（敏感值打码）
  check                 连通性自检：SMTP 登录 / OpenAlex / 学校 WebVPN / 大模型 / 飞书
  set smtp|webvpn|openalex|llm|feishu [--key value ...]   非交互写入（Agent 代填推荐）
  set-profile --file x.json                               直接导入研究方向配置
  gen-profile           交互式生成 config/profile.json（研究方向 / 项目 / 期刊）

示例（Agent 收集到用户信息后写入）
--------------------------------
  python scripts/setup.py set smtp --host smtp.example.com --port 465 \
      --user you@example.com --password <授权码> --to you@example.com
  python scripts/setup.py set webvpn --host webvpn.xxx.edu.cn --user 学号 \
      --password <密码> --cnki-entry https://webvpn.xxx.edu.cn/https/<hash>/
  python scripts/setup.py set openalex --api-key <key> --mailto you@example.com
  python scripts/setup.py set llm --provider openai-compatible \
      --base-url https://api.xxx.com/v1 --api-key <key> --model gpt-4o-mini
  python scripts/setup.py check
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "scripts"))
import config_loader as C  # noqa: E402

ensure = C.ensure_dirs

SPEC = {
    "smtp": (["host", "port", "user", "password", "to", "cc"],
             "发信邮箱 SMTP（用于每日/每周监测邮件）"),
    "webvpn": (["host", "user", "password", "cnki_entry", "kns_hash"],
               "学校/单位 WebVPN（用于知网中文文献监测）"),
    "openalex": (["api_key", "mailto"], "OpenAlex API（英文文献检索）"),
    "llm": (["provider", "base_url", "api_key", "model"], "大模型（深度解读 / 摘要翻译）"),
    "feishu": (["app_id", "app_secret", "calendar_id", "base_token", "table_id"],
               "飞书（可选：日历 / 任务表联动）"),
}


def ask(prompt, default="", secret=False):
    tip = "（直接回车跳过）" if not default else "（回车用默认：%s）" % default
    v = input("%s %s: " % (prompt, tip)).strip()
    if not v:
        return default
    return v


# ------------------------------------------------------------------ 非交互写入
def cmd_set(a):
    if a.what not in SPEC:
        print(json.dumps({"ok": False, "detail": "未知配置项 %s，可选：%s"
                          % (a.what, "/".join(SPEC))}, ensure_ascii=False))
        return
    kv = {}
    for i in range(0, len(a.pairs), 2):
        kv[a.pairs[i].lstrip("-").replace("-", "_")] = a.pairs[i + 1]
    if not kv:
        print(json.dumps({"ok": False, "detail": "未提供任何字段", "fields": SPEC[a.what][0]},
                         ensure_ascii=False))
        return
    cur = C.load(a.what)
    cur.update(kv)
    p = C.save(a.what, cur)
    print(json.dumps({"ok": True, "saved": p, "fields": sorted(cur),
                      "view": C.public_view(a.what)}, ensure_ascii=False, indent=1))


def cmd_set_profile(a):
    if not a.file or not os.path.exists(a.file):
        print(json.dumps({"ok": False, "detail": "请提供存在的 profile JSON：--file xxx.json"},
                         ensure_ascii=False))
        return
    d = json.load(open(a.file, encoding="utf-8"))
    p = C.save("profile", d)
    print(json.dumps({"ok": True, "saved": p,
                      "n_directions": len(C.directions()),
                      "n_projects": len(C.projects()),
                      "n_journals_en": len(C.journals("en")),
                      "n_journals_cn": len(C.journals("cn"))}, ensure_ascii=False))


# ------------------------------------------------------------------ 交互式生成 profile
def cmd_gen_profile(a):
    print("\n=== 研究方向与关注主题（这是评分引擎的唯一输入，决定什么文献会被推给你）===")
    print("提示：关键词越具体，监测越准；中英文都填效果最好。\n")
    directions = {}
    n = ask("你要设几个研究方向？", "2")
    try:
        n = max(1, min(8, int(n)))
    except Exception:
        n = 2
    for i in range(n):
        code = chr(ord("A") + i)
        print("\n--- 方向 %s ---" % code)
        name = ask("方向名称（如：数字技术与国家能力）", "")
        if not name:
            continue
        kws_en = ask("英文关键词（英文分号或逗号分隔）", "")
        kws_zh = ask("中文关键词（中文分号或逗号分隔）", "")
        prio = ask("优先级 highest/high/medium/low", "medium")
        thr = ask("该方向的提醒阈值（默认 75）", "75")
        try:
            thr = float(thr)
        except Exception:
            thr = 75.0
        directions[code] = {
            "code": code, "name_zh": name, "name_en": name, "priority": prio,
            "alert_threshold_override": thr,
            "keywords_en": [x.strip() for x in _split(kws_en)],
            "keywords_zh": [x.strip() for x in _split(kws_zh)],
            "research_questions": [],
        }

    print("\n=== 在研项目（可选，命中项目关键词会加分并打标签）===")
    projects = {}
    np_ = ask("在研项目数量", "0")
    try:
        np_ = max(0, min(10, int(np_)))
    except Exception:
        np_ = 0
    for i in range(np_):
        pid = "P%d" % (i + 1)
        name = ask("项目 %s 名称" % pid, "")
        if not name:
            continue
        kws = ask("项目关键词（中英文均可，分号分隔）", "")
        projects[pid] = {"id": pid, "name": name,
                         "keywords_zh": [x.strip() for x in _split(kws)],
                         "keywords_en": []}

    print("\n=== 期刊清单（留空可稍后补；也可用 `python scripts/journals.py add --name ...`）===")
    journals_en, journals_cn = [], []
    je = ask("英文期刊（分号分隔）", "")
    for name in _split(je):
        journals_en.append({"name": name.strip(), "issn": "", "tier": 70})
    jc = ask("中文期刊（分号分隔，需知网可检索到）", "")
    for name in _split(jc):
        journals_cn.append({"name": name.strip(), "issn": "", "tier": 70})

    profile = {
        "profile_version": "1.0.0",
        "owner": ask("使用者称呼（用于邮件抬头，可留空）", ""),
        "theme": {"zh": ask("一句话概括你的研究主题", ""), "en": ""},
        "directions": directions,
        "projects": projects,
        "journals_en": journals_en,
        "journals_cn": journals_cn,
        "negative_keywords": {"en": [], "zh": []},
        "scoring": {
            "weights": {"d1_research_match": 0.35, "d2_theory_transfer": 0.20,
                        "d3_method_value": 0.20, "d5_writing_help": 0.15,
                        "d7_maturity": 0.10},
            "thresholds": {"critical": 90, "high": 75, "recommended": 60},
            "default_journal_tier": 70,
        },
    }
    p = C.save("profile", profile)
    print("\n已写入 %s" % p)
    print(json.dumps({"ok": True, "n_directions": len(directions),
                      "n_projects": len(projects),
                      "n_journals_en": len(journals_en),
                      "n_journals_cn": len(journals_cn)}, ensure_ascii=False))


def _split(s):
    if not s:
        return []
    s = s.replace("；", ";").replace("，", ",").replace("、", ",")
    out = []
    for part in s.replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.append(part)
    return out


# ------------------------------------------------------------------ 交互向导（全量）
def cmd_wizard(a):
    print("=== 学术文献监测 Skill · 安装向导 ===")
    print("所有信息只保存在本机 skill 目录的 config/ 下，不会写入代码、不会外传。\n")
    if not C.exists("profile") or ask("重新配置研究方向与期刊？y/N", "N").lower() == "y":
        cmd_gen_profile(a)
    print("\n=== 发信邮箱（SMTP）===")
    print("国内邮箱一般用「授权码」而非登录密码：126/163 在 设置→POP3/SMTP 里获取，QQ 邮箱同理。")
    smtp = {
        "host": ask("SMTP 服务器", "smtp.example.com"),
        "port": ask("端口", "465"),
        "user": ask("邮箱账号", ""),
        "password": ask("授权码/密码", ""),
        "to": ask("收件人（默认同账号）", ""),
    }
    if not smtp["to"]:
        smtp["to"] = smtp["user"]
    if smtp["user"] and smtp["password"]:
        C.save("smtp", smtp)
    print("\n=== 学校/单位 WebVPN（中文知网监测用；不用中文监测可跳过）===")
    wv = {
        "host": ask("WebVPN 域名", ""),
        "user": ask("账号", ""),
        "password": ask("密码", ""),
        "cnki_entry": ask("知网入口 URL（可留空，登录后自动探测）", ""),
        "kns_hash": ask("知网主机 hash（可留空）", ""),
    }
    if wv["host"] and wv["user"]:
        C.save("webvpn", wv)
    print("\n=== OpenAlex（英文文献检索；可留空，留空走免费 polite pool）===")
    oa = {"api_key": ask("OpenAlex API Key", ""), "mailto": ask("联系邮箱", smtp.get("user", ""))}
    if oa["api_key"] or oa["mailto"]:
        C.save("openalex", oa)
    print("\n=== 大模型（深度解读 / 摘要翻译；可留空，留空则只做结构化摘要）===")
    llm = {"provider": ask("provider", "openai-compatible"),
           "base_url": ask("base_url", ""),
           "api_key": ask("API Key", ""),
           "model": ask("模型名", "")}
    if llm["api_key"]:
        C.save("llm", llm)
    print("\n=== 飞书（可选：日历 / 任务表联动）===")
    fs = {"app_id": ask("App ID", ""), "app_secret": ask("App Secret", ""),
          "calendar_id": ask("日历 ID", ""), "base_token": ask("多维表格 token", ""),
          "table_id": ask("数据表 id", "")}
    if fs["app_id"]:
        C.save("feishu", fs)
    print("\n配置完成，运行 `python scripts/setup.py check` 做连通性自检。")


# ------------------------------------------------------------------ 状态与自检
def cmd_status(a):
    out = {"skill_dir": BASE}
    for k in ("profile", "smtp", "webvpn", "openalex", "llm", "feishu"):
        d = C.load(k)
        if k == "profile":
            out[k] = {"ready": bool(C.directions()),
                      "n_directions": len(C.directions()),
                      "n_projects": len(C.projects()),
                      "n_journals_en": len(C.journals("en")),
                      "n_journals_cn": len(C.journals("cn"))}
        else:
            out[k] = {"ready": bool(d), "fields": C.public_view(k)}
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_check(a):
    res = {"ts": _now()}
    # 1) profile
    try:
        ds = C.directions()
        res["profile"] = {"ok": bool(ds), "n_directions": len(ds)}
    except Exception as e:
        res["profile"] = {"ok": False, "detail": str(e)}
    # 2) smtp
    smtp = C.load("smtp")
    if smtp.get("user") and smtp.get("password"):
        try:
            import smtplib
            import ssl
            with smtplib.SMTP_SSL(smtp.get("host", ""), int(smtp.get("port", 465)),
                                  context=ssl.create_default_context(), timeout=30) as s:
                s.login(smtp["user"], smtp["password"])
            res["smtp"] = {"ok": True, "user": C.mask(smtp["user"])}
        except Exception as e:
            res["smtp"] = {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:160])}
    else:
        res["smtp"] = {"ok": False, "detail": "未配置（运行 setup wizard 或 set smtp）"}
    # 3) openalex
    oa = C.load("openalex")
    try:
        import urllib.request
        url = "https://api.openalex.org/works?filter=title.search:test&per-page=1"
        if oa.get("mailto"):
            url += "&mailto=" + oa["mailto"]
        if oa.get("api_key"):
            url += "&api_key=" + oa["api_key"]
        with urllib.request.urlopen(url, timeout=25) as r:
            j = json.loads(r.read().decode("utf-8"))
        res["openalex"] = {"ok": True, "works": (j.get("meta") or {}).get("count"),
                           "with_key": bool(oa.get("api_key"))}
    except Exception as e:
        res["openalex"] = {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:160])}
    # 4) webvpn
    wv = C.load("webvpn")
    if wv.get("host") and wv.get("user"):
        try:
            sys.path.insert(0, os.path.join(BASE, "scripts"))
            import webvpn
            ok, msg, cookies = webvpn.http_login(wv["user"], wv["password"],
                                                 host=wv["host"])
            res["webvpn"] = {"ok": ok, "detail": msg[:200],
                             "host": wv["host"], "n_cookies": len(cookies or {})}
        except Exception as e:
            res["webvpn"] = {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:160])}
    else:
        res["webvpn"] = {"ok": False, "detail": "未配置（不做中文知网监测可忽略）"}
    # 5) llm
    llm = C.load("llm")
    if llm.get("api_key") and llm.get("base_url"):
        try:
            import urllib.request
            req = urllib.request.Request(
                llm["base_url"].rstrip("/") + "/models",
                headers={"Authorization": "Bearer " + llm["api_key"]})
            with urllib.request.urlopen(req, timeout=25) as r:
                r.read(500)
            res["llm"] = {"ok": True, "model": llm.get("model")}
        except Exception as e:
            res["llm"] = {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:160])}
    else:
        res["llm"] = {"ok": False, "detail": "未配置（不做大模型深度解读可忽略）"}
    # 6) feishu
    fs = C.load("feishu")
    res["feishu"] = {"ok": bool(fs.get("app_id") and fs.get("app_secret")),
                     "detail": "已配置" if fs.get("app_id") else "未配置（可选）"}
    print(json.dumps(res, ensure_ascii=False, indent=1))


def _now():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def main():
    ap = argparse.ArgumentParser(description="学术文献监测 Skill 安装向导 / 自检")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("set")
    p.add_argument("what", choices=list(SPEC))
    p.add_argument("pairs", nargs=argparse.REMAINDER,
                   help="--字段名 值 成对出现（--user me@x.com --password xxx）")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("set-profile")
    p.add_argument("--file", default="")
    p.set_defaults(func=cmd_set_profile)

    p = sub.add_parser("gen-profile")
    p.set_defaults(func=cmd_gen_profile)

    sub.add_parser("wizard").set_defaults(func=cmd_wizard)
    sub.add_parser("status").set_defaults(func=cmd_status)
    sub.add_parser("check").set_defaults(func=cmd_check)

    a = ap.parse_args()
    C.ensure_dirs()
    a.func(a)


if __name__ == "__main__":
    main()
