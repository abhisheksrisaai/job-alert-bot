# Job Alert Automation

Scheduled pipeline that finds new Bangalore job postings for AI/product engineering and SDET roles, deduplicates, ranks relevance with Groq (Llama 3.3 70B) against your resume, and sends a Telegram digest. Runs on GitHub Actions cron — no server required.

## How it works

```
[GitHub Actions cron, every 4 hours]
        ↓
[fetch_jobs.py] → TinyFish (LinkedIn) + SerpAPI (Google Jobs), Bangalore only
        ↓
[dedupe.py] → compares against seen_jobs.json, keeps only new
        ↓
[rank_jobs.py] → Groq scores relevance vs resume (product co. + AI/SDET focus)
        ↓
[notify.py] → Telegram digest of top matches
        ↓
[update seen_jobs.json, commit back to repo]
```

## Target profile (configured for Abhishek)

- **Location**: Bangalore / Bengaluru only (strict)
- **Company type**: product-based tech companies preferred over IT services
- **Roles**: AI/ML intern, SWE intern, SDET/QA automation intern, full-stack intern
- **Strengths**: FastAPI, React, Groq/RAG, Playwright, CI/CD, Azure

## Setup

### 1. API keys

| Variable | Where to get it |
|----------|-----------------|
| `TINYFISH_API_KEY` | [agent.tinyfish.ai/api-keys](https://agent.tinyfish.ai/api-keys) |
| `SERPAPI_KEY` | [serpapi.com](https://serpapi.com) (free tier) |
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) (free tier) |
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` → `/newbot` |
| `TELEGRAM_CHAT_ID` | Message your bot, then `getUpdates` on the Telegram API |

Copy `.env.example` to `.env` and fill in values. **Never commit `.env` or put real keys in `.env.example`.**

For GitHub Actions, add all secrets under **Repo Settings → Secrets → Actions**.

### 2. Configure search

Edit `config/search_config.json` for roles, `exclude_keywords`, and `min_relevance_score`.

### 3. Resume

`config/resume.txt` holds your plain-text resume for Groq ranking context.

### 4. Test

```bash
pip install -r requirements.txt
cp .env.example .env   # if not already created
python src/main.py
```

Trigger manually from **Actions → Job Alert Check → Run workflow** before relying on cron.

## Cost awareness

- **TinyFish**: metered after free tier; 7 roles × every 4h adds up — consider trimming `roles` or cron to twice daily.
- **SerpAPI**: ~100 free searches/month; 7 roles × 6 runs/day exceeds this quickly.
- **Groq**: generous free tier; ranking cost is negligible.

## Tuning

- Raise `min_relevance_score` in `search_config.json` if digests are noisy.
- Add company names to `exclude_keywords` for firms you want to skip.
- Drop TinyFish LinkedIn fetch if flaky; SerpAPI alone is simpler.
