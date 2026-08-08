import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://metagame.info"
ARCHIVE = f"{BASE}/en-us/mtg/articles"
OUTPUT = Path("feed.xml")
MAX_PAGES = 20
MAX_ITEMS = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MetagameRSS/1.0)"
}

session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_date(text):
    match = re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2},\s+\d{4}\b",
        text,
    )

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(), "%b %d, %Y"
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def get_page(page_number):
    if page_number == 1:
        url = ARCHIVE
    else:
        url = f"{ARCHIVE}?page={page_number}"

    response = session.get(url, timeout=20)
    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser")


def extract_articles(soup):
    articles = []

    for link in soup.select('a[href*="/en-us/mtg/articles/"]'):
        href = urljoin(BASE, link.get("href", ""))
        title = clean(link.get_text(" ", strip=True))

        if not title:
            continue

        if href.rstrip("/") == ARCHIVE:
            continue

        if not href.startswith(f"{ARCHIVE}/"):
            continue

        # The article card contains the publication date.
        parent = link.parent

        # Look at a few levels of parents because the exact card
        # structure can change slightly.
        for _ in range(4):
            if parent is None:
                break

            text = clean(parent.get_text(" ", strip=True))

            if parse_date(text):
                break

            parent = parent.parent

        published = parse_date(text) if parent else None

        if published is None:
            continue

        articles.append({
            "title": title,
            "link": href,
            "published": published,
        })

    return articles


def collect_articles():
    found = {}

    for page in range(1, MAX_PAGES + 1):
        try:
            soup = get_page(page)
        except requests.RequestException as error:
            print(f"Could not fetch page {page}: {error}")
            break

        articles = extract_articles(soup)

        print(f"Page {page}: found {len(articles)} articles")

        if not articles:
            break

        for article in articles:
            found[article["link"]] = article

    articles = list(found.values())

    articles.sort(
        key=lambda item: (
            item["published"],
            item["title"],
        ),
        reverse=True,
    )

    return articles[:MAX_ITEMS]


def create_rss(articles):
    now = datetime.now(timezone.utc)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        "    <title>Metagame.info - Magic: The Gathering Articles</title>",
        f"    <link>{html.escape(ARCHIVE)}</link>",
        "    <description>Latest Magic: The Gathering articles from Metagame.info.</description>",
        "    <language>en-us</language>",
        f"    <lastBuildDate>{format_datetime(now, usegmt=True)}</lastBuildDate>",
    ]

    for article in articles:
        title = html.escape(article["title"])
        link = html.escape(article["link"])
        pub_date = format_datetime(
            article["published"],
            usegmt=True,
        )

        lines.extend([
            "    <item>",
            f"      <title>{title}</title>",
            f"      <link>{link}</link>",
            f"      <guid isPermaLink=\"true\">{link}</guid>",
            f"      <pubDate>{pub_date}</pubDate>",
            "    </item>",
        ])

    lines.extend([
        "  </channel>",
        "</rss>",
    ])

    return "\n".join(lines) + "\n"


def main():
    articles = collect_articles()

    if not articles:
        raise RuntimeError(
            "No articles found. feed.xml was not changed."
        )

    OUTPUT.write_text(
        create_rss(articles),
        encoding="utf-8",
    )

    print(f"Successfully created RSS feed with {len(articles)} articles.")


if __name__ == "__main__":
    main()
