import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from datetime import datetime, timezone
from email.utils import format_datetime
import re
import html

BASE_URL = "https://edhrec.com"
ARCHIVE_URL = "https://edhrec.com/articles"
FEED_URL = "https://nikonoclast.github.io/metagame-articles-rss/edhrec.xml"

MAX_PAGES = 10
MAX_ITEMS = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/128.0 Safari/537.36"
    )
}

DATE_PATTERN = re.compile(
    r"\b("
    r"January|February|March|April|May|June|July|August|September|October|November|December"
    r")\s+\d{1,2},\s+\d{4}\b"
)


def get_soup(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def extract_date(element):
    """
    Look at the article card and nearby parent elements for a date.
    """
    current = element

    for _ in range(7):
        if current is None:
            break

        text = current.get_text(" ", strip=True)
        match = DATE_PATTERN.search(text)

        if match:
            try:
                return datetime.strptime(
                    match.group(0),
                    "%B %d, %Y"
                ).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        current = current.parent

    return None


def extract_articles():
    articles = []
    seen = set()

    for page in range(1, MAX_PAGES + 1):
        if page == 1:
            url = ARCHIVE_URL
        else:
            url = f"{ARCHIVE_URL}/page/{page}"

        print(f"Fetching EDHREC article page {page}: {url}")

        soup = get_soup(url)

        for link in soup.find_all("a", href=True):
            href = urljoin(BASE_URL, link["href"])
            parsed = urlparse(href)

            # Only actual article URLs:
            # /articles/article-slug
            if parsed.netloc != "edhrec.com":
                continue

            path = parsed.path.rstrip("/")

            if not path.startswith("/articles/"):
                continue

            remainder = path[len("/articles/"):]

            # Exclude pagination, tags, authors, etc.
            if not remainder or "/" in remainder:
                continue

            excluded = {
                "for-writers",
                "authors",
                "tags",
                "tag",
                "author",
            }

            if remainder.lower() in excluded:
                continue

            if href in seen:
                continue

            title = link.get_text(" ", strip=True)

            if not title:
                continue

            # Avoid navigation links that aren't article titles.
            if len(title) < 5:
                continue

            pub_date = extract_date(link)

            # Only accept entries where we found a publication date.
            if pub_date is None:
                continue

            seen.add(href)

            articles.append({
                "title": title,
                "link": href,
                "pub_date": pub_date,
            })

            if len(articles) >= MAX_ITEMS:
                break

        if len(articles) >= MAX_ITEMS:
            break

    # Newest first
    articles.sort(
        key=lambda x: x["pub_date"],
        reverse=True
    )

    return articles[:MAX_ITEMS]


def xml_escape(value):
    return html.escape(str(value), quote=True)


def build_rss(articles):
    now = datetime.now(timezone.utc)

    items = []

    for article in articles:
        pub_date = format_datetime(article["pub_date"])

        items.append(
            f"""    <item>
      <title>{xml_escape(article["title"])}</title>
      <link>{xml_escape(article["link"])}</link>
      <guid isPermaLink="true">{xml_escape(article["link"])}</guid>
      <pubDate>{pub_date}</pubDate>
      <description>{xml_escape(article["title"])}</description>
    </item>"""
        )

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>EDHREC Articles</title>
    <link>{FEED_URL.rsplit("/", 1)[0]}</link>
    <description>Latest articles from EDHREC</description>
    <language>en-us</language>
    <lastBuildDate>{format_datetime(now)}</lastBuildDate>
{chr(10).join(items)}
  </channel>
</rss>
"""


def main():
    print("Fetching EDHREC articles...")

    articles = extract_articles()

    if not articles:
        raise RuntimeError(
            "No EDHREC articles were found. "
            "Refusing to create an empty feed."
        )

    print(f"Found {len(articles)} EDHREC articles.")

    rss = build_rss(articles)

    with open("edhrec.xml", "w", encoding="utf-8") as f:
        f.write(rss)

    print("Successfully created EDHREC RSS feed.")
    print("Output: edhrec.xml")


if __name__ == "__main__":
    main()
