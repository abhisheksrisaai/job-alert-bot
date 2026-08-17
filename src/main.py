import json
from fetch_jobs import fetch_all
from dedupe import filter_new, mark_seen
from rank_jobs import rank_jobs
from notify import send_telegram_digest

def main():
    with open("config/search_config.json") as f:
        search_config = json.load(f)

    with open("config/resume.txt") as f:
        resume_text = f.read()

    print("Fetching jobs (Bangalore, product/AI focus)...")
    all_jobs = fetch_all(search_config)
    print(f"Fetched {len(all_jobs)} jobs after location/keyword filters")

    new_jobs = filter_new(all_jobs)
    print(f"{len(new_jobs)} new jobs after dedupe")

    ranked = rank_jobs(new_jobs, resume_text, search_config)
    print(f"{len(ranked)} jobs passed Groq relevance filter")

    send_telegram_digest(ranked)
    mark_seen(new_jobs)
    print("Done.")

if __name__ == "__main__":
    main()
