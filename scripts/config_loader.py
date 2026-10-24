# -*- coding: utf-8 -*-
"""统一配置读取层：所有个人/机构信息都放在 skill 的 config/ 目录，代码里不内置任何私密值。

配置清单（全部由 `python scripts/setup.py` 在安装时生成）
------------------------------------------------------
  config/profile.json   研究方向、关键词、在研项目、期刊清单、评分阈值   ← 必填
  config/smtp.json      发信邮箱 SMTP（host/port/user/授权码/收件人）    ← 邮件通知必填
  config/webvpn.json    学校/单位 WebVPN（host/账号/密码/知网入口）      ← 中文知网监测必填
  config/openalex.json  OpenAlex api_key / mailto                       ← 英文监测可选
  config/llm.json       大模型 provider/base_url/api_key/model           ← 深度解读可选
  config/feishu.json    飞书应用凭据 / 日历或任务表 token                ← 可选

读取规则
--------
1. 先读环境变量（SMTP_HOST / SMTP_USER ... / OPENALEX_API_KEY / LLM_API_KEY ...）
2. 再读 config/<name>.json
3. 都没有 → 返回空 dict，由调用方提示「请先运行 setup.py」

绝不把账号、授权码、API Key 写进代码或日志：打印时统一用 mask()。
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(BASE, "config")
DATA = os.path.join(BASE, "data")
STATE = os.path.join(BASE, "state")
OUTBOX = os.path.join(BASE, "outbox")
OUTPUTS = os.path.join(BASE, "outputs")

ENV_MAP = {
    "smtp": {"host": "SMTP_HOST", "port": "SMTP_PORT", "user": "SMTP_USER",
             "password": "SMTP_PASSWORD", "to": "SMTP_TO"},
    "openalex": {"api_key": "OPENALEX_API_KEY", "mailto": "OPENALEX_MAILTO"},
    "llm": {"api_key": "LLM_API_KEY", "base_url": "LLM_BASE_URL", "model": "LLM_MODEL",
            "provider": "LLM_PROVIDER"},
    "webvpn": {"host": "WEBVPN_HOST", "user": "WEBVPN_USER", "password": "WEBVPN_PASSWORD"},
    "feishu": {"app_id": "FEISHU_APP_ID", "app_secret": "FEISHU_APP_SECRET"},
}

SECRET_KEYS = {"password", "api_key", "app_secret", "token", "authorization", "key"}


def ensure_dirs():
    for d in (DATA, STATE, OUTBOX, OUTPUTS):
        os.makedirs(d, exist_ok=True)


def path(name):
    return os.path.join(CONFIG, "%s.json" % name)


def exists(name):
    return os.path.exists(path(name))


def load(name, default=None):
    """读取配置；不存在返回 default。环境变量优先级更高。"""
    d = dict(default or {})
    if exists(name):
        try:
            with open(path(name), encoding="utf-8") as f:
                d.update({k: v for k, v in json.load(f).items() if v not in (None, "")})
        except Exception:
            pass
    for k, env in (ENV_MAP.get(name) or {}).items():
        if os.environ.get(env):
            d[k] = os.environ[env]
    return d


def require(name, keys=None, hint=""):
    """必需配置：缺失直接抛 SetupNeeded，避免脚本带着空配置静默跑。"""
    d = load(name)
    if not d:
        raise SetupNeeded("缺少 config/%s.json —— 请先运行 `python scripts/setup.py`%s"
                          % (name, ("（%s）" % hint) if hint else ""))
    if keys:
        miss = [k for k in keys if not d.get(k)]
        if miss:
            raise SetupNeeded("config/%s.json 缺少字段 %s —— 请运行 `python scripts/setup.py` 补填"
                              % (name, "/".join(miss)))
    return d


class SetupNeeded(Exception):
    pass


def mask(v):
    v = str(v or "")
    if len(v) <= 4:
        return "*" * len(v)
    return v[:2] + "*" * (len(v) - 4) + v[-2:]


def public_view(name):
    """打印配置概览（敏感字段打码），用于 setup --check / 故障排查。"""
    d = load(name)
    return {k: (mask(v) if k in SECRET_KEYS else v) for k, v in d.items()}


def save(name, obj):
    os.makedirs(CONFIG, exist_ok=True)
    with open(path(name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return path(name)


# ------------------------------------------------------------------ profile
def profile():
    return load("profile")


def directions():
    """研究方向列表：[{code, name, keywords_en, keywords_zh, ...}]"""
    p = profile()
    ds = p.get("directions") or {}
    out = []
    if isinstance(ds, dict):
        for code, v in ds.items():
            v = dict(v)
            v.setdefault("code", code)
            out.append(v)
    else:
        out = [dict(x) for x in ds]
    return out


def projects():
    p = profile()
    ps = p.get("projects") or {}
    if isinstance(ps, dict):
        return [dict(v, id=k) for k, v in ps.items()]
    return [dict(x) for x in ps]


def scoring():
    p = profile()
    s = p.get("scoring") or {}
    return {
        "weights": s.get("weights") or {"d1_research_match": 0.35, "d2_theory_transfer": 0.20,
                                        "d3_method_value": 0.20, "d5_writing_help": 0.15,
                                        "d7_maturity": 0.10},
        "thresholds": s.get("thresholds") or {"critical": 90, "high": 75, "recommended": 60},
    }


def journals(kind="en"):
    """期刊清单：[{name, issn, tier}]，kind = en | cn"""
    p = profile()
    key = "journals_en" if kind == "en" else "journals_cn"
    return [dict(x) for x in (p.get(key) or [])]


def journal_tier(name):
    p = profile()
    for j in (p.get("journals_en") or []) + (p.get("journals_cn") or []):
        if (j.get("name") or "").strip() == (name or "").strip():
            return float(j.get("tier") or 70)
    return float((p.get("scoring") or {}).get("default_journal_tier", 70))
