# -*- coding: utf-8 -*-
"""SMTP 发信（无任何内置账号：全部来自 config/smtp.json 或环境变量）。

用法
----
  python scripts/smtp_sender.py --check                      只验证登录，不发信
  python scripts/smtp_sender.py --subject "主题" --body-file outbox/x.html [--send]
  python scripts/smtp_sender.py --subject "测试" --body "你好" --send
"""
import argparse
import json
import os
import smtplib
import ssl
import sys
import time
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402

FROM_NAME = "学术文献监测"


def conf():
    d = C.load("smtp")
    if not (d.get("host") and d.get("user") and d.get("password")):
        raise RuntimeError("未配置 SMTP：运行 `python scripts/setup.py set smtp --host ... "
                           "--port 465 --user ... --password <授权码> --to ...`")
    try:
        d["port"] = int(d.get("port") or 465)
    except Exception:
        d["port"] = 465
    return d


def build_message(subject, body, to, cc, subtype, frm):
    msg = MIMEText(body, subtype, "utf-8")
    msg["From"] = formataddr((FROM_NAME, frm))
    msg["To"] = to if isinstance(to, str) else ", ".join(to)
    if cc:
        msg["Cc"] = cc if isinstance(cc, str) else ", ".join(cc)
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate(localtime=True)
    return msg


def send(subject, body, to=None, cc=None, subtype="html", retries=1):
    c = conf()
    to = to or c.get("to") or c["user"]
    cc = cc or c.get("cc")
    rcpts = [to] if isinstance(to, str) else list(to)
    cc_list = ([cc] if isinstance(cc, str) else list(cc or [])) if cc else []
    all_rcpt = rcpts + cc_list
    last = ""
    for attempt in range(retries + 1):
        try:
            with smtplib.SMTP_SSL(c["host"], c["port"],
                                  context=ssl.create_default_context(), timeout=30) as s:
                s.login(c["user"], c["password"])
                s.sendmail(c["user"], all_rcpt,
                           build_message(subject, body, to, cc, subtype, c["user"]).as_string())
            return {"ok": True, "detail": "sent", "to": all_rcpt, "attempt": attempt + 1}
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, str(e)[:200])
            if attempt < retries:
                time.sleep(10)
    return {"ok": False, "detail": last, "to": all_rcpt}


def check():
    try:
        c = conf()
    except RuntimeError as e:
        return {"ok": False, "detail": str(e)}
    try:
        with smtplib.SMTP_SSL(c["host"], c["port"],
                              context=ssl.create_default_context(), timeout=30) as s:
            s.login(c["user"], c["password"])
        return {"ok": True, "detail": "%s@%s:%s 登录成功" % (C.mask(c["user"]), c["host"], c["port"])}
    except Exception as e:
        return {"ok": False, "detail": "%s: %s" % (type(e).__name__, str(e)[:200])}


def main():
    ap = argparse.ArgumentParser(description="SMTP 发信")
    ap.add_argument("--subject", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--to", default="")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.check:
        print(json.dumps(check(), ensure_ascii=False))
        return
    if a.body_file and os.path.exists(a.body_file):
        body = open(a.body_file, encoding="utf-8").read()
        subtype = "html" if a.body_file.lower().endswith((".html", ".htm")) else "plain"
    elif a.body:
        body, subtype = a.body, "plain"
    else:
        print(json.dumps({"ok": False, "detail": "缺少 --body / --body-file"}, ensure_ascii=False))
        return
    if not a.send:
        print(json.dumps({"ok": False, "detail": "未加 --send，未实际发送",
                          "subject": a.subject}, ensure_ascii=False))
        return
    print(json.dumps(send(a.subject or "(无主题)", body, to=a.to or None, subtype=subtype),
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
