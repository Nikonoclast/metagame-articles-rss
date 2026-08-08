# Metagame.info RSS feed

A self-updating RSS 2.0 feed for the English Magic: The Gathering article
archive at https://metagame.info/en-us/mtg/articles.

The GitHub Action runs once per hour, crawls the paginated article archive,
and publishes `feed.xml` through GitHub Pages.

## One-time setup

1. Create a new GitHub repository, for example `metagame-rss`.
2. Upload all files from this folder to the repository.
3. In GitHub, open **Settings → Pages**.
4. Under **Build and deployment**, set **Source** to **GitHub Actions**.
5. Open **Actions** and run **Update Metagame RSS feed** once with
   **Run workflow**.
6. Your feed will be available at:

   `https://YOUR-USERNAME.github.io/YOUR-REPOSITORY/feed.xml`

The scheduled workflow then refreshes it hourly.

## What it includes

- English-language articles from all archive pages.
- Article title and canonical URL.
- Publication date when available from the archive.
- Up to 100 newest articles in the feed.

The script deliberately publishes links/snippets rather than copying article
bodies into the RSS feed.
