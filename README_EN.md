# academic-lit-monitor

[简体中文](README.md) | **English**

A **WorkBuddy Skill** that watches the literature for you, unattended.

It scans English and Chinese journals on **your own** research agenda, collects **metadata only**
(title / authors / abstract / keywords / publication date), scores every item **0–100** for relevance,
emails only the ones that matter, and keeps a **CSV ledger** of everything it has ever seen
(optionally synced to your WorkBuddy Library).

> No personal data ships with this repo. Every credential lives in `config/*.json` on the
> installer's own machine, and the scoring engine contains **no domain-specific vocabulary** —
> point it at any field by editing `profile.json`.

---

## What it does

| Capability | Detail |
|---|---|
| **English monitoring** | OpenAlex — by journal list *and* by research-question keywords (public API, no VPN) |
| **Chinese monitoring** | CNKI (知网) via **your own** institution WebVPN — table-of-contents discovery + per-article metadata |
| **Metadata only** | No full-text PDF download, ever |
| **0–100 scoring** | 5 weighted dimensions, graded `critical / high / recommended / archive` |
| **Email digest** | Only items above your threshold; HTML + plain text |
| **CSV ledger** | 21 columns, incremental; one-shot sync to WorkBuddy Library (always overwrites the *same* node) |
| **Optional extras** | LLM deep-reading notes, Feishu calendar / Bitable push |
| **Runs headless** | The CNKI browser runs in the background; it never steals your focus |

---

## Install (3 steps)

### 1. Drop it into your skills directory

```
Copy the whole academic-lit-monitor folder to:
  Windows: C:\Users\<you>\.workbuddy\skills\academic-lit-monitor
  macOS  : ~/.workbuddy/skills/academic-lit-monitor
```

### 2. Let the agent collect your configuration

Say *"install the literature-monitor skill"* to your agent. It must ask you for **six** things and
write them into `config/` (local only, never committed, never printed in clear text):

| # | Setting | What you need to prepare | Written to |
|---|---|---|---|
| 1 | **SMTP mailbox** | SMTP host, port, **account**, **app password** (an authorization code from your mail provider — *not* your login password), recipient | `config/smtp.json` |
| 2 | **Research agenda** | A few research directions (name + EN/ZH keywords), ongoing projects (name + keywords), journal lists to watch | `config/profile.json` |
| 3 | **Institution WebVPN** | WebVPN domain, student/staff ID, password (needed for CNKI institutional access; skip if you don't need Chinese monitoring) | `config/webvpn.json` |
| 4 | **OpenAlex API** | API key (may be left empty to use the free polite pool) + a contact email | `config/openalex.json` |
| 5 | **LLM** | provider / base_url / **API key** / model name (for deep reading; optional) | `config/llm.json` |
| 6 | **Feishu / Lark** *(optional)* | App ID, App Secret, calendar ID or Bitable token + table_id | `config/feishu.json` |

Prefer doing it yourself?

```bash
python scripts/setup.py wizard     # interactive walkthrough
python scripts/setup.py status     # what's configured, what's missing (secrets masked)
python scripts/setup.py check      # connectivity self-test: SMTP / OpenAlex / WebVPN / LLM / Feishu
```

### 3. Create the scheduled jobs

Ask your agent to create scheduled tasks using the templates in
`references/automation-prompts.md`:

- **English daily** — `FREQ=DAILY;BYHOUR=8;BYMINUTE=0`
- **Chinese daily** — `FREQ=DAILY;BYHOUR=14;BYMINUTE=0`
- **Weekly digest + ledger sync** — `FREQ=WEEKLY;BYDAY=SU;BYHOUR=20;BYMINUTE=0`

---

## Requirements

- Python 3.9+ (standard library is enough for English monitoring and the ledger)
- For CNKI monitoring: `pip install playwright requests` and `playwright install msedge`
  (or `chromium`). The browser runs **headless in the background** by default;
  set `CNKI_HEADLESS=0` to see it while debugging.

## Repository layout

```
academic-lit-monitor/
  SKILL.md                       Trigger words and operating rules (read by the agent)
  README.md                      Chinese documentation
  README_EN.md                   This file
  config/*.template.json         6 config templates — copy to *.json and fill in
  scripts/
    setup.py                     Setup wizard / self-check / config writer
    config_loader.py             Centralized config access (masks secrets)
    relevance_engine.py          Domain-agnostic scoring engine
    runner.py                    English pipeline: collect -> score -> digest -> mail
    collector.py                 OpenAlex collector (by journal / by question)
    cnki_scan.py                 CNKI ToC discovery + metadata extraction (no PDF)
    cnki_watch.py                Chinese queue: merge -> score -> digest -> mail
    cnki_browser.py              Headless browser launcher
    webvpn.py                    Generic university WebVPN login
    ledger.py                    CSV ledger + WorkBuddy Library sync
    smtp_sender.py               Outbound mail (config-driven)
    llm_client.py                Optional LLM deep reading
    feishu_sync.py               Optional Feishu calendar / Bitable
  references/automation-prompts.md   Ready-to-paste scheduled-task prompts
  data/ state/ outbox/ outputs/     Runtime artifacts (created on first run)
```

## Scoring (0–100)

| Dimension | Weight | Meaning |
|---|---|---|
| d1 Research-fit | 0.35 | How many of **your** direction keywords are hit (title hits weigh more) |
| d2 Theoretical value | 0.20 | Does it speak to mechanism / logic / causality (generic academic wording only) |
| d3 Design value | 0.20 | Recognizable credible design: experiment / DiD / RDD / panel / case / computational text |
| d5 Project relevance | 0.15 | Overlap with **your** ongoing projects |
| d7 Maturity | 0.10 | Journal tier (set in `profile.json`), preprints down-weighted |

Grades: `critical ≥ 90` | `high ≥ 75` | `recommended ≥ 60` | `archive < 60` (thresholds editable).
Because the engine hard-codes **no field-specific terms**, switching research topics means
switching `profile.json` — nothing else.

## Ledger CSV columns

source / title / authors / journal / publication date / volume-issue / pages / DOI / URL /
abstract / keywords / score / grade / research direction / linked project / research design /
recommendation reason / first seen / last updated / status

## Operating rules (non-negotiable)

1. **No fabrication.** Unretrievable fields stay blank and are reported as such. Never invent
   abstracts, authors, scores, send results, or sync results.
2. **No full-text download.** Metadata only.
3. **Compliant access.** CNKI is reached through the installer's own institutional WebVPN;
   on hitting a slider CAPTCHA the run stops immediately and reports honestly.
4. **Rate restraint.** Randomized delay between articles (≈12 s by default).
5. **Privacy.** Credentials live only in `config/` — never in code, logs, or email bodies.

## Privacy & compliance

- The code contains **no personal information**; accounts, app passwords and API keys exist only
  in `config/*.json` (git-ignored).
- Only basic metadata is collected; no PDFs.
- CNKI access relies on the user's own institutional subscription. This project does not bypass
  any paywall or access control.

## License

MIT — see [LICENSE](LICENSE).
