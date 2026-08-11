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
JINA_PREFIX = "https://r.jina.ai/"
OUTPUT = Path("feed.xml")

MAX_PAGES = 20
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


def parse_date(text):
    match = re.search(
        r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
        r"\s+\d{1,2},\s+\d{4}\b",
        text or "",
    )

    if not match:
        return None

    try:
        return datetime.strptime(
            match.group(),
            "%b %d, %Y",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def direct_page(url):
    response = session.get(url, timeout=30)

    if response.status_code == 403:
        print(f"Metagame returned 403 for {url}")
        return None, True

    response.raise_for_status()

    return BeautifulSoup(response.text, "html.parser"), False


def jina_page(url):
    jina_url = JINA_PREFIX + url

    print(f"Using Jina Reader for {url}")

    response = session.get(
        jina_url,
        timeout=45,
        headers={
            "User-Agent": "MetagameRSS/1.0"
        },
    )

    response.raise_for_status()

    return response.text


def extract_html_articles(soup):
    articles = {}

    for link in soup.select('a[href*="/en-us/mtg/articles/"]'):
        href = urljoin(BASE, link.get("href", ""))
        title = clean(link.get_text(" ", strip=True))

        if not title:
            continue

        if href.rstrip("/") == ARCHIVE:
            continue

        if not href.startswith(f"{ARCHIVE}/"):
            continue

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


def extract_jina_articles(markdown):
    articles = {}

    # Jina returns Markdown links such as:
    #
    # [Article Title](https://metagame.info/en-us/mtg/articles/...)
    #
    link_pattern = re.compile(
        r"\[([^\]]+)\]\((https://metagame\.info/en-us/mtg/articles/[^\s\)]+)\)"
    )

    matches = list(link_pattern.finditer(markdown))

    for match in matches:
        title = clean(match.group(1))
        href = match.group(2)

        if not title:
            continue

        # Look around the link for the date.
        start = max(0, match.start() - 500)
        end = min(len(markdown), match.end() + 500)

        surrounding = markdown[start:end]
        published = parse_date(surrounding)

        if published is None:
            continue

        articles[href] = {
            "title": title,
            "link": href,
            "published": published,
        }

    return list(articles.values())


def get_archive_page(page_number):
    if page_number == 1:
        url = ARCHIVE
    else:
        url = f"{ARCHIVE}?page={page_number}"

    # Try Metagame directly first.
    try:
        result, blocked = direct_page(url)

        if not blocked:
            return extract_html_articles(result)

    except requests.RequestException as error:
        print(f"Direct request failed for page {page_number}: {error}")

    # If direct access is blocked, use Jina Reader.
    try:
        markdown = jina_page(url)
        return extract_jina_articles(markdown)

    except requests.RequestException as error:
        print(f"Jina Reader failed for page {page_number}: {error}")
        return []


def collect_articles():
    articles = {}

    for page in range(1, MAX_PAGES + 1):
        found = get_archive_page(page)

        print(
            f"Page {page}: found {len(found)} articles"
        )

        if not found:
            # Stop when an archive page contains no articles.
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
        "    <title>Metagame.info - Magic: The Gathering Articles</title>",
        f"    <link>{html.escape(ARCHIVE)}</link>",
        "    <description>",
        "Latest Magic: The Gathering articles from Metagame.info.",
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
            "No articles found. feed.xml was not changed."
        )

    OUTPUT.write_text(
        create_rss(articles),
        encoding="utf-8",
    )

    print(
        f"Successfully created RSS feed "
        f"with {len(articles)} articles."
    )


if __name__ == "__main__":
    main()
