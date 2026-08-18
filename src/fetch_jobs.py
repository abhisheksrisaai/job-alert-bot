import os
import json
from datetime import datetime
from urllib.parse import quote, urlparse

BANGALORE_ALIASES = ("bangalore", "bengaluru", "blr")
REMOTE_ALIASES = ("remote", "work from home", "wfh", "hybrid")
OTHER_CITY_KEYWORDS = (
    "hyderabad", "mumbai", "pune", "chennai", "delhi", "gurgaon", "noida", "kolkata",
)
JOB_URL_HINTS = (
    "job", "career", "apply", "opening", "intern", "greenhouse", "lever", "ashby",
    "workday", "greythr", "keka", "darwinbox", "pyjamahr", "zoho", "smartrecruiters",
)
SERPAPI_USAGE_FILE = "data/serpapi_usage.json"
DORK_QUERIES_FILE = "config/dork_queries.json"
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
    text = " ".join(
        [
            job.get("title") or "",
            job.get("company") or "",
            job.get("location") or "",
        ]
    ).lower()
    if any(city in text for city in OTHER_CITY_KEYWORDS):
        return False
    if any(alias in text for alias in REMOTE_ALIASES):
        return False
    if any(alias in text for alias in BANGALORE_ALIASES):
        return True
    loc = (job.get("location") or "").lower()
    if loc:
        return False
    # Dork/ATS hits often omit location; accept if no conflicting city/remote signals.
    return True


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
        return {"month": current_month, "count": 0, "dork_index": 0}
    with open(SERPAPI_USAGE_FILE, "r") as f:
        data = json.load(f)
    if data.get("month") != current_month:
        return {"month": current_month, "count": 0, "dork_index": 0}
    data.setdefault("dork_index", 0)
    return data


def _save_serpapi_usage(usage):
    os.makedirs("data", exist_ok=True)
    with open(SERPAPI_USAGE_FILE, "w") as f:
        json.dump(usage, f)


def _serpapi_budget_remaining(usage, search_config):
    monthly_cap = search_config.get("serpapi_monthly_limit", SERPAPI_MONTHLY_LIMIT)
    per_run_cap = search_config.get("serpapi_max_searches_per_run", 4)
    remaining_month = monthly_cap - usage["count"]
    return max(0, min(per_run_cap, remaining_month))


def _serpapi_search(params, usage):
    import requests

    if usage["count"] >= search_config_get_monthly_limit():
        return None, usage

    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = r.json()
    except requests.RequestException as exc:
        print(f"Warning: SerpAPI request failed: {exc}")
        return None, usage

    usage["count"] += 1
    _save_serpapi_usage(usage)

    if _serpapi_rate_limited(r, data):
        print(
            f"Warning: SerpAPI rate limit after {usage['count']} searches this month."
        )
        return None, usage
    if not r.ok:
        print(f"Warning: SerpAPI HTTP {r.status_code}")
        return None, usage
    return data, usage


def search_config_get_monthly_limit():
    return SERPAPI_MONTHLY_LIMIT


def _load_dork_config():
    with open(DORK_QUERIES_FILE, "r") as f:
        return json.load(f)


def _build_dork_query(entry, dork_config):
    if entry.get("full_query"):
        return entry["query"]
    return (
        f"{entry['query']} {dork_config['role_core']} "
        f"{dork_config['location_core']} {dork_config['exclusions']}"
    )


def _company_from_url(url):
    try:
        host = urlparse(url).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        parts = host.split(".")
        if len(parts) >= 2:
            return parts[0].replace("-", " ").title()
        return host
    except Exception:
        return "?"


def _organic_result_to_job(result):
    link = result.get("link", "")
    title = result.get("title", "")
    if not link or not title:
        return None
    link_lower = link.lower()
    if not any(hint in link_lower for hint in JOB_URL_HINTS):
        return None
    snippet = result.get("snippet", "")
    company = result.get("source") or _company_from_url(link)
    return {
        "title": title,
        "company": company,
        "location": snippet,
        "posted": "",
        "link": link,
        "source": "google_dork",
    }


def _next_dork_entries(dork_config, batch_size, usage):
    queries = dork_config.get("queries", [])
    if not queries:
        return []
    idx = usage.get("dork_index", 0)
    batch = []
    for _ in range(min(batch_size, len(queries))):
        batch.append(queries[idx % len(queries)])
        idx += 1
    usage["dork_index"] = idx % len(queries)
    _save_serpapi_usage(usage)
    return batch


def fetch_serpapi_dorks(search_config):
    usage = _load_serpapi_usage()
    budget = _serpapi_budget_remaining(usage, search_config)
    dork_batch_size = min(
        search_config.get("serpapi_dorks_per_run", 3),
        budget,
    )
    if dork_batch_size <= 0:
        print("Warning: SerpAPI budget exhausted; skipping Google dork searches.")
        return []

    try:
        dork_config = _load_dork_config()
    except OSError as exc:
        print(f"Warning: could not load dork queries: {exc}")
        return []

    entries = _next_dork_entries(dork_config, dork_batch_size, usage)
    all_jobs = []
    time_filter = dork_config.get("time_filter", "qdr:w")

    print(f"SerpAPI dorks: running {len(entries)} ATS portal queries (past week)...")
    for entry in entries:
        usage = _load_serpapi_usage()
        if _serpapi_budget_remaining(usage, search_config) <= 0:
            break

        query = _build_dork_query(entry, dork_config)
        print(f"SerpAPI dork [{entry['id']}]: {entry['name']}")
        params = {
            "engine": "google",
            "q": query,
            "api_key": os.environ["SERPAPI_KEY"],
            "num": 10,
            "tbs": time_filter,
        }
        data, usage = _serpapi_search(params, usage)
        if not data:
            break

        for result in data.get("organic_results", []):
            job = _organic_result_to_job(result)
            if job:
                all_jobs.append(job)

    print(f"SerpAPI dorks: {len(all_jobs)} job-like results")
    return all_jobs


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


def _roles_for_linkedin(search_config):
    return search_config.get("linkedin_roles") or search_config["roles"]


def fetch_linkedin_jobs(search_config):
    if not TINYFISH_AVAILABLE or os.environ.get("SKIP_TINYFISH") == "1":
        print("Skipping LinkedIn/TinyFish fetch (SDK unavailable or SKIP_TINYFISH=1).")
        return []

    try:
        client = TinyFish()
    except Exception as exc:
        print(f"Warning: TinyFish client init failed: {exc}; skipping LinkedIn.")
        return []

    all_jobs = []
    location = _linkedin_location(search_config)
    tpr = _posted_tpr(search_config)
    location_goal = _linkedin_location_goal(search_config)
    roles = _roles_for_linkedin(search_config)
    print(f"TinyFish: fetching {len(roles)} LinkedIn role searches...")

    for i, role in enumerate(roles, start=1):
        keywords = quote(role)
        url = (
            f"https://www.linkedin.com/jobs/search/?keywords={keywords}"
            f"&location={location}&f_TPR={tpr}"
        )
        print(f"TinyFish [{i}/{len(roles)}]: {role}")
        try:
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
                jobs_found = response.result.get("jobs", [])
                print(f"TinyFish [{i}/{len(roles)}]: {len(jobs_found)} jobs for '{role}'")
                all_jobs.extend(jobs_found)
            else:
                print(
                    f"Warning: TinyFish run incomplete for '{role}' "
                    f"(status={response.status.name}); skipping."
                )
        except Exception as exc:
            print(f"Warning: TinyFish failed for '{role}': {exc}; continuing.")
    return all_jobs


def get_job_link(job):
    apply_options = job.get("apply_options", [])
    if apply_options and apply_options[0].get("link"):
        return apply_options[0]["link"]
    related = job.get("related_links", [])
    if related and related[0].get("link"):
        return related[0]["link"]
    title = job.get("title", "")
    company = job.get("company_name", "")
    query = f"{title} {company}".replace(" ", "+")
    return f"https://www.google.com/search?q={query}&ibp=htl;jobs"


def _roles_for_google_jobs(search_config):
    return search_config.get("google_jobs_roles") or search_config["roles"][:3]


def fetch_serpapi_jobs(search_config):
    usage = _load_serpapi_usage()
    budget = _serpapi_budget_remaining(usage, search_config)
    google_jobs_cap = min(
        search_config.get("serpapi_google_jobs_per_run", 1),
        budget,
    )
    if google_jobs_cap <= 0:
        print("Warning: SerpAPI budget exhausted; skipping Google Jobs fetch.")
        return []

    roles = _roles_for_google_jobs(search_config)[:google_jobs_cap]
    all_jobs = []
    serp_location = "Bangalore, Karnataka, India"
    sample_logged = False
    location_suffix = (
        "Bengaluru"
        if search_config.get("location_strict")
        else "Bengaluru OR remote"
    )

    print(f"SerpAPI Google Jobs: {len(roles)} role searches...")
    for role in roles:
        usage = _load_serpapi_usage()
        if _serpapi_budget_remaining(usage, search_config) <= 0:
            break

        params = {
            "engine": "google_jobs",
            "q": f"{role} {location_suffix}",
            "location": serp_location,
            "api_key": os.environ["SERPAPI_KEY"],
        }
        data, usage = _serpapi_search(params, usage)
        if not data:
            break

        for job in data.get("jobs_results", []):
            if not sample_logged:
                print("SerpAPI Google Jobs sample:")
                print(json.dumps(job, indent=2))
                sample_logged = True
            all_jobs.append(
                {
                    "title": job.get("title"),
                    "company": job.get("company_name"),
                    "location": job.get("location"),
                    "posted": job.get("detected_extensions", {}).get("posted_at", ""),
                    "link": get_job_link(job),
                    "source": "google_jobs",
                }
            )
    return all_jobs


def fetch_all(search_config):
    jobs = []
    try:
        jobs += fetch_linkedin_jobs(search_config)
    except Exception as exc:
        print(f"Warning: LinkedIn/TinyFish fetch aborted: {exc}; continuing with SerpAPI.")
    jobs += fetch_serpapi_dorks(search_config)
    jobs += fetch_serpapi_jobs(search_config)
    return apply_search_filters(jobs, search_config)
