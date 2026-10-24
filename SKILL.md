---
name: academic-lit-monitor
description: 学术文献监测助手 — 按使用者自定义的研究方向，每日/每周监测中英文新文献（英文走 OpenAlex，中文走知网 + 本人学校 WebVPN），只抓标题/作者/摘要/关键词/出版时间等基础元数据，做 0–100 分相关性评分与分级，生成邮件推送、飞书日程，并持续维护一份 CSV 文献台账（可同步到 WorkBuddy 资料库）。触发词：文献监测、新文献推送、期刊更新、文献台账、知网监测、OpenAlex 检索、文献评分。
version: 1.0.0
---

# 学术文献监测助手（academic-lit-monitor）

把「盯新文献」这件事自动化：每天自动扫一批期刊和问题，把值得读的挑出来、打分排序、发到邮箱，
并把所有监测到的文献持续沉淀成一份 CSV 台账。

**本 Skill 不含任何个人信息**，安装后必须先由使用者本人完成配置（见 §1）。

---

## 1. 首次安装：必须完成的 6 项配置

Agent 在首次使用本 Skill 时，**必须逐项向使用者收集以下信息并写入配置**，不得跳过、
不得用占位值蒙混、不得把信息写进代码（只能写进 `config/*.json`）。

| # | 配置项 | 收集什么 | 写入命令 |
|---|--------|----------|----------|
| 1 | **发信邮箱 SMTP** | SMTP 服务器、端口、**邮箱账号**、**授权码**（不是登录密码）、收件人 | `python scripts/setup.py set smtp --host smtp.example.com --port 465 --user you@example.com --password <授权码> --to you@example.com` |
| 2 | **研究方向与兴趣** | 若干个研究方向（名称 + 中英文关键词）、在研项目（名称 + 关键词）、要盯的中英文期刊清单 | `python scripts/setup.py gen-profile`（人在终端）或 `set-profile --file profile.json`（Agent 代填） |
| 3 | **学校/单位 WebVPN** | WebVPN 域名、账号、密码（用于知网机构认证；不做中文监测可跳过） | `python scripts/setup.py set webvpn --host webvpn.xxx.edu.cn --user <学号> --password <密码> [--cnki-entry <知网入口URL>] [--kns-hash <hash>]` |
| 4 | **OpenAlex API** | API Key（可留空走免费 polite pool）+ 联系邮箱 | `python scripts/setup.py set openalex --api-key <key> --mailto me@x.com` |
| 5 | **大模型** | provider / base_url / **API Key** / 模型名（用于深度解读，可留空） | `python scripts/setup.py set llm --provider openai-compatible --base-url https://.../v1 --api-key <key> --model <model>` |
| 6 | **飞书**（可选） | App ID / App Secret，日历 ID 或 多维表格 token+table_id | `python scripts/setup.py set feishu --app-id ... --app-secret ... --calendar-id ... --base-token ... --table-id ...` |

其他命令：

```bash
python scripts/setup.py wizard     # 终端交互式一条龙（人在场时最省事）
python scripts/setup.py status     # 看哪些配了、哪些没配（敏感值打码）
python scripts/setup.py check      # 连通性自检：SMTP 登录 / OpenAlex / WebVPN / 大模型 / 飞书
```

配置全部落在 `<skill>/config/`，只在本机可见；任何脚本都不会把账号、授权码、API Key 打印出来。

### profile.json 示例结构（`setup.py gen-profile` 会生成同结构文件）

```json
{
  "theme": {"zh": "一句话概括你的研究主题"},
  "directions": {
    "A": {"code": "A", "name_zh": "方向名", "keywords_en": ["..."], "keywords_zh": ["..."],
          "alert_threshold_override": 75, "research_questions": ["..."]}
  },
  "projects": {"P1": {"id": "P1", "name": "项目名", "keywords_zh": ["..."], "keywords_en": ["..."]}},
  "journals_en": [{"name": "Journal Name", "issn": "0000-0000", "tier": 90}],
  "journals_cn": [{"name": "期刊名", "tier": 90}],
  "negative_keywords": {"en": [], "zh": []},
  "scoring": {"weights": {"d1_research_match": 0.35, "d2_theory_transfer": 0.20,
                          "d3_method_value": 0.20, "d5_writing_help": 0.15, "d7_maturity": 0.10},
              "thresholds": {"critical": 90, "high": 75, "recommended": 60},
              "default_journal_tier": 70}
}
```

---

## 2. 三条主流程

### 2.1 英文文献监测（OpenAlex，公开 API，无需 WebVPN）

```bash
python scripts/runner.py collect --mode both --days 7   # 按期刊清单 + 按方向关键词各扫一遍
python scripts/runner.py sync                            # 去重入库并打分
python scripts/runner.py digest --min-score 75           # 输出高分清单（供 Agent 深度解读）
python scripts/runner.py mail --min-score 60 --send      # 发邮件
```

### 2.2 中文文献监测（知网，经本人学校 WebVPN，只抓元数据、不下载 PDF）

```bash
python scripts/webvpn.py login                           # 登录 WebVPN（会话存 state/）
python scripts/cnki_scan.py toc --limit 8                # 目录发现：最新一期有哪些文章
python scripts/cnki_scan.py meta --limit 30              # 逐篇抓 摘要/关键词/出版时间/DOI
python scripts/cnki_watch.py sync                        # 并入队列 + 打分
python scripts/cnki_watch.py digest --min-score 75       # 高分清单
python scripts/cnki_watch.py mail --min-score 60 --send  # 发邮件
```

浏览器**默认后台无头**运行（不弹窗、不抢占焦点）；`CNKI_HEADLESS=0` 可切回可见用于排障。

### 2.3 文献台账 CSV（+ 同步到 WorkBuddy 资料库）

```bash
python scripts/ledger.py build                           # 汇总中英文队列 -> outputs/文献监测台账.csv
python scripts/ledger.py push                            # 同步到资料库（首次建节点，之后覆盖同一节点）
python scripts/ledger.py status                          # 查看本地 CSV 行数与资料库节点
```

CSV 字段：序号 / 来源 / 标题 / 作者 / 期刊 / 出版时间 / 卷期 / 页码 / DOI / 链接 /
摘要 / 关键词 / 评分 / 等级 / 研究方向 / 关联项目 / 研究设计 / 推荐理由 / 首次发现 / 最近更新 / 状态。

资料库同步用 `library` skill 的 `database/import_csv.py`：首次导入后把 `database_id` 记进
`state/library_ledger.json`，之后每次用 `--database-id` **覆盖重导入同一节点**，不会堆积重复文件。

---

## 3. 评分机制（0–100，与领域无关的通用维度 + 使用者自定义关键词）

| 维度 | 权重 | 含义 |
|------|------|------|
| d1 研究问题匹配 | 0.35 | 命中**你自己填的**方向关键词的数量与广度（标题命中权重更高） |
| d2 理论机制价值 | 0.20 | 是否指向机制 / 逻辑 / 因果等理论贡献（内置通用学术词，非领域词） |
| d3 研究设计价值 | 0.20 | 能否识别可信设计：实验 / DID / RDD / 面板 / 案例 / 计算文本 … |
| d5 项目可借鉴 | 0.15 | 与**你填的**在研项目关键词的关联 |
| d7 学术成熟度 | 0.10 | 期刊层级（profile 里可设 tier）+ 预印本降权 |

等级：critical ≥90｜high ≥75｜recommended ≥60｜archive <60（阈值可在 profile 改）。
评分引擎**不内置任何研究领域词汇**，因此换一个研究方向也能直接用——换的是 `profile.json`。

---

## 4. 行为准则（不可违反）

1. **不伪造**：抓不到的字段一律留空并在报告中说明；绝不编造摘要、作者、评分、发送状态、入库状态。
2. **不下载全文 PDF**：本 Skill 只采集基础元数据（标题/作者/摘要/关键词/出版时间/卷期页码/DOI/链接）。
3. **合规访问**：知网走使用者本人的学校/单位 WebVPN 机构认证；遇滑块验证码立即停止整个队列并如实报告。
4. **速率克制**：篇间随机延时（默认 12s 上下浮动），不对数据源造成压力。
5. **隐私**：账号、授权码、API Key 只进 `config/`，不进代码、不进日志、不进邮件正文。

---

## 5. 部署为定时任务

把主流程挂成定时任务即可无人值守运行（模板见 `references/automation-prompts.md`）：

- **英文每日**：`FREQ=DAILY;BYHOUR=8;BYMINUTE=0` → `runner.py run` + 高分才发信
- **中文每日**：`FREQ=DAILY;BYHOUR=14;BYMINUTE=0` → `cnki_scan.py run` + `cnki_watch.py sync/mail`
- **每周汇总 + 台账**：`FREQ=WEEKLY;BYDAY=SU;BYHOUR=20;BYMINUTE=0` → `ledger.py build/push` + 周报邮件

定时任务 prompt 的关键约束（写进任务里，避免跑偏）：
先 `setup.py check` 门禁 → 任一项失败如实报告并停止 → 不做推测填充 → 结束前报告「抓了几篇 /
几篇高分 / 邮件是否真的发出 / 台账是否更新」。
