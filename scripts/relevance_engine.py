# -*- coding: utf-8 -*-
"""通用文献相关性评分引擎（relevance-v3.0.0，数据驱动）

与旧版最大的不同：**本文件不含任何研究领域词汇**。方向关键词、在研项目、期刊层级、
权重与阈值全部来自 config/profile.json（安装者本人填写）。内置的只有与领域无关的
通用学术语言（理论机制词、研究设计词），它们衡量的是「这篇文章做得扎不扎实」，
而不是「这篇文章是不是我的题目」。

维度与默认权重（可在 profile.scoring 里改）
------------------------------------------
  d1 研究问题匹配 0.35   命中使用者自定义方向关键词的数量与广度
  d2 理论机制价值 0.20   是否指向机制 / 逻辑 / 因果等理论贡献
  d3 研究设计价值 0.20   能否识别可信的经验设计或方法路径
  d5 项目可借鉴   0.15   与使用者在研项目的关联
  d7 学术成熟度   0.10   期刊层级 + 是否正式发表（预印本降权）

等级：critical ≥90 / high ≥75 / recommended ≥60 / archive <60（阈值可在 profile 里改）
"""
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config_loader as C  # noqa: E402

VERSION = "relevance-v3.0.0"

# ---- 通用理论机制词（与领域无关：衡量是否做机制/理论贡献）----
THEORY_MARKERS = {
    "en": ["mechanism", "causal", "causality", "theoretical", "theory", "framework",
           "logic", "pathway", "channel", "mediat", "moderat", "heterogeneous",
           "heterogeneity", "boundary condition", "identification", "trade-off",
           "paradox", "unintended", "explains", "explaining", "account for"],
    "zh": ["机制", "机理", "逻辑", "路径", "框架", "理论", "解释", "因果", "条件", "边界",
           "效应", "范式", "模型", "谱系", "反思", "建构", "生成", "演化", "转型", "重塑",
           "何以", "如何", "为何", "视角", "进路", "规律", "悖论", "张力", "调适"],
}

# ---- 通用研究设计识别（d3）：(标签, 基础分, 模式) ----
DESIGN_PATTERNS = [
    ("实验研究", 88, [r"\bexperiment\b", r"\bRCT\b", r"randomi[sz]ed", r"\btreatment\b",
                      r"survey experiment", r"field experiment", r"conjoint"]),
    ("双重差分/准自然实验", 92, [r"difference-in-differences", r"\bDID\b", r"natural experiment",
                                 r"quasi-experimental", r"policy evaluation"]),
    ("断点回归", 88, [r"regression discontinuity", r"\bRDD\b"]),
    ("工具变量/因果识别", 84, [r"instrumental variable", r"\bIV\b", r"identification strategy"]),
    ("面板/纵向数据分析", 78, [r"panel data", r"fixed effects", r"longitudinal", r"time-series"]),
    ("大样本量化分析", 74, [r"\bempirical\b", r"regression", r"econometric", r"large-N",
                            r"administrative data", r"statistical analysis"]),
    ("问卷调查", 70, [r"\bsurvey\b", r"questionnaire", r"sampling", r"\bscale\b"]),
    ("案例研究", 68, [r"case study", r"case studies", r"qualitative case", r"in-depth case"]),
    ("质性/扎根/访谈", 66, [r"grounded theory", r"qualitative", r"interview", r"ethnograph",
                            r"participant observation", r"\bcoding\b"]),
    ("定性比较分析(QCA)", 72, [r"qualitative comparative", r"\bQCA\b", r"fsQCA", r"configurational"]),
    ("计算文本/机器学习", 80, [r"text analysis", r"text mining", r"topic model", r"word embedding",
                               r"large language model", r"machine learning", r"natural language processing",
                               r"automated content analysis", r"\bBERT\b", r"\bLLM\b"]),
    ("历史/档案分析", 62, [r"historical", r"archival", r"\barchive\b", r"historical data"]),
    ("文献综述/理论探讨", 45, [r"\breview\b", r"synthesis", r"research agenda", r"\bprospect\b",
                               r"state of the art", r"literature review"]),
]

# 中文补充（中文文献由 cnki_score.py 处理，这里保留一套以便统一调用）
DESIGN_PATTERNS_ZH = [
    ("实验研究", 88, ["实验", "联合实验", "调查实验", "田野实验", "随机", "RCT", "被试"]),
    ("双重差分/准自然实验", 92, ["双重差分", "DID", "准自然实验", "自然实验", "政策评估"]),
    ("断点回归", 88, ["断点回归", "RDD", "断点"]),
    ("面板/纵向数据分析", 78, ["面板", "纵向", "固定效应", "追踪", "时间序列"]),
    ("大样本量化分析", 74, ["实证", "回归", "计量", "统计分析", "量化", "测度"]),
    ("问卷调查", 70, ["问卷", "调查", "抽样", "量表"]),
    ("案例研究", 68, ["案例", "个案", "以.*为例", "考察", "典型"]),
    ("扎根理论/质性编码", 66, ["扎根理论", "质性", "编码", "访谈", "民族志", "田野"]),
    ("定性比较分析(QCA)", 72, ["定性比较", "QCA", "组态", "模糊集"]),
    ("计算文本分析", 80, ["文本分析", "文本挖掘", "语义", "主题模型", "词频", "语料",
                          "大语言模型", "机器学习"]),
    ("历史/档案分析", 62, ["历史", "档案", "史料", "碑刻", "族谱", "方志"]),
    ("文献综述/理论探讨", 45, ["综述", "述评", "回顾", "展望", "议程", "谱系"]),
]


def _norm_words(seq):
    return [str(w).strip() for w in (seq or []) if str(w).strip()]


def _text_of(item, lang="en"):
    parts = []
    if lang == "en":
        parts += [item.get("title_en") or item.get("title") or "",
                  item.get("abstract_en") or item.get("abstract") or ""]
    else:
        parts += [item.get("title_zh") or item.get("title") or "",
                  item.get("abstract_zh") or item.get("abstract") or ""]
    kw = item.get("keywords")
    if isinstance(kw, str):
        parts.append(kw)
    elif isinstance(kw, list):
        parts.append(" ".join(str(x) for x in kw))
    return " ".join(p for p in parts if p)


def _hits(text, words):
    low = text.lower()
    return [w for w in words if w and w.lower() in low]


def score(item, profile=None, lang=None):
    """给一条文献打分。item 至少含标题，最好含摘要与关键词。

    lang: en / zh / None（自动判断：含中文字符且无英文摘要则按 zh）
    """
    p = profile or C.profile()
    sc = C.scoring()
    weights, thresholds = sc["weights"], sc["thresholds"]
    dirs = []
    ds = p.get("directions") or {}
    if isinstance(ds, dict):
        for code, v in ds.items():
            v = dict(v)
            v.setdefault("code", code)
            dirs.append(v)
    else:
        dirs = [dict(x) for x in ds]

    if lang is None:
        title = (item.get("title_en") or item.get("title") or "")
        zh = (item.get("title_zh") or item.get("abstract_zh") or "")
        lang = "zh" if (zh and not (item.get("abstract_en") or "")) else "en"
        if any("\u4e00" <= c <= "\u9fff" for c in (title or "")) and not (item.get("abstract_en") or ""):
            lang = "zh"

    full = _text_of(item, lang)
    title_txt = (item.get("title_zh") if lang == "zh" else item.get("title_en")) or item.get("title") or ""
    reasons = []

    # ---------------- d1 研究问题匹配 ----------------
    hits = {}
    for d in dirs:
        words = _norm_words(d.get("keywords_zh" if lang == "zh" else "keywords_en"))
        if not words:
            words = _norm_words(d.get("keywords_en") or d.get("keywords_zh"))
        got = _hits(full, words)
        if got:
            hits[d.get("code") or d.get("name_zh")] = got
    n_dirs = len(hits)
    n_concepts = sum(len(v) for v in hits.values())
    n_title = sum(len([w for w in v if w.lower() in (title_txt or "").lower()]) for v in hits.values())
    if n_dirs == 0:
        d1 = 8.0
        reasons.append("未命中任何自定义研究方向关键词")
    else:
        base = 34.0 + min(n_title, 5) * 12.0 + min(max(n_concepts - n_title, 0), 5) * 3.0
        base += (n_dirs - 1) * 5.0
        d1 = min(base, 100.0)
        reasons.append("命中方向 %s（题名概念 %d / 全部 %d）"
                       % ("/".join(sorted(hits)), n_title, n_concepts))
    if not (item.get("abstract_en") or item.get("abstract_zh") or item.get("abstract")):
        d1 *= 0.92
        reasons.append("无摘要，d1 打折 8%")

    # ---------------- d2 理论机制价值 ----------------
    markers = THEORY_MARKERS.get(lang, THEORY_MARKERS["en"])
    th = _hits(full, markers) if lang == "en" else [m for m in markers if m in full]
    d2 = 30.0 if not th else min(48.0 + len(th) * 9.0, 100.0)
    reasons.append("理论机制词 %s" % ("、".join(th[:6]) if th else "无"))

    # ---------------- d3 研究设计价值 ----------------
    design, d3 = "未识别", 40.0
    pats = DESIGN_PATTERNS_ZH if lang == "zh" else DESIGN_PATTERNS
    for label, base, ps in pats:
        for pt in ps:
            if (pt in full) if lang == "zh" else re.search(pt, full, re.I):
                design, d3 = label, float(base)
                break
        if design != "未识别":
            break
    reasons.append(("识别设计：%s" % design) if design != "未识别" else "未识别到明确研究设计")

    # ---------------- d5 项目可借鉴 ----------------
    projs = []
    ps = p.get("projects") or {}
    plist = [dict(v, id=k) for k, v in ps.items()] if isinstance(ps, dict) else [dict(x) for x in ps]
    for pr in plist:
        words = _norm_words(pr.get("keywords_zh" if lang == "zh" else "keywords_en")) + \
            _norm_words(pr.get("keywords_en") if lang == "zh" else pr.get("keywords_zh"))
        got = _hits(full, words) if lang == "en" else [w for w in words if w in full]
        if got:
            projs.append({"id": pr.get("id"), "name": pr.get("name") or pr.get("name_zh") or "",
                          "hits": got})
    if projs:
        d5 = min(75.0 + len(projs) * 12.0, 100.0)
        reasons.append("关联在研项目：%s" % "、".join(x["name"] for x in projs))
    elif hits:
        d5 = 45.0
        reasons.append("未直接命中在研项目，但命中研究方向关键词")
    else:
        d5 = 30.0

    # ---------------- d7 学术成熟度 ----------------
    jname = item.get("journal_name") or item.get("journal") or ""
    d7 = float(C.journal_tier(jname))
    if (item.get("publication_status") or "") in ("preprint", "online_first") or \
       (item.get("preprint_status") or "") == "preprint":
        d7 = max(d7 - 8.0, 40.0)
        reasons.append("预印本/在线优先，成熟度降权")
    reasons.append("期刊层级 %.0f（%s）" % (d7, jname or "未标注"))

    total = (d1 * weights.get("d1_research_match", 0.35)
             + d2 * weights.get("d2_theory_transfer", 0.20)
             + d3 * weights.get("d3_method_value", 0.20)
             + d5 * weights.get("d5_writing_help", 0.15)
             + d7 * weights.get("d7_maturity", 0.10))

    # ---------------- 负面信号 ----------------
    negatives = []
    neg = (p.get("negative_keywords") or {}).get(lang, [])
    for w in neg:
        if w and (w.lower() in full.lower() if lang == "en" else w in full):
            negatives.append({"word": w, "action": "总分 ×0.6"})
            total *= 0.6
            break
    total = round(max(0.0, min(total, 100.0)), 1)

    dirs_sorted = sorted(hits, key=lambda d: (-len(hits[d]), d))
    top = dirs_sorted[0] if dirs_sorted else "-"
    level = ("critical" if total >= thresholds.get("critical", 90)
             else "high" if total >= thresholds.get("high", 75)
             else "recommended" if total >= thresholds.get("recommended", 60)
             else "archive")
    thr = float(thresholds.get("high", 75))
    for d in dirs:
        if (d.get("code") or "") == top and d.get("alert_threshold_override"):
            thr = float(d["alert_threshold_override"])
    dname = {d.get("code"): (d.get("name_zh") or d.get("name") or d.get("code")) for d in dirs}

    return {
        "scorer_version": VERSION,
        "total_score": total,
        "alert_level": level,
        "alert_threshold": thr,
        "should_alert": total >= thr,
        "directions": dirs_sorted,
        "top_direction": top,
        "top_direction_name": dname.get(top, top),
        "matched_concepts": [{"direction": d, "concepts": v} for d, v in sorted(hits.items())],
        "evidence_design": design,
        "project_tags": [x["id"] for x in projs],
        "project_names": [x["name"] for x in projs],
        "d1_research_match": round(d1, 1),
        "d2_theory_transfer": round(d2, 1),
        "d3_method_value": round(d3, 1),
        "d5_writing_help": round(d5, 1),
        "d7_maturity": round(d7, 1),
        "recommend_reason": "；".join(reasons),
        "negative_signals": negatives,
        "lang": lang,
    }


def score_all(items, profile=None):
    p = profile or C.profile()
    out = []
    for it in items:
        r = score(it, p)
        r["id"] = it.get("id") or it.get("doi") or it.get("article_uid")
        r["title"] = it.get("title_en") or it.get("title_zh") or it.get("title")
        out.append(r)
    out.sort(key=lambda x: -x["total_score"])
    return out


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="通用文献相关性评分")
    ap.add_argument("--input", required=True, help="文献 JSON 数组文件")
    ap.add_argument("--top", type=int, default=20)
    a = ap.parse_args()
    items = json.load(open(a.input, encoding="utf-8"))
    res = score_all(items)
    for r in res[:a.top]:
        print("%5.1f [%s] %s | %s | %s | %s"
              % (r["total_score"], r["alert_level"], "/".join(r["directions"]) or "-",
                 r["evidence_design"], ",".join(r["project_tags"]) or "-",
                 (r["title"] or "")[:50]))
