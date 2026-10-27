"""Builds edhrec.xml from the EDHREC articles page.

Improvements over the old version:
  * Dates, authors and descriptions are read from the single article "card"
    instead of a wide surrounding area, which could pick up a neighbouring
    article's details.
  * Every article is remembered in edhrec-history.json, so an article never
    vanishes or changes date because of one bad run.
  * If the website is unreachable, the feed is rebuilt from what was remembered.
"""

import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import feedlib

BASE_URL = "https://edhrec.com"
ARCHIVE_URL = "https://edhrec.com/articles"
FEED_URL = f"{feedlib.SITE_BASE}/edhrec.xml"
HISTORY_FILE = "edhrec-history.json"
OUTPUT_FILE = "edhrec.xml"
MAX_PAGES = 10          # pages to read on the very first run
INCREMENTAL_PAGES = 3   # pages to read on later runs
MAX_ITEMS = 100
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)

DATE_PATTERN = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},\s+\d{4}\b"
)
EXCLUDED_SLUGS = {"for-writers", "authors", "tags", "tag", "author"}


def article_url(raw_href):
    """Return the full article URL if this link points to an article, else None."""
    href = urljoin(BASE_URL, raw_href)
    parsed = urlparse(href)
    if parsed.netloc != "edhrec.com":
        return None
    path = parsed.path.rstrip("/")
    if not path.startswith("/articles/"):
        return None
    remainder = path[len("/articles/"):]
    if not remainder or "/" in remainder:
        return None
    if remainder.lower() in EXCLUDED_SLUGS:
        return None
    return f"{BASE_URL}{path}"


def find_card(link):
    """Climb from the title link to the largest element that still
    contains only this one article."""
    card = link
    for _ in range(7):
        parent = card.parent
        if parent is None or parent.name in ("body", "html", "[document]"):
            break
        urls = {article_url(a["href"]) for a in parent.find_all("a", href=True)}
        urls.discard(None)
        if len(urls) > 1:
            break
        card = parent
    return card


def parse_date(text):
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    try:
        return datetime.strptime(match.group(0), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def find_date(link, card):
    published = parse_date(card.get_text(" ", strip=True))
    if published:
        return published
    # Fallback: the original, wider search, so nothing that used to work breaks.
    current = link
    for _ in range(7):
        if current is None:
            break
        published = parse_date(current.get_text(" ", strip=True))
        if published:
            return published
        current = current.parent
    return None


def find_author(card):
    author_link = card.find("a", href=re.compile(r"/authors?/"))
    if author_link:
        name = feedlib.clean(author_link.get_text(" ", strip=True))
        if name and len(name) < 100:
            return name
    text = card.get_text(" ", strip=True)
    match = re.search(r"\bby\s+([A-Z][\w.'\-]*(?:\s+[A-Z][\w.'\-]*){0,3})", text)
    if match:
        return match.group(1).strip()
    return ""


def find_description(card, title, author):
    text = card.get_text(" ", strip=True)
    text = text.replace(title, "", 1)
    text = DATE_PATTERN.sub("", text)
    if author:
        text = re.sub(r"\bby\s+" + re.escape(author), "", text, flags=re.IGNORECASE)
        text = text.replace(author, "", 1)
    text = feedlib.clean(text)
    if 30 <= len(text) < 1000:
        return text
    return ""


def extract_cards(soup):
    cards = {}
    for link in soup.find_all("a", href=True):
        url = article_url(link["href"])
        if not url:
            continue
        title = feedlib.clean(link.get_text(" ", strip=True))
        if len(title) < 5:
            continue
        if url in cards and len(title) <= len(cards[url]["title"]):
            continue

        card = find_card(link)
        published = find_date(link, card)
        if published is None:
            continue
        author = find_author(card)
        cards[url] = {
            "title": title,
            "link": url,
            "published": feedlib.to_iso(published),
            "author": author,
            "description": find_description(card, title, author),
        }
    return cards


def main():
    history = feedlib.load_history(HISTORY_FILE)
    session = feedlib.make_session(USER_AGENT)
    collected = {}
    fetch_error = None

    page_limit = INCREMENTAL_PAGES if history else MAX_PAGES
    for page in range(1, page_limit + 1):
        url = ARCHIVE_URL if page == 1 else f"{ARCHIVE_URL}?page={page}"
        print(f"Fetching EDHREC article page {page}: {url}")
        try:
            soup = BeautifulSoup(feedlib.fetch_text(session, url), "html.parser")
        except requests.RequestException as error:
            fetch_error = error
            print(f"Could not load {url}: {error}")
            break

        cards = extract_cards(soup)
        print(f"Page {page}: found {len(cards)} articles")
        if not cards:
            break

        unknown = [link for link in cards if link not in history and link not in collected]
        for link, card in cards.items():
            collected.setdefault(link, card)
        if history and not unknown:
            break
        time.sleep(1)

    if not collected and not history:
        print("ERROR: no EDHREC articles found and nothing saved from earlier runs.")
        sys.exit(1)

    items = feedlib.merge_items(history, list(collected.values()), MAX_ITEMS)
    new_count = sum(1 for item in items if item["link"] not in history)

    feedlib.save_history(HISTORY_FILE, items)
    feedlib.write_text(
        OUTPUT_FILE,
        feedlib.build_rss(
            title="EDHREC Articles",
            link=ARCHIVE_URL,
            description="Latest articles from EDHREC",
            feed_url=FEED_URL,
            items=items,
        ),
    )
    print(f"Wrote {OUTPUT_FILE}: {len(items)} articles ({new_count} new)")

    if fetch_error and not collected:
        sys.exit(1)  # feed was still written from saved data, but flag the problem


if __name__ == "__main__":
    main()
