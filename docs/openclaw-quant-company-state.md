# OpenClaw Quant Company State

Snapshot date: 2026-05-11

This document records the current OpenClaw Discord multi-agent setup as a
sanitized operational snapshot. It intentionally excludes Discord bot tokens,
provider API keys, gateway tokens, and raw `openclaw.json` secrets.

## Company Design

The OpenClaw Discord team is modeled as a quant investment company. The current
live OpenClaw config contains 9 configured agents; the 10th role below is a
recommended open seat.

| Agent | Company Role | Responsibility |
| --- | --- | --- |
| TianClaws | CEO / PM / dispatch center | Agenda routing, research meetings, decision closure, portfolio priorities |
| Jim Simons | CIO / Head of Quant Research | Alpha hypotheses, factor research, statistical testing, backtest discipline |
| Jeff Dean | Head of AI Infra | Data and model infrastructure, LLM research pipeline, compute efficiency |
| Linus Torvalds | CTO / Trading Platform | Trading systems, code quality, tooling, complexity review |
| Lisa Su | Head of Compute & Semiconductor Strategy | AI compute, semiconductor supply chain, hardware cycles, compute supply |
| 段永平 | Quality & Long-Term Value PM | Quality factors, cash flow, business durability, long-horizon sanity checks |
| 沈南鹏 | China / Private Market Strategy | China tech, private market signals, industry trends, founder and organization judgment |
| Marc Andreessen | Tech Megatrends PM | AI/software/platform trends, risk asset narratives, innovation cycles |
| Julie Sweet | COO / Enterprise Adoption Analyst | Enterprise AI adoption, client budgets, consulting and IT spending, implementation validation |
| Open seat | CRO / Risk Officer | Drawdown control, position limits, compliance, model failure, kill switch |

## Agent Skill Assignments

Skills are installed per agent workspace rather than globally, to keep each
agent focused and reduce accidental prompt noise.

| Agent | Skills |
| --- | --- |
| TianClaws | `discord-agent-communication`, `finance`, `finance-lite`, `macro-news-signal`, `news`, `risk` |
| Jim Simons | `empyrical-risk-metrics`, `finance`, `finance-lite`, `macro-news-signal`, `portfolio-risk-manager`, `quantitative-research`, `trading-devbox` |
| Jeff Dean | `github`, `github-repo-deep-dive`, `quantitative-research`, `tech-data-playbook`, `tech-stack-evaluator` |
| Linus Torvalds | `github`, `github-repo-deep-dive`, `tech-debt-tracker`, `tech-security-audit`, `trading-devbox` |
| Lisa Su | `finance`, `finance-lite`, `finance-radar`, `tech-news`, `tech-stack-evaluator` |
| 段永平 | `finance`, `finance-analysis`, `investment-risk-scanner`, `portfolio-risk-manager` |
| 沈南鹏 | `desk-research-skill`, `eastmoney-news`, `finance`, `market-research`, `prospect-research`, `security-portfolio-risk`, `tushare-finance` |
| Marc Andreessen | `github-ai-trends`, `github-trending-feed`, `in-depth-research`, `market-research`, `tech-news` |
| Julie Sweet | `desk-research-skill`, `finance-lite`, `macro-news-signal`, `market-research`, `prospect-research`, `risk` |

## Replaced Skills

The following skills were disabled because they were not currently usable in the
Linux OpenClaw container or required missing credentials:

| Disabled Skill | Reason | Replacement |
| --- | --- | --- |
| `market-news` | Requires `os: win32` | `news`, `finance-lite`, `macro-news-signal`, `tech-news`, `eastmoney-news` |
| `financial-news` | Requires `pip` and `TUSHARE_TOKEN` | `finance-lite`, `macro-news-signal`, `eastmoney-news` |
| `oraclaw-risk` | Requires `ORACLAW_API_KEY` | `portfolio-risk-manager`, `empyrical-risk-metrics`, `risk`, `security-portfolio-risk` |

Disabled skill directories were moved under timestamped `.disabled-*` folders in
their agent workspaces rather than deleted.

## Persona Updates

Each agent `SOUL.md` now includes a "quant company role and human texture" block
with company responsibility, MBTI-flavored behavior, conversational quirks, and
quant-company reflexes. The intent is to make the agents feel like distinct
colleagues with compatible but conflicting viewpoints:

| Agent | Personality Direction |
| --- | --- |
| TianClaws | ENTJ-A with ENFJ social radar; meeting control, agenda routing, asks for edge/risk/owner |
| Jim Simons | INTP/INTJ; skeptical, data-first, worries about p-hacking and out-of-sample failure |
| Jeff Dean | INTJ; calm systems thinker, failure modes, observability, reproducibility |
| Linus Torvalds | ISTP/INTP; direct engineering critic, complexity control, production reliability |
| Lisa Su | ENTJ/ISTJ; roadmap, execution, hardware delivery, supply-chain realism |
| 段永平 | INTP/ISTP; plain-language business judgment, margin of safety, low-drama value checks |
| 沈南鹏 | ENTJ; fast market/team judgment, China tech and private-market sensitivity |
| Marc Andreessen | ENTP; platform narratives, 10x shifts, energetic but subject to quant validation |
| Julie Sweet | ESTJ/ENTJ; operating model, adoption, ownership, metrics, enterprise execution |

The persona blocks also preserve safety boundaries: agents do not claim to be the
real public figures and do not claim to represent their companies.

## Live Verification Summary

Last checked on the live container:

- OpenClaw container: `playground-tianclaws-zamuig-openclaw-1`
- Discord accounts for Lisa Su and Julie Sweet were connected and working after
  restart.
- Replacement skills were visible to model for key affected agents:
  - TianClaws: `finance_lite`, `macro-news-signal`, `news`, `risk`
  - Jim Simons: `empyrical-risk-metrics`, `finance_lite`, `macro-news-signal`
  - 沈南鹏: `eastmoney-news`, `security-portfolio-risk`, `tushare-finance`
  - Lisa Su: `finance_lite`, `finance-radar`, `tech-news`
  - Julie Sweet: `finance_lite`, `macro-news-signal`, `risk`

Known non-blocking issue:

- TianClaws still has `taskflow` installed but it requires `OPENCLAW_WORKSPACE`.
  `taskflow-inbox-triage` remains visible, and this does not affect the quant
  company skill replacement set.

## Follow-Up

Recommended next step: create the 10th OpenClaw agent for the CRO / Risk Officer
seat, then install:

- `risk`
- `portfolio-risk-manager`
- `position-risk-manager`
- `empyrical-risk-metrics`
- `security-portfolio-risk`
