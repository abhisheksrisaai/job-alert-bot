import os
import json
import re
import time
from groq import Groq

DEFAULT_MODEL = "openai/gpt-oss-20b"
BATCH_SIZE = 5
RESUME_MAX_CHARS = 1200
PRIORITY_BONUS = 2

PRIORITY_COMPANIES = [
    "Razorpay",
    "Flipkart",
    "Swiggy",
    "Meesho",
    "CRED",
    "PhonePe",
    "Freshworks",
    "Atlassian",
    "Zeta",
    "Groww",
    "Dunzo",
    "Rippling",
    "Hasura",
    "Postman",
  # Startups (early/growth stage)
    "Zolve",
    "Slintel",
    "Whatfix",
    "Chargebee",
    "Zeotap",
    "Fyle",
    "Plum",
    "Jupiter",
    "Fi Money",
    "Khatabook",
    "Vahan",
    "Setu",
    "Juspay",
    "Recko",
    "Anyplace",
    "Toplyne",
    "Airbase",
]


def _condensed_resume(resume_text):
    if len(resume_text) <= RESUME_MAX_CHARS:
        return resume_text
    return resume_text[:RESUME_MAX_CHARS] + "\n...[resume truncated for token limits]"


def _priority_bonus(job):
    company = (job.get("company") or "").lower()
    for name in PRIORITY_COMPANIES:
        if name.lower() in company:
            return PRIORITY_BONUS
    return 0


def _build_prompt(jobs_text, resume_text, search_config):
    locations = ", ".join(search_config.get("locations", ["Bangalore", "Bengaluru", "Remote", "India"]))
    focus_areas = search_config.get("focus_areas", [])
    prefer_product = search_config.get("prefer_product_companies", True)
    location_strict = search_config.get("location_strict", False)
    focus_text = "\n".join(f"- {area}" for area in focus_areas)
    product_pref = (
        "Prefer product-based technology companies (SaaS, product startups, in-house product teams). "
        "Penalize IT services/consulting body-shopping roles (e.g. TCS, Infosys, Wipro, Cognizant bench roles)."
        if prefer_product
        else ""
    )

    if location_strict:
        location_rule = (
            f"Location: STRICTLY {locations} on-site only. "
            "Mark relevant=false for remote, hybrid, work-from-home, or roles in other Indian cities."
        )
    else:
        location_rule = (
            f"Location: Prefer {locations}. Bangalore/Bengaluru is ideal; Remote and India-wide roles are also acceptable. "
            "Reject roles that are clearly tied to other Indian cities only (e.g. Hyderabad-only, Pune-only)."
        )

    priority_names = ", ".join(PRIORITY_COMPANIES)
    return f"""Here is my resume:
{_condensed_resume(resume_text)}

Here are new job postings:
{jobs_text}

RANKING RULES:
- {location_rule}
- Experience: internship or new-grad / entry-level only (final-year B.Tech student, graduating May 2027).
- Focus areas:
{focus_text}
- {product_pref}
- TOP PRIORITY (highest scores): AI-assisted engineering, LLM/RAG, and QA automation/Playwright (SDET) roles — this candidate has deep experience in both.
- ALSO VALID (score normally, do NOT auto-reject): Product Engineer Intern, Data Analyst Intern, general SWE/full-stack intern roles.
- Priority companies (bonus signal, not required): {priority_names}
- Startup-friendly scoring (general signal, not limited to the list above):
  When scoring, also give a positive signal (not just to PRIORITY_COMPANIES) to:
  - Early-stage/Series A-C startups building product (not IT services/staffing/bench roles)
  - Roles explicitly mentioning "founding engineer," "early team," "startup," or small team size
  - YC-backed or well-known Indian startup ecosystem companies, even if not in the fixed priority list
  Do NOT penalize a company just because it is small or unfamiliar — judge by role substance
  (AI-assisted engineering, product work) not company size/brand recognition.

For each job, return ONLY a JSON array (no other text) with objects:
{{"index": <number>, "relevant": true/false, "score": 0-10, "reason": "<one short sentence>"}}

Score 8-10: strong fit for AI/full-stack/SDET intern or new grad (especially AI+QA combo or priority product companies).
Score 6-7: reasonable fit but weaker alignment on skills, location, or company type."""


def _parse_rankings(text):
    text = (text or "").strip()
    text = text.replace("```json", "").replace("```", "").strip()
    if not text:
        return []
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[[\s\S]*\]", text)
        if match:
            return json.loads(match.group())
        print(f"Warning: could not parse Groq rankings: {text[:200]}")
        return []


def _rank_batch(client, model, batch, resume_text, search_config):
    jobs_text = "\n".join(
        f"{i+1}. {j['title']} at {j.get('company', '?')} ({j.get('location', '?')}) - {j['link']}"
        for i, j in enumerate(batch)
    )
    prompt = _build_prompt(jobs_text, resume_text, search_config)
    response = client.chat.completions.create(
        model=model,
        max_tokens=2000,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    return _parse_rankings(text)


def rank_jobs(new_jobs, resume_text, search_config=None):
    if not new_jobs:
        return []

    search_config = search_config or {}
    min_score = search_config.get("min_relevance_score", 8)

    client = Groq(api_key=os.environ["GROQ_API_KEY"])
    model = os.environ.get("GROQ_MODEL", DEFAULT_MODEL)

    results = []
    for batch_start in range(0, len(new_jobs), BATCH_SIZE):
        batch = new_jobs[batch_start:batch_start + BATCH_SIZE]
        try:
            rankings = _rank_batch(client, model, batch, resume_text, search_config)
        except Exception as exc:
            print(f"Warning: Groq batch failed ({exc}); skipping batch.")
            rankings = []
        for r in rankings:
            if not r.get("relevant"):
                continue
            idx = r.get("index")
            if not isinstance(idx, int) or idx < 1 or idx > len(batch):
                continue
            job = batch[idx - 1]
            raw_score = r.get("score", 0)
            bonus = _priority_bonus(job)
            final_score = min(10, raw_score + bonus)
            if final_score < min_score:
                continue
            job["score"] = final_score
            if bonus:
                job["reason"] = f"{r.get('reason', '')} (+{bonus} priority company)"
            else:
                job["reason"] = r.get("reason", "")
            results.append(job)
        time.sleep(1)

    return sorted(results, key=lambda x: -x["score"])
