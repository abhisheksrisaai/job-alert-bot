import os
import json
from datetime import datetime
from urllib.parse import quote

BANGALORE_ALIASES = ("bangalore", "bengaluru", "blr")
REMOTE_ALIASES = ("remote", "work from home", "wfh")
SERPAPI_USAGE_FILE = "data/serpapi_usage.json"
SERPAPI_MONTHLY_LIMIT = 100

try:
    from tinyfish import TinyFish, BrowserProfile

    TINYFISH_AVAILABLE = True
except ImportError:
    TINYFISH_AVAILABLE = False


def _linkedin_location(search_config):
    for loc in search_config.get("locations", ["Bangalore"]):
        if loc.lower() not in ("remote", "india"):
            return quote(f"{loc}, Karnataka, India")
    return quote("Bangalore, Karnataka, India")


def _linkedin_location_goal(search_config):
    if search_config.get("location_strict"):
        return "Only include jobs located in Bangalore or Bengaluru."
    return (
        "Include jobs in Bangalore/Bengaluru, Remote, or India-wide roles. "
        "Exclude jobs that are clearly limited to other cities only."
    )


def _posted_tpr(search_config):
    hours = search_config.get("posted_within_hours", 24)
    return f"r{hours * 3600}"


def _matches_location(job, search_config):
    if not search_config.get("location_strict"):
        return True
    loc = (job.get("location") or "").lower()
    if not loc:
        return False
    configured = [l.lower() for l in search_config.get("locations", [])]
    if any(alias in loc for alias in BANGALORE_ALIASES):
        return True
    if any(alias in loc for alias in REMOTE_ALIASES):
        return True
    if "india" in configured and "india" in loc:
        return True
    return any(loc_word in loc for loc_word in configured)


def _is_excluded(job, search_config):
    text = " ".join(
        [
            job.get("title") or "",
            job.get("company") or "",
            job.get("location") or "",
        ]
    ).lower()
    for keyword in search_config.get("exclude_keywords", []):
        if keyword.lower() in text:
            return True
    return False


def apply_search_filters(jobs, search_config):
    filtered = []
    for job in jobs:
        if not job.get("title") or not job.get("link"):
            continue
        if _is_excluded(job, search_config):
            continue
        if not _matches_location(job, search_config):
            continue
        filtered.append(job)
    return filtered


def _load_serpapi_usage():
    current_month = datetime.now().strftime("%Y-%m")
    if not os.path.exists(SERPAPI_USAGE_FILE):
        return {"month": current_month, "count": 0}
    with open(SERPAPI_USAGE_FILE, "r") as f:
        data = json.load(f)
    if data.get("month") != current_month:
        return {"month": current_month, "count": 0}
    return data


def _save_serpapi_usage(usage):
    os.makedirs("data", exist_ok=True)
    with open(SERPAPI_USAGE_FILE, "w") as f:
        json.dump(usage, f)


def _serpapi_rate_limited(response, data):
    if response.status_code == 429:
        return True
    if isinstance(data, dict) and "error" in data:
        error_text = str(data.get("error", "")).lower()
        if any(
            token in error_text
            for token in ("rate", "limit", "quota", "exceeded", "too many")
        ):
            return True
    return False


def fetch_linkedin_jobs(search_config):
    if not TINYFISH_AVAILABLE or os.environ.get("SKIP_TINYFISH") == "1":
        print("Skipping LinkedIn/TinyFish fetch (SDK unavailable or SKIP_TINYFISH=1).")
        return []

    client = TinyFish()
    all_jobs = []
    location = _linkedin_location(search_config)
    tpr = _posted_tpr(search_config)
    location_goal = _linkedin_location_goal(search_config)

    for role in search_config["roles"]:
        keywords = quote(role)
        url = (
            f"https://www.linkedin.com/jobs/search/?keywords={keywords}"
            f"&location={location}&f_TPR={tpr}"
        )
        response = client.agent.run(
            goal=(
                "Extract all job postings visible on this page: title, company name, "
                "location, posted date, and the direct apply/job link. "
                f"{location_goal}"
            ),
            url=url,
            browser_profile=BrowserProfile.STEALTH,
            output_schema={
                "type": "object",
                "properties": {
                    "jobs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "company": {"type": "string"},
                                "location": {"type": "string"},
                                "posted": {"type": "string"},
                                "link": {"type": "string"},
                            },
                            "required": ["title", "company", "link"],
                        },
                    }
                },
                "required": ["jobs"],
            },
        )
        if response.status.name == "COMPLETED":
            all_jobs.extend(response.result.get("jobs", []))
    return all_jobs


def fetch_serpapi_jobs(search_config):
    import requests

    usage = _load_serpapi_usage()
    if usage["count"] >= SERPAPI_MONTHLY_LIMIT:
        print(
            f"Warning: SerpAPI monthly limit ({SERPAPI_MONTHLY_LIMIT}) reached "
            f"({usage['count']} searches this month); skipping SerpAPI fetch."
        )
        return []

    all_jobs = []
    serp_location = "Bangalore, Karnataka, India"

    for role in search_config["roles"]:
        if usage["count"] >= SERPAPI_MONTHLY_LIMIT:
            print(
                f"Warning: SerpAPI monthly limit ({SERPAPI_MONTHLY_LIMIT}) reached; "
                "stopping SerpAPI fetch."
            )
            break

        params = {
            "engine": "google_jobs",
            "q": f"{role} Bangalore OR remote",
            "location": serp_location,
            "api_key": os.environ["SERPAPI_KEY"],
        }
        try:
            r = requests.get("https://serpapi.com/search", params=params, timeout=30)
            data = r.json()
        except requests.RequestException as exc:
            print(f"Warning: SerpAPI request failed for '{role}': {exc}")
            continue

        usage["count"] += 1
        _save_serpapi_usage(usage)

        if _serpapi_rate_limited(r, data):
            print(
                f"Warning: SerpAPI rate limit hit after {usage['count']} searches "
                f"this month; skipping remaining SerpAPI roles."
            )
            break

        if not r.ok:
            print(f"Warning: SerpAPI returned HTTP {r.status_code} for '{role}'; skipping.")
            continue

        for job in data.get("jobs_results", []):
            all_jobs.append(
                {
                    "title": job.get("title"),
                    "company": job.get("company_name"),
                    "location": job.get("location"),
                    "posted": job.get("detected_extensions", {}).get("posted_at", ""),
                    "link": job.get("related_links", [{}])[0].get(
                        "link", job.get("job_id", "")
                    ),
                }
            )
    return all_jobs


def fetch_all(search_config):
    # TinyFish/LinkedIn is primary; SerpAPI supplements when quota allows.
    jobs = []
    jobs += fetch_linkedin_jobs(search_config)
    jobs += fetch_serpapi_jobs(search_config)
    return apply_search_filters(jobs, search_config)
