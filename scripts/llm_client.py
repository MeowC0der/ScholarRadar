# -*- coding: utf-8 -*-
"""大模型客户端（OpenAI 兼容协议）——用于深度解读 / 摘要翻译，可选能力。

配置来自 config/llm.json：{"provider": "openai-compatible", "base_url": "...",
"api_key": "...", "model": "..."}（由 setup.py 填写）。未配置时所有函数返回 None，
调用方应降级为「只用结构化字段」，绝不伪造解读。

用法
----
  from llm_client import chat, deep_read
  deep_read(article_dict)  ->  一段结构化解读文本（或 None）
"""
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402


def conf():
    return C.load("llm")


def enabled():
    c = conf()
    return bool(c.get("api_key") and c.get("base_url"))


def chat(messages, model=None, temperature=0.2, max_tokens=2000, timeout=90):
    c = conf()
    if not (c.get("api_key") and c.get("base_url")):
        return None
    url = c["base_url"].rstrip("/") + "/chat/completions"
    body = {"model": model or c.get("model") or "gpt-4o-mini",
            "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + c["api_key"],
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8"))
        return ((j.get("choices") or [{}])[0].get("message") or {}).get("content")
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:200])}


def deep_read(item, lang="zh"):
    """对一篇文献做结构化深度解读。缺摘要时不做臆测，只给已有信息。"""
    if not enabled():
        return None
    p = C.profile()
    theme = (p.get("theme") or {}).get("zh") or ""
    title = item.get("title") or item.get("title_en") or item.get("title_zh") or ""
    abstract = item.get("abstract") or item.get("abstract_en") or item.get("abstract_zh") or ""
    sysmsg = ("你是一位严谨的文献精读助手。只依据给出的题名与摘要作答，"
              "严禁编造研究方法、数据、结论或出处；信息不足就明确写「摘要未提供」。")
    user = ("使用者研究主题：%s\n\n题名：%s\n摘要：%s\n\n请输出：\n"
            "1) 一句话核心主张\n2) 研究问题\n3) 研究设计与数据（摘要未提供就写未提供）\n"
            "4) 主要发现\n5) 与使用者的研究主题的关系（可迁移 / 仅背景 / 无直接关系，并说明理由）\n"
            "6) 值得警惕的局限\n" % (theme, title, abstract[:3000]))
    out = chat([{"role": "system", "content": sysmsg},
                {"role": "user", "content": user}])
    if isinstance(out, dict):
        return None
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", required=True, help="单篇文献 JSON 文件")
    a = ap.parse_args()
    d = json.load(open(a.file, encoding="utf-8"))
    r = deep_read(d)
    print(r if r else "（未配置大模型或调用失败：config/llm.json）")
