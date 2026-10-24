# 学术文献监测助手 · academic-lit-monitor

**简体中文** | [English](README_EN.md)

一个可无人值守运行的文献监测 Skill（WorkBuddy 技能包）：按**你自己的**研究方向，每天自动扫中英文新文献，
只抓基础元数据（标题/作者/摘要/关键词/出版时间），做 0–100 分相关性评分与分级，
高分才发邮件，并把所有监测到的文献持续沉淀成一份 CSV 台账（可同步到 WorkBuddy 资料库）。

> 仓库**不含任何个人信息**：所有账号、授权码、API Key 只存在安装者本机的 `config/*.json`；
> 评分引擎内置的是**通用学术语言**，不含任何领域词汇——换研究方向只需换 `profile.json`。

---

## 它能做什么

| 能力 | 说明 |
|---|---|
| **英文监测** | 走 OpenAlex 公开 API，按期刊清单 + 按研究问题关键词双路检索（无需 VPN） |
| **中文监测** | 知网（CNKI），经**你本人学校/单位**的 WebVPN 机构认证：目录发现 + 逐篇元数据抓取 |
| **只抓元数据** | 不下载全文 PDF |
| **0–100 评分** | 5 个加权维度，分 critical / high / recommended / archive 四档 |
| **邮件推送** | 只发超过阈值的条目，HTML + 纯文本双版本 |
| **CSV 台账** | 21 列增量维护，可一键同步到 WorkBuddy 资料库（每次覆盖同一节点，不堆积） |
| **可选增强** | 大模型深度解读、飞书日历/多维表格推送 |
| **后台无头** | 知网浏览器默认后台无头运行，不弹窗、不抢焦点 |

---

## 安装（3 步）

### 1. 放到你的 skills 目录

```
把整个 academic-lit-monitor 目录复制到：
  Windows: C:\Users\<你>\.workbuddy\skills\academic-lit-monitor
  macOS  : ~/.workbuddy/skills/academic-lit-monitor
```

### 2. 告诉 WorkBuddy 你的配置（让 Agent 帮你写，或自己跑向导）

Agent 会逐项问你要 6 类信息，然后写入 `config/`（只在本机，不外传）：

| # | 配置 | 你要准备什么 |
|---|------|--------------|
| 1 | 发信邮箱 SMTP | 邮箱账号 + **授权码**（在邮箱设置→POP3/SMTP 里申请，不是登录密码）+ SMTP 服务器 |
| 2 | 研究方向与兴趣 | 几个研究方向名称 + 中英文关键词；在研项目名称 + 关键词；要盯的中英文期刊清单 |
| 3 | 学校/单位 WebVPN | WebVPN 域名 + 学号/工号 + 密码（用于知网机构认证；不做中文监测可跳过） |
| 4 | OpenAlex API | API Key（可留空走免费通道）+ 联系邮箱 |
| 5 | 大模型 | provider / base_url / API Key / 模型名（用于深度解读，可留空） |
| 6 | 飞书（可选） | App ID / App Secret + 日历 ID 或 多维表格 token |

自己装也可以：

```bash
python scripts/setup.py wizard     # 交互式一条龙
python scripts/setup.py status     # 看哪些配了、哪些没配（敏感值打码）
python scripts/setup.py check      # 连通性自检：SMTP / OpenAlex / WebVPN / 大模型 / 飞书
```

### 3. 建定时任务（让 Agent 用 `references/automation-prompts.md` 里的模板建）

- 英文每日 08:00：`FREQ=DAILY;BYHOUR=8;BYMINUTE=0`
- 中文每日 14:00：`FREQ=DAILY;BYHOUR=14;BYMINUTE=0`
- 每周汇总 + 台账入库：周日 20:00：`FREQ=WEEKLY;BYDAY=SU;BYHOUR=20;BYMINUTE=0`

---

## 环境要求

- Python 3.9+（标准库即可跑英文监测与台账）
- 中文知网监测需要：`pip install playwright requests` 并 `playwright install msedge`（或 chromium）
- 浏览器默认**后台无头**运行，不会弹窗打断你工作

## 目录结构

```
academic-lit-monitor/
  SKILL.md                       触发说明与行为准则（Agent 读）
  README.md                      本文件
  README_EN.md                   English documentation
  config/*.template.json         6 份配置模板（复制成 *.json 后填写）
  scripts/
    setup.py                     安装向导 / 自检 / 配置写入
    config_loader.py             统一配置读取（敏感值打码）
    relevance_engine.py          通用评分引擎（不内置任何领域词）
    runner.py                    英文监测主流程（采集→评分→清单→邮件）
    collector.py                 OpenAlex 采集（按期刊 / 按问题）
    cnki_scan.py                 知网目录发现 + 元数据抓取（不下载 PDF）
    cnki_watch.py                中文队列：合并→评分→清单→邮件
    cnki_browser.py              后台无头浏览器启动器
    webvpn.py                    通用高校 WebVPN 登录
    ledger.py                    文献台账 CSV + 资料库同步
    smtp_sender.py               发信（配置化）
    llm_client.py                大模型深度解读（可选）
    feishu_sync.py               飞书日历 / 多维表格（可选）
  references/automation-prompts.md   定时任务 prompt 模板
  data/ state/ outbox/ outputs/      运行产物（首次运行自动创建）
```

## 评分机制（0–100）

| 维度 | 权重 | 含义 |
|------|------|------|
| d1 研究问题匹配 | 0.35 | 命中**你自己填的**方向关键词的数量与广度（标题命中权重更高） |
| d2 理论机制价值 | 0.20 | 是否指向机制 / 逻辑 / 因果等理论贡献（通用学术词） |
| d3 研究设计价值 | 0.20 | 能否识别可信设计：实验 / DID / RDD / 面板 / 案例 / 计算文本 |
| d5 项目可借鉴 | 0.15 | 与**你填的**在研项目关键词的关联 |
| d7 学术成熟度 | 0.10 | 期刊层级（profile 里设 tier）+ 预印本降权 |

等级：critical ≥90｜high ≥75｜recommended ≥60｜archive <60（阈值可在 profile 改）。
评分引擎**不内置任何研究领域词汇**，换方向只换 `profile.json`。

## 台账 CSV 字段

来源 / 标题 / 作者 / 期刊 / 出版时间 / 卷期 / 页码 / DOI / 链接 / 摘要 / 关键词 /
评分 / 等级 / 研究方向 / 关联项目 / 研究设计 / 推荐理由 / 首次发现 / 最近更新 / 状态。

## 行为准则（不可违反）

1. **不伪造**：抓不到的字段一律留空并在报告中说明；绝不编造摘要、作者、评分、发送状态、入库状态。
2. **不下载全文 PDF**：本 Skill 只采集基础元数据。
3. **合规访问**：知网走使用者本人的学校/单位 WebVPN 机构认证；遇滑块验证码立即停止整个队列并如实报告。
4. **速率克制**：篇间随机延时（默认 12s 上下浮动）。
5. **隐私**：账号、授权码、API Key 只进 `config/`，不进代码、不进日志、不进邮件正文。

## 隐私与合规

- 代码里**不含任何个人信息**：账号、授权码、API Key 只存在 `config/*.json`（已被 .gitignore 排除）。
- 只采集基础元数据，不下载全文 PDF。
- 知网访问依赖使用者本人的机构订阅权限；本项目不绕过任何付费墙或访问控制。

## 许可

MIT — 见 [LICENSE](LICENSE)。
