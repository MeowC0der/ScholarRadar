# -*- coding: utf-8 -*-
"""通用高校/单位 WebVPN 登录与会话管理（深澜协议，国内高校最常见）。

本文件不含任何学校域名与账号：全部来自 config/webvpn.json（由 setup.py 生成）
或环境变量 WEBVPN_HOST / WEBVPN_USER / WEBVPN_PASSWORD。

流程：GET {host}/login 取 _csrf → POST {host}/do-login
      → 返回 NEED_CONFIRM 时再 POST {host}/do-confirm-login（会踢掉该账号其他 WebVPN 会话）
      → 成功后 cookies 存 state/webvpn_session.json，供浏览器注入 / requests 复用。

若你的学校不是深澜协议：仍可手工登录浏览器后把 cookies 写成
state/webvpn_session.json（{"cookies": {"name": "value"}}），脚本同样可用。

子命令：login / check
"""
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402

SESSION_FILE = os.path.join(C.STATE, "webvpn_session.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0")


def conf():
    d = C.load("webvpn")
    return d


def load_creds():
    d = conf()
    return d.get("host", ""), d.get("user", ""), d.get("password", "")


def http_login(user, pwd, host=None):
    """HTTP 层登录，返回 (ok, msg, cookies_dict)。host 缺省取配置。"""
    import requests
    host = (host or conf().get("host") or "").rstrip("/")
    if not host:
        return False, "未配置 WebVPN 域名（config/webvpn.json → host）", {}
    s = requests.Session()
    s.trust_env = False          # 校内域名直连，绕开系统代理（代理常导致误判）
    s.headers.update({"User-Agent": UA})
    r = s.get(host + "/login", timeout=30)
    m = re.search(r'name="_csrf"[^>]*value="([^"]+)"', r.text)
    if not m:
        return False, "登录页未找到 _csrf（可能不是深澜协议，请手工注入 cookies）", {}
    data = {"username": user, "password": pwd, "auth_type": "local",
            "needCaptcha": "false", "captcha_id": "", "captcha": "", "_csrf": m.group(1)}
    r2 = s.post(host + "/do-login", data=data, timeout=30)
    try:
        j = r2.json()
    except Exception:
        return False, "do-login 非 JSON: %s %s" % (r2.status_code, r2.text[:120]), {}
    if j.get("error") == "NEED_CONFIRM":
        r3 = s.post(host + "/do-confirm-login", data=data, timeout=30)
        try:
            j = r3.json()
        except Exception:
            return False, "do-confirm-login 非 JSON: %s" % r3.status_code, {}
    if not j.get("success"):
        return False, "登录失败: %s %s" % (j.get("error"), j.get("message", "")), {}
    r4 = s.get(host + "/", timeout=30)
    ok = r4.status_code == 200 and len(r4.text) > 3000
    return ok, "home len=%d" % len(r4.text), s.cookies.get_dict()


def save_session(cookies, user=""):
    os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
    json.dump({"user": user, "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "cookies": cookies},
              open(SESSION_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return SESSION_FILE


def load_session():
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        return json.load(open(SESSION_FILE, encoding="utf-8"))
    except Exception:
        return None


def session_valid(host=None, timeout=25):
    """已登录时访问 /login 会被 302 到首页。"""
    import requests
    d = load_session()
    if not d:
        return False
    host = (host or conf().get("host") or "").rstrip("/")
    if not host:
        return False
    s = requests.Session()
    s.trust_env = False
    s.headers.update({"User-Agent": UA})
    dom = host.split("://")[-1]
    for k, v in (d.get("cookies") or {}).items():
        s.cookies.set(k, v, domain=dom, path="/")
    try:
        r = s.get(host + "/login", timeout=timeout, allow_redirects=False)
        return r.status_code in (301, 302, 303, 307)
    except Exception:
        return False


def ensure(timeout=40):
    """确保会话可用，失效自动重登。返回 (ok, msg)"""
    if session_valid(timeout):
        return True, "existing session"
    host, user, pwd = load_creds()
    if not (host and user and pwd):
        return False, "缺少 WebVPN 配置（config/webvpn.json：host/user/password）"
    ok, msg, cookies = http_login(user, pwd, host=host)
    if ok:
        save_session(cookies, user)
        return True, "re-login ok"
    return False, msg


def browser_cookies():
    d = load_session() or {}
    host = conf().get("host", "")
    dom = host.split("://")[-1] or "localhost"
    return [{"name": k, "value": v, "domain": dom, "path": "/", "secure": True}
            for k, v in (d.get("cookies") or {}).items()]


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "login":
        host, user, pwd = load_creds()
        if not (user and pwd and host):
            print(json.dumps({"ok": False, "msg": "缺少凭据，先跑 setup.py set webvpn"},
                             ensure_ascii=False))
            return
        ok, msg, cookies = http_login(user, pwd, host=host)
        if ok:
            save_session(cookies, user)
        print(json.dumps({"ok": ok, "msg": msg, "saved": ok}, ensure_ascii=False))
    else:
        ok = session_valid()
        print(json.dumps({"alive": ok, "session_file": SESSION_FILE,
                          "host": conf().get("host", "")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
