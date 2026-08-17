import os
import requests

def send_telegram_digest(ranked_jobs):
    if not ranked_jobs:
        return

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    message = "🎯 *New Job Matches*\n\n"
    for job in ranked_jobs[:10]:
        message += (
            f"*{job['title']}* @ {job.get('company','?')}\n"
            f"📍 {job.get('location','?')} | Score: {job['score']}/10\n"
            f"💬 {job['reason']}\n"
            f"🔗 {job['link']}\n\n"
        )

    requests.post(url, data={
        "chat_id": chat_id,
        "text": message[:4000],
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    })
