"""Builds wizards-mtg.xml from the DailyMTG news archive.

Speed-up over the old version: publication dates are remembered in
wizards-history.json, so only articles never seen before need their own page
downloaded (and those downloads happen several at a time).
If the website is unreachable, the feed is rebuilt from what was remembered.
"""

import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import feedlib

BASE = "https://www.magic.wizards.com"
ARCHIVE = f"{BASE}/en/news/archive"
HISTORY_FILE = "wizards-history.json"
OUTPUT_FILE = "wizards-mtg.xml"
FEED_URL = f"{feedlib.SITE_BASE}/wizards-mtg.xml"
MAX_PAGES = 10          # pages to read on the very first run
INCREMENTAL_PAGES = 3   # pages to read on later runs (new articles are always on top)
MAX_ITEMS = 100
WORKERS = 4
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/150.0 Safari/537.36"
)

CATEGORY_ENDINGS = (
    "/announcements",
    "/feature",
    "/making-magic",
    "/mtg-arena",
    "/card-image-gallery",
    "/podcasts",
)
DATE_RE = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}\b"
)
META_NAMES = [
    ("property", "article:published_time"),
    ("name", "article:published_time"),
    ("property", "og:published_time"),
]


def extract_article_links(soup):
    """Return {link: title} for every article link on an archive page."""
    articles = {}
    for anchor in soup.find_all("a", href=True):
        href = urljoin(BASE, anchor["href"])
        if "/en/news/" not in href:
            continue
        # Skip archive/pagination pages and anything with a query string.
        if "/en/news/archive" in href or "?" in href or "#" in href:
            continue
        if href.rstrip("/") == f"{BASE}/en/news":
            continue
        if href.rstrip("/").endswith(CATEGORY_ENDINGS):
            continue
        title = feedlib.clean(anchor.get_text(" ", strip=True))
        if not title:
            continue
        # The same article can be linked twice; keep the more descriptive title.
        if len(title) > len(articles.get(href, "")):
            articles[href] = title
    return articles


def parse_iso(text):
    try:
        moment = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def find_key(data, key):
    """Search nested JSON for the first value stored under `key`."""
    if isinstance(data, dict):
        if key in data and isinstance(data[key], str):
            return data[key]
        for value in data.values():
            found = find_key(value, key)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_key(value, key)
            if found:
                return found
    return None


def parse_article_date(soup):
    # 1. Standard page metadata.
    for attribute, value in META_NAMES:
        tag = soup.find("meta", attrs={attribute: value})
        if tag and tag.get("content"):
            moment = parse_iso(tag["content"])
            if moment:
                return moment
    # 2. Structured data embedded in the page.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        found = find_key(data, "datePublished")
        if found:
            moment = parse_iso(found)
            if moment:
                return moment
    # 3. A <time> tag.
    tag = soup.find("time", attrs={"datetime": True})
    if tag:
        moment = parse_iso(tag["datetime"])
        if moment:
            return moment
    # 4. Last resort: first written date on the page, e.g. "Jul 13, 2026".
    match = DATE_RE.search(feedlib.clean(soup.get_text(" ", strip=True)))
    if match:
        try:
            return datetime.strptime(match.group(), "%b %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def fetch_article(session, link, title):
    """Download one article page and return it as a dated article (or None)."""
    try:
        soup = BeautifulSoup(feedlib.fetch_text(session, link), "html.parser")
    except requests.RequestException as error:
        print(f"Could not fetch article: {link} ({error})")
        return None
    published = parse_article_date(soup)
    if published is None:
        print(f"No publication date found: {link}")
        return None
    return {"title": title, "link": link, "published": feedlib.to_iso(published)}


def main():
    history = feedlib.load_history(HISTORY_FILE)
    session = feedlib.make_session(USER_AGENT)
    found = {}
    fetch_error = None

    page_limit = INCREMENTAL_PAGES if history else MAX_PAGES
    for page in range(1, page_limit + 1):
        url = f"{ARCHIVE}?author=all&category=all&order=newest&page={page}&search="
        try:
            soup = BeautifulSoup(feedlib.fetch_text(session, url), "html.parser")
        except requests.RequestException as error:
            fetch_error = error
            print(f"Could not fetch archive page {page}: {error}")
            break

        links = extract_article_links(soup)
        print(f"Archive page {page}: found {len(links)} possible articles")
        if not links:
            break

        unknown = [link for link in links if link not in history and link not in found]
        for link, title in links.items():
            if len(title) > len(found.get(link, "")):
                found[link] = title

        # A whole page of already-known articles means nothing newer is left.
        if history and not unknown:
            break
        time.sleep(1)

    to_fetch = [(link, title) for link, title in found.items() if link not in history]
    to_fetch = to_fetch[:MAX_ITEMS]
    print(f"{len(to_fetch)} new articles to look up ({len(history)} already remembered)")

    new_items = []
    if to_fetch:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = pool.map(lambda pair: fetch_article(session, *pair), to_fetch)
            new_items = [item for item in results if item]

    if not history and not new_items:
        print("ERROR: no Wizards articles found and nothing saved from earlier runs.")
        sys.exit(1)

    items = feedlib.merge_items(history, new_items, MAX_ITEMS)
    feedlib.save_history(HISTORY_FILE, items)
    feedlib.write_text(
        OUTPUT_FILE,
        feedlib.build_rss(
            title="Magic: The Gathering \u2014 DailyMTG",
            link=ARCHIVE,
            description="Latest Magic: The Gathering articles and news from Wizards of the Coast.",
            feed_url=FEED_URL,
            items=items,
        ),
    )
    print(f"Wrote {OUTPUT_FILE}: {len(items)} articles ({len(new_items)} new)")

    if fetch_error and not new_items:
        sys.exit(1)  # feed was still written from saved data, but flag the problem


if __name__ == "__main__":
    main()
