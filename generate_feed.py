import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://metagame.info"
ARCHIVE = f"{BASE}/en-us/mtg/articles"
OUTPUT = Path("feed.xml")
MAX_PAGES = 100
MAX_ITEMS = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MetagameRSS/1.0; +https://github.com/)"
}

def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()

def parse_date(text):
    # Metagame currently renders English dates like "Aug 05, 2026".
    m = re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2},\s+\d{4}\b",
        text,
    )
    if not m:
        return None
    try:
        return datetime.strptime(m.group(), "%b %d, %Y").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None

def article_links(soup):
    seen = set()
    for a in soup.select('a[href*="/en-us/mtg/articles/"]'):
        href = urljoin(BASE, a.get("href", ""))
        parsed = urlparse(href)
        # Keep only article detail pages, not the archive itself.
        if parsed.path.rstrip("/") == "/en-us/mtg/articles":
            continue
        if not parsed.path.startswith("/en-us/mtg/articles/"):
            continue
        title = clean(a.get_text(" ", strip=True))
        if not title or href in seen:
            continue
        seen.add(href)
        yield a, href, title

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def collect():
    items = {}
    for page in range(1, MAX_PAGES + 1):
        url = ARCHIVE if page == 1 else f"{ARCHIVE}?page={page}"
        soup = fetch(url)
        found = 0

        for a, href, title in article_links(soup):
            found += 1
            # The archive card contains the publication date. If it is not
            # available there, use the article page as a fallback.
            card = a.parent
            card_text = clean(card.get_text(" ", strip=True))
            published = parse_date(card_text)

            if published is None:
                try:
                    article = fetch(href)
                    published = parse_date(clean(article.get_text(" ", strip=True)))
                except requests.RequestException:
                    published = None

            if published is None:
                # Keep the item, but place it at the end rather than
                # inventing a publication date.
                published = datetime(1970, 1, 1, tzinfo=timezone.utc)

            items[href] = {
                "title": title,
                "link": href,
                "published": published,
            }

        if found == 0:
            break

    return sorted(
        items.values(),
        key=lambda x: (x["published"], x["title"]),
        reverse=True,
    )[:MAX_ITEMS]

def rss(items):
    now = datetime.now(timezone.utc)
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        "    <title>Metagame.info — Magic: The Gathering Articles</title>",
        f"    <link>{html.escape(ARCHIVE)}</link>",
        "    <description>All English Magic: The Gathering article updates from Metagame.info.</description>",
        "    <language>en-us</language>",
        f"    <lastBuildDate>{format_datetime(now, usegmt=True)}</lastBuildDate>",
    ]

    for item in items:
        title = html.escape(item["title"])
        link = html.escape(item["link"])
        guid = html.escape(item["link"])
        pub = format_datetime(item["published"], usegmt=True)
        out.extend([
            "    <item>",
            f"      <title>{title}</title>",
            f"      <link>{link}</link>",
            f"      <guid isPermaLink=\"true\">{guid}</guid>",
            f"      <pubDate>{pub}</pubDate>",
            "    </item>",
        ])

    out += ["  </channel>", "</rss>"]
    return "\n".join(out) + "\n"

if __name__ == "__main__":
    items = collect()
    if not items:
        raise SystemExit("No Metagame articles were found; refusing to overwrite feed.xml.")
    OUTPUT.write_text(rss(items), encoding="utf-8")
    print(f"Wrote {len(items)} items to {OUTPUT}")
