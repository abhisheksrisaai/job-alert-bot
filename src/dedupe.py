import json
import hashlib
import os

SEEN_FILE = "data/seen_jobs.json"

def job_id(job):
    key = f"{job.get('title','')}-{job.get('company','')}-{job.get('link','')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]

def load_seen():
    if not os.path.exists(SEEN_FILE):
        return set()
    with open(SEEN_FILE, "r") as f:
        return set(json.load(f))

def save_seen(seen_ids):
    os.makedirs("data", exist_ok=True)
    with open(SEEN_FILE, "w") as f:
        json.dump(list(seen_ids), f)

def filter_new(jobs):
    seen = load_seen()
    new_jobs = []
    for job in jobs:
        jid = job_id(job)
        if jid not in seen:
            job["_id"] = jid
            new_jobs.append(job)
    return new_jobs

def mark_seen(jobs):
    seen = load_seen()
    for job in jobs:
        seen.add(job["_id"])
    save_seen(seen)
