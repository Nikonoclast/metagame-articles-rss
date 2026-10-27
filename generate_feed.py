"""Builds feed.xml from the article archive on metagame.info.

Reads the archive pages directly (newest first), remembers every article it
has seen in metagame-articles.json, and always writes a feed, even if the
website is unreachable this run (it just reuses what it remembered).
"""

import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import feedlib

BASE = "https://metagame.info"
ARCHIVE = f"{BASE}/en-us/mtg/articles"
HISTORY_FILE = "metagame-articles.json"
OUTPUT_FILE = "feed.xml"
FEED_URL = f"{feedlib.SITE_BASE}/feed.xml"
MAX_PAGES = 8           # pages to read on the very first run
INCREMENTAL_PAGES = 3   # pages to read on later runs (new articles are always on top)
MAX_ITEMS = 100
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DATE = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}"
DATE_RE = re.compile(DATE)
ARTICLE_PATH = re.compile(r"^/en-us/mtg/articles/([^/]+)/?$")


def find_title(anchor, text, date_match, slug):
    heading = anchor.find(["h1", "h2", "h3", "h4", "h5", "h6"])
    if heading:
        title = feedlib.clean(heading.get_text(" ", strip=True))
        if title:
            return title
    # Archive cards read: "<title> article <title> shoppingmode <category> ..."
    match = re.match(r"^(.+?)\s+article\s+\1(?:\s|$)", text)
    if match:
        return match.group(1)
    match = re.match(r"^(.+?)\s+article\s+(?:shoppingmode|face)\b", text)
    if match:
        return match.group(1)
    # Sidebar cards read: "<category> · by <author> · <date> <title>"
    after = text[date_match.end():].strip()
    if after:
        return after
    return slug.replace("-", " ").title()


def parse_card(anchor):
    """Turn one <a> tag into an article dict, or None if it isn't an article card."""
    parsed = urlparse(urljoin(BASE, anchor.get("href", "")))
    if parsed.netloc not in ("metagame.info", "www.metagame.info"):
        return None
    match = ARTICLE_PATH.match(parsed.path)
    if not match:
        return None
    slug = match.group(1)

    text = feedlib.clean(anchor.get_text(" ", strip=True))
    date_match = DATE_RE.search(text)
    if not date_match:
        return None  # e.g. translated duplicate links in the sidebar
    try:
        published = datetime.strptime(date_match.group(0), "%b %d, %Y")
    except ValueError:
        return None
    published = published.replace(tzinfo=timezone.utc)

    author = category = ""
    found = re.search(r"\bface\s+(.+?)\s+" + DATE, text)
    if found:
        author = found.group(1)
    found = re.search(r"\bshoppingmode\s+(.+?)\s+favorite\b", text)
    if found:
        category = found.group(1)
    if not author:
        found = re.search(r"\bby\s+(.+?)\s+·\s+" + DATE, text)
        if found:
            author = found.group(1)
    if not category:
        found = re.match(r"^(.+?)\s+·\s+by\b", text)
        if found:
            category = found.group(1)

    description = category
    if author:
        description = f"{category} - by {author}" if category else f"By {author}"

    return {
        "title": find_title(anchor, text, date_match, slug),
        "link": f"{BASE}/en-us/mtg/articles/{slug}",
        "published": feedlib.to_iso(published),
        "author": author,
        "category": category,
        "description": description,
    }


def extract_cards(soup):
    cards = {}
    for anchor in soup.find_all("a", href=True):
        card = parse_card(anchor)
        if not card:
            continue
        existing = cards.get(card["link"])
        if existing is None or len(card["title"]) > len(existing["title"]):
            cards[card["link"]] = card
    return cards


def main():
    history = feedlib.load_history(HISTORY_FILE)
    session = feedlib.make_session(USER_AGENT)
    collected = {}
    fetch_error = None

    page_limit = INCREMENTAL_PAGES if history else MAX_PAGES
    for page in range(1, page_limit + 1):
        url = ARCHIVE if page == 1 else f"{ARCHIVE}?page={page}"
        try:
            page_html = feedlib.fetch_text(session, url)
        except requests.RequestException as error:
            fetch_error = error
            print(f"Could not load {url}: {error}")
            break

        cards = extract_cards(BeautifulSoup(page_html, "html.parser"))
        print(f"Page {page}: found {len(cards)} articles")
        if not cards:
            break

        unknown = [link for link in cards if link not in history and link not in collected]
        for link, card in cards.items():
            collected.setdefault(link, card)

        # Once a whole page is already known there is nothing older to find.
        if history and not unknown:
            break
        time.sleep(1)

    if not collected and not history:
        print("ERROR: no articles found and nothing saved from earlier runs.")
        sys.exit(1)

    items = feedlib.merge_items(history, list(collected.values()), MAX_ITEMS)
    new_count = sum(1 for item in items if item["link"] not in history)

    feedlib.save_history(HISTORY_FILE, items)
    feedlib.write_text(
        OUTPUT_FILE,
        feedlib.build_rss(
            title="Metagame.info - Magic: The Gathering Articles",
            link=ARCHIVE,
            description="Latest Magic: The Gathering articles from Metagame.info",
            feed_url=FEED_URL,
            items=items,
        ),
    )
    print(f"Wrote {OUTPUT_FILE}: {len(items)} articles ({new_count} new)")

    if fetch_error and not collected:
        # Feed was still written from saved data, but flag the problem.
        sys.exit(1)


if __name__ == "__main__":
    main()
