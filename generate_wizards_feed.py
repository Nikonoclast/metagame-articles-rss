import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://magic.wizards.com"
ARCHIVE = f"{BASE}/en/news"
OUTPUT = Path("wizards-mtg.xml")

MAX_PAGES = 10
MAX_ITEMS = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; WizardsMTGRSS/1.0)"
}

session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def parse_date(text):
    patterns = [
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2},\s+\d{4}\b",

        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2}\b",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if not match:
            continue

        value = match.group()

        for fmt in ("%b %d, %Y", "%b %d"):
            try:
                date = datetime.strptime(value, fmt)

                if fmt == "%b %d":
                    date = date.replace(year=datetime.now().year)

                return date.replace(tzinfo=timezone.utc)

            except ValueError:
                pass

    return None


def fetch(url):
    response = session.get(url, timeout=20)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_articles(soup):
    articles = {}

    for link in soup.select('a[href*="/en/news/"]'):
        href = urljoin(BASE, link.get("href", ""))
        title = clean(link.get_text(" ", strip=True))

        if not title:
            continue

        # Exclude the main news page itself.
        if href.rstrip("/") == ARCHIVE:
            continue

        if not href.startswith(f"{ARCHIVE}/"):
            continue

        # Find a nearby card containing the date.
        parent = link.parent
        card_text = ""

        for _ in range(5):
            if parent is None:
                break

            text = clean(parent.get_text(" ", strip=True))

            if parse_date(text):
                card_text = text
                break

            parent = parent.parent

        published = parse_date(card_text)

        if published is None:
            continue

        articles[href] = {
            "title": title,
            "link": href,
            "published": published,
        }

    return list(articles.values())


def collect_articles():
    articles = {}

    # First grab the current DailyMTG page.
    for page_number in range(1, MAX_PAGES + 1):

        if page_number == 1:
            url = ARCHIVE
        else:
            # Wizards' archive supports page-based navigation.
            url = (
                f"{BASE}/en/news/archive"
                f"?search=&page={page_number}"
                f"&category=all&order=newest"
            )

        try:
            soup = fetch(url)
        except requests.RequestException as error:
            print(f"Could not fetch page {page_number}: {error}")
            break

        found = extract_articles(soup)

        print(f"Page {page_number}: found {len(found)} articles")

        if not found:
            break

        for article in found:
            articles[article["link"]] = article

    result = list(articles.values())

    result.sort(
        key=lambda article: (
            article["published"],
            article["title"],
        ),
        reverse=True,
    )

    return result[:MAX_ITEMS]


def create_rss(articles):
    now = datetime.now(timezone.utc)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        "    <title>Magic: The Gathering — DailyMTG</title>",
        f"    <link>{html.escape(ARCHIVE)}</link>",
        "    <description>Latest Magic: The Gathering news and articles from Wizards of the Coast.</description>",
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
            "No Wizards articles found. Feed was not changed."
        )

    OUTPUT.write_text(
        create_rss(articles),
        encoding="utf-8",
    )

    print(
        f"Successfully created Wizards RSS feed "
        f"with {len(articles)} articles."
    )


if __name__ == "__main__":
    main()
