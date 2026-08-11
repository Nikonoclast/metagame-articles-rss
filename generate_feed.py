import html
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote

import requests

OUTPUT = Path("feed.xml")
HISTORY = Path("metagame-history.json")

GOOGLE_NEWS_URL = (
    "https://news.google.com/rss/search"
    "?q=" + quote("site:metagame.info/en-us/mtg/articles")
    + "&hl=en-US&gl=US&ceid=US:en"
)

MAX_ITEMS = 100

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MetagameRSS/1.0)"
}


def clean(text):
    return " ".join((text or "").split()).strip()


def parse_date(value):
    if not value:
        return datetime.now(timezone.utc)

    try:
        date = parsedate_to_datetime(value)

        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)

        return date.astimezone(timezone.utc)

    except (TypeError, ValueError):
        return datetime.now(timezone.utc)


def load_history():
    if not HISTORY.exists():
        return []

    try:
        data = json.loads(
            HISTORY.read_text(encoding="utf-8")
        )

        if isinstance(data, list):
            return data

    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not read history: {error}")

    return []


def save_history(articles):
    HISTORY.write_text(
        json.dumps(
            articles,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def fetch_google_news():
    print("Fetching Google News RSS...")

    response = requests.get(
        GOOGLE_NEWS_URL,
        headers=HEADERS,
        timeout=30,
    )

    response.raise_for_status()

    return response.content


def extract_articles(xml_data):
    root = ET.fromstring(xml_data)

    articles = []

    for item in root.findall(".//item"):
        title = clean(
            item.findtext("title")
        )

        link = clean(
            item.findtext("link")
        )

        pub_date = item.findtext("pubDate")

        if not title or not link:
            continue

        articles.append({
            "title": title,
            "link": link,
            "published": format_datetime(
                parse_date(pub_date),
                usegmt=True,
            ),
        })

    return articles


def merge_articles(history, new_articles):
    combined = {}

    for article in history:
        link = article.get("link")

        if link:
            combined[link] = article

    for article in new_articles:
        link = article.get("link")

        if link:
            combined[link] = article

    articles = list(combined.values())

    def sort_key(article):
        try:
            return parsedate_to_datetime(
                article.get("published", "")
            )
        except (TypeError, ValueError):
            return datetime.min.replace(
                tzinfo=timezone.utc
            )

    articles.sort(
        key=sort_key,
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
        "    <link>https://metagame.info/en-us/mtg/articles</link>",
        "    <description>",
        "Latest Magic: The Gathering articles from Metagame.info.",
        "</description>",
        "    <language>en-us</language>",
        f"    <lastBuildDate>{format_datetime(now, usegmt=True)}</lastBuildDate>",
    ]

    for article in articles:
        title = html.escape(article["title"])
        link = html.escape(article["link"])
        pub_date = html.escape(article["published"])

        lines.extend([
            "    <item>",
            f"      <title>{title}</title>",
            f"      <link>{link}</link>",
            f"      <guid isPermaLink=\"false\">{link}</guid>",
            f"      <pubDate>{pub_date}</pubDate>",
            "    </item>",
        ])

    lines.extend([
        "  </channel>",
        "</rss>",
    ])

    return "\n".join(lines) + "\n"


def main():
    history = load_history()

    print(
        f"Existing Metagame history: "
        f"{len(history)} articles"
    )

    xml_data = fetch_google_news()

    new_articles = extract_articles(xml_data)

    print(
        f"Google News returned "
        f"{len(new_articles)} Metagame articles."
    )

    if not new_articles and not history:
        raise RuntimeError(
            "No Metagame articles found and no existing history."
        )

    combined = merge_articles(
        history,
        new_articles,
    )

    save_history(combined)

    OUTPUT.write_text(
        create_rss(combined),
        encoding="utf-8",
    )

    print(
        f"Metagame history now contains "
        f"{len(combined)} articles."
    )


if __name__ == "__main__":
    main()
