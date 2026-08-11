import html
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, format_datetime
from pathlib import Path
from urllib.parse import quote

import requests

OUTPUT = Path("feed.xml")

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

        # Make sure this is actually a Metagame result.
        source = item.find("source")

        if source is not None:
            source_url = source.get("url", "")

            if source_url and "metagame.info" not in source_url:
                continue

        articles.append({
            "title": title,
            "link": link,
            "published": parse_date(pub_date),
        })

    return articles


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
        pub_date = format_datetime(
            article["published"],
            usegmt=True,
        )

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
    xml_data = fetch_google_news()

    articles = extract_articles(xml_data)

    print(
        f"Google News returned {len(articles)} Metagame articles."
    )

    if not articles:
        raise RuntimeError(
            "Google News returned no Metagame articles. "
            "feed.xml was not changed."
        )

    articles.sort(
        key=lambda article: article["published"],
        reverse=True,
    )

    articles = articles[:MAX_ITEMS]

    OUTPUT.write_text(
        create_rss(articles),
        encoding="utf-8",
    )

    print(
        f"Successfully created Metagame RSS feed "
        f"with {len(articles)} articles."
    )


if __name__ == "__main__":
    main()
