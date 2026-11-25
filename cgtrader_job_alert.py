#!/usr/bin/env python3
import json
import os
import re
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL = "https://www.cgtrader.com/3d-modeling-jobs/browse"
STATE_FILE = Path(__file__).with_name("seen_jobs.json")

LINK_PATTERN = re.compile(os.getenv("LINK_PATTERN") or r"/3d-modeling-jobs/.*\d{4,}")
IGNORE = ("/browse", "/find-freelance-projects")

KEYWORDS = [k.strip().lower() for k in os.getenv("KEYWORDS", "").split(",") if k.strip()]


def fetch_jobs():
    jobs = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page.goto(URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)
        for _ in range(3):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(1000)

        for a in page.query_selector_all("a[href]"):
            href = a.get_attribute("href") or ""
            if href.startswith("/"):
                href = "https://www.cgtrader.com" + href
            href = href.split("?")[0].split("#")[0]
            if "cgtrader.com" not in href:
                continue
            if any(href.rstrip("/").endswith(i) for i in IGNORE):
                continue
            if not LINK_PATTERN.search(href):
                continue
            title = " ".join((a.inner_text() or "").split()) or href.rsplit("/", 1)[-1]
            if href not in jobs or len(title) > len(jobs[href]):
                jobs[href] = title
        browser.close()
    return jobs


def notify(title, link):
    sent = False

    topic = os.getenv("NTFY_TOPIC")
    if topic:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=title.encode("utf-8"),
            headers={
                "Title": "New CGTrader job",
                "Click": link,
                "Tags": "briefcase",
            },
            timeout=20,
        )
        sent = True

    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat, "text": f"New CGTrader job:\n{title}\n{link}"},
            timeout=20,
        )
        sent = True

    if not sent:
        print(f"[no notifier configured] {title} -> {link}")


def main():
    debug = "--debug" in sys.argv
    jobs = fetch_jobs()

    if debug:
        print(f"Found {len(jobs)} project links:")
        for link, title in jobs.items():
            print(f"  {title[:60]:60}  {link}")
        return

    if not jobs:
        print("No jobs found this run (page may have failed to load).")
        sys.exit(1)

    first_run = not STATE_FILE.exists()
    seen = set(json.loads(STATE_FILE.read_text())) if not first_run else set()

    new = {l: t for l, t in jobs.items() if l not in seen}

    if first_run:
        print(f"First run: saved {len(jobs)} existing jobs, no alerts sent.")
    else:
        for link, title in new.items():
            if KEYWORDS and not any(k in title.lower() for k in KEYWORDS):
                continue
            notify(title, link)
        print(f"{len(new)} new job(s).")

    STATE_FILE.write_text(json.dumps(sorted(seen | set(jobs)), indent=2))


if __name__ == "__main__":
    main()
