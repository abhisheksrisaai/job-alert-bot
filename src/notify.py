import os
import requests


def _escape_html(text):
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def send_telegram_digest(ranked_jobs):
    if not ranked_jobs:
        print("No ranked jobs to send; skipping Telegram.")
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    message = "🎯 <b>New Job Matches</b>\n\n"
    for job in ranked_jobs[:10]:
        link = job.get("link", "")
        message += (
            f"<b>{_escape_html(job['title'])}</b> @ {_escape_html(job.get('company', '?'))}\n"
            f"📍 {_escape_html(job.get('location', '?'))} | Score: {job['score']}/10\n"
            f"💬 {_escape_html(job.get('reason', ''))}\n"
        )
        if link:
            message += f"🔗 <a href=\"{link}\">Apply</a>\n\n"
        else:
            message += "🔗 (no link)\n\n"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message[:4000],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        data = response.json()
        if response.ok and data.get("ok"):
            print(f"Telegram digest sent ({min(len(ranked_jobs), 10)} jobs).")
        else:
            print(f"Warning: Telegram send failed: {data}")
    except requests.RequestException as exc:
        print(f"Warning: Telegram request failed: {exc}")
