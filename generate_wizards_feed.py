import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.magic.wizards.com"
ARCHIVE = f"{BASE}/en/news/archive"
OUTPUT = Path("wizards-mtg.xml")

MAX_PAGES = 10
MAX_ITEMS = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/150.0 Safari/537.36"
    )
}

session = requests.Session()
session.headers.update(HEADERS)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def fetch(url):
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_article_links(soup):
    articles = {}

    for link in soup.find_all("a", href=True):
        href = urljoin(BASE, link["href"])

        if "/en/news/" not in href:
            continue

        # Ignore category/archive/navigation pages.
        if href.rstrip("/") in {
            ARCHIVE,
            f"{BASE}/en/news",
        }:
            continue

        title = clean(link.get_text(" ", strip=True))

        if not title:
            continue

        # Ignore category links.
        if href.rstrip("/").endswith((
            "/announcements",
            "/feature",
            "/making-magic",
            "/mtg-arena",
            "/card-image-gallery",
            "/podcasts",
        )):
            continue

        articles[href] = {
            "title": title,
            "link": href,
        }

    return list(articles.values())


def parse_article_date(soup):
    # First try structured metadata.
    meta_names = [
        ("property", "article:published_time"),
        ("name", "article:published_time"),
        ("property", "og:published_time"),
    ]

    for attribute, value in meta_names:
        tag = soup.find("meta", attrs={attribute: value})

        if tag and tag.get("content"):
            try:
                date = tag["content"].replace("Z", "+00:00")
                return datetime.fromisoformat(date).astimezone(timezone.utc)
            except ValueError:
                pass

    # Wizards currently displays dates in article metadata such as:
    # "Jul 13, 2026"
    text = clean(soup.get_text(" ", strip=True))

    match = re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2},\s+\d{4}\b",
        text,
    )

    if match:
        try:
            return datetime.strptime(
                match.group(),
                "%b %d, %Y",
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            pass

    return None


def collect_articles():
    articles = {}

    for page_number in range(1, MAX_PAGES + 1):
        url = (
            f"{ARCHIVE}"
            f"?author=all"
            f"&category=all"
            f"&order=newest"
            f"&page={page_number}"
            f"&search="
        )

        try:
            soup = fetch(url)
        except requests.RequestException as error:
            print(f"Could not fetch archive page {page_number}: {error}")
            break

        found = extract_article_links(soup)

        print(
            f"Archive page {page_number}: "
            f"found {len(found)} possible articles"
        )

        if not found:
            break

        for article in found:
            articles[article["link"]] = article

    # Fetch the article pages only after we have discovered their URLs.
    #
    # This is slower than scraping the archive alone, but it gives us
    # accurate publication dates and avoids inventing dates.
    dated_articles = []

    for number, article in enumerate(
        list(articles.values())[:MAX_ITEMS],
        start=1,
    ):
        try:
            soup = fetch(article["link"])
            published = parse_article_date(soup)
        except requests.RequestException as error:
            print(
                f"Could not fetch article {number}: "
                f"{article['link']} ({error})"
            )
            continue

        if published is None:
            print(
                f"No publication date found: "
                f"{article['link']}"
            )
            continue

        article["published"] = published
        dated_articles.append(article)

        print(
            f"{number}: {article['title']} "
            f"({published.date()})"
        )

    dated_articles.sort(
        key=lambda article: article["published"],
        reverse=True,
    )

    return dated_articles[:MAX_ITEMS]


def create_rss(articles):
    now = datetime.now(timezone.utc)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0">',
        "  <channel>",
        "    <title>Magic: The Gathering — DailyMTG</title>",
        f"    <link>{html.escape(ARCHIVE)}</link>",
        "    <description>"
        "Latest Magic: The Gathering articles and news "
        "from Wizards of the Coast."
        "</description>",
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
