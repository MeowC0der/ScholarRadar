# 定时任务 Prompt 模板

把下面的 prompt 直接用于创建定时任务（RRULE 见下）。所有路径请替换为你的 skill 实际安装路径。
约定：`SKILL = <你的 skill 安装目录>/academic-lit-monitor`，`PY = 你的 python 解释器`。

---

## A. 英文文献监测（每日 08:00）

- RRULE：`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`
- Prompt：

```
执行英文文献监测（OpenAlex）。工作目录 SKILL，解释器 PY。

步骤：
1) 门禁：运行 `PY scripts/setup.py check`。若 profile 或 smtp 未配置（ok=false），
   立即停止并如实报告"未配置完成，未执行监测"，不要猜测配置、不要伪造结果。
2) 采集：`PY scripts/runner.py collect --mode both --days 1`（只抓昨今两天的新文献）。
3) 入库与评分：`PY scripts/runner.py sync`。
4) 高分清单：`PY scripts/runner.py digest --min-score 75 --limit 20`。
5) 若存在 ≥75 分的条目：用你自己的话对 top 3 做 3–5 句深度解读（依据题名+摘要，
   严禁编造方法、数据、结论），随后 `PY scripts/runner.py mail --min-score 75 --send` 发信。
   若没有 ≥75 分的条目：不发信，只报告"今日无高分新文献"。
6) 台账：`PY scripts/ledger.py build`。
7) 结束前报告：抓到几篇、新增几篇、几篇 ≥75、几篇 60–74、邮件是否真的发出（以发送接口返回为准）、
   台账行数。任何一步失败都要如实说明失败在哪一步。
```

---

## B. 中文期刊监测（每日 14:00）

- RRULE：`FREQ=DAILY;BYHOUR=14;BYMINUTE=0`
- Prompt：

```
执行中文期刊（知网）新文献监测，只抓基础元数据，不下载 PDF。工作目录 SKILL，解释器 PY。

步骤：
1) 门禁：`PY scripts/setup.py check`。webvpn 未配置或登录失败 → 停止并如实报告，不伪造任何条目。
2) 目录发现：`PY scripts/cnki_scan.py toc --limit 8`（刊名取自 profile.journals_cn）。
   若返回 blocked_slider / vpn_session_expired，立即停止并报告，不要重试刷量。
3) 元数据抓取：`PY scripts/cnki_scan.py meta --limit 30 --delay 12`（后台无头，不弹窗）。
   抓不到的摘要/关键词留空，绝不推测填充。
4) 入队评分：`PY scripts/cnki_watch.py sync`。
5) 高分清单：`PY scripts/cnki_watch.py digest --min-score 75`。
6) 邮件：有 ≥75 分条目时 `PY scripts/cnki_watch.py mail --min-score 75 --send`；
   否则不发信，只报告。
7) 台账：`PY scripts/ledger.py build`。
8) 报告：扫描了几本刊、拿到几篇元数据、新增几篇、高分几篇、邮件是否真的发出、失败在哪一步。
```

---

## C. 每周汇总 + 台账同步到资料库（每周日 20:00）

- RRULE：`FREQ=WEEKLY;BYDAY=SU;BYHOUR=20;BYMINUTE=0`
- Prompt：

```
生成本周文献监测周报并更新台账。工作目录 SKILL，解释器 PY。

步骤：
1) 汇总本周英文高分：`PY scripts/runner.py digest --min-score 60 --limit 40`。
2) 汇总本周中文高分：`PY scripts/cnki_watch.py digest --min-score 60 --limit 40`。
3) 写一份周报：按研究方向分组，列出本周最值得读的 5–10 篇（题名/期刊/评分/一句为什么值得读），
   并指出本周的「缺口」（哪个方向没新文献、哪种设计稀缺）。
4) 台账：`PY scripts/ledger.py build` → `PY scripts/ledger.py push`（同步到 WorkBuddy 资料库同一节点）。
5) 邮件：把周报发到使用者邮箱（`--send`）。
6) 报告：台账总行数、新增行数、资料库是否真的更新成功（以接口返回为准）、周报是否发出。
```

---

## D. 即时检索（按需，不定时）

```
按使用者给的问题检索文献（OpenAlex 全文/摘要检索）：
`PY scripts/collector.py questions --days 365 --per-page 50`
再 `PY scripts/runner.py sync` + `digest`，把 top 10 整理成带评分的清单发给使用者。
```

---

## 通用约束（每条任务都要带）

- 任何"未配置 / 被拦截 / 接口失败"都必须**如实报告**，禁止输出"已完成""已发送""已入库"的假状态。
- 只保存元数据，不下载 PDF。
- 遇滑块验证码立即停止，不重刷。
- 账号、授权码、API Key 不出现在报告里。
