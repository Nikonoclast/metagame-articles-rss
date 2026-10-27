"""Shared helpers for the three feed generators.

Everything the generators have in common lives here: downloading pages
(with automatic retries), remembering past articles between runs, and
writing the RSS file.
"""

import html
import json
import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Where the finished feeds are published (used for the "self" link in each feed).
SITE_BASE = "https://nikonoclast.github.io/metagame-articles-rss"

_BAD_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean(text):
    """Collapse whitespace and strip characters that are illegal in XML."""
    text = _BAD_XML_CHARS.sub("", text or "")
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------- downloading

def make_session(user_agent):
    """A requests session that retries temporary failures automatically."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    retry = Retry(
        total=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def fetch_text(session, url, timeout=30):
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


# ------------------------------------------------------------------- dates

def to_iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def from_iso(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ----------------------------------------------------------------- history

def load_history(path):
    """Read the saved article list. Returns {link: article}."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"Could not read {path}: {error}")
        return {}
    history = {}
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("link") and item.get("published"):
                history[item["link"]] = item
    return history


def save_history(path, items):
    Path(path).write_text(
        json.dumps(items, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def merge_items(history, new_items, max_items):
    """Combine saved articles with freshly found ones.

    The date an article was first saved with is always kept, so an article
    never "moves" in readers because of a later re-scrape.
    """
    merged = {}
    # Brand-new articles go first so same-day ties keep the website's order.
    for item in new_items:
        link = item["link"]
        if link not in history and link not in merged:
            merged[link] = dict(item)
    for link, item in history.items():
        merged[link] = dict(item)
    # Fill in details (author, description...) that an older copy was missing.
    for item in new_items:
        old = merged[item["link"]]
        for key, value in item.items():
            if key != "published" and value and not old.get(key):
                old[key] = value

    items = list(merged.values())
    items.sort(key=lambda entry: entry["published"], reverse=True)  # stable sort
    return items[:max_items]


# --------------------------------------------------------------------- RSS

def _esc(value):
    return html.escape(str(value), quote=True)


def build_rss(*, title, link, description, feed_url, items):
    # Use the newest article's date (not "now") so the file only changes
    # when something genuinely new appears.
    if items:
        build_date = from_iso(items[0]["published"])
    else:
        build_date = datetime.now(timezone.utc)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "  <channel>",
        f"    <title>{_esc(title)}</title>",
        f"    <link>{_esc(link)}</link>",
        f"    <description>{_esc(description)}</description>",
        "    <language>en-us</language>",
        f'    <atom:link href="{_esc(feed_url)}" rel="self" type="application/rss+xml"/>',
        f"    <lastBuildDate>{format_datetime(build_date, usegmt=True)}</lastBuildDate>",
    ]

    for item in items:
        published = from_iso(item["published"])
        lines.append("    <item>")
        lines.append(f"      <title>{_esc(item['title'])}</title>")
        lines.append(f"      <link>{_esc(item['link'])}</link>")
        lines.append(f'      <guid isPermaLink="true">{_esc(item["link"])}</guid>')
        lines.append(f"      <pubDate>{format_datetime(published, usegmt=True)}</pubDate>")
        if item.get("author"):
            lines.append(f"      <dc:creator>{_esc(item['author'])}</dc:creator>")
        if item.get("category"):
            lines.append(f"      <category>{_esc(item['category'])}</category>")
        if item.get("description"):
            lines.append(f"      <description>{_esc(item['description'])}</description>")
        lines.append("    </item>")

    lines += ["  </channel>", "</rss>"]
    return "\n".join(lines) + "\n"


def write_text(path, text):
    Path(path).write_text(text, encoding="utf-8")
