# Barstool Sports

A Jarvis voice command that pulls the latest Barstool Sports headlines, with
optional filtering by sport.

> **News only.** Barstool doesn't expose a public scores API. For live scores,
> schedules, and final results use the bundled `get_sports` command (ESPN data).
> This package focuses on what's getting written about over at Barstool.

## What it does

- Parses Barstool's monthly article sitemap (`/sitemap/YYYY-MM.xml`) — public,
  no API key, refreshes within seconds of each new post.
- Returns the freshest N entries with title, URL, kind (`blog` / `video`), and
  publish timestamp.
- Optional category filter: `nfl`, `nba`, `mlb`, `nhl`, `college`, `golf`,
  `mma`, `soccer`, `gambling`, `viral`, or `all`.

## Voice examples

| You say | What Jarvis does |
|---|---|
| "What's on Barstool?" | Top 5 newest posts, any sport |
| "Any Barstool NFL news?" | Filter to NFL posts |
| "Top 3 Barstool stories" | Newest 3, any sport |
| "What's Barstool saying about the NBA?" | Filter to NBA posts |

## Parameters

| Name | Type | Default | Description |
|---|---|---|---|
| `category` | string (enum) | `all` | Sport filter (see list above) |
| `count` | int | `5` | How many headlines to return (1–25) |

## Why a sitemap instead of RSS?

Barstool used to publish an RSS feed but no longer does. The sitemap is updated
on every post and contains exactly the fields we need (URL + last-modified
timestamp). Category tagging is recovered by keyword-matching the URL slug
against team / sport keyword lists — there's no per-post category metadata in
the sitemap itself.

## Install

```bash
jdt deploy local .                        # local Pi node
jdt deploy docker jarvis-node-kitchen .   # docker container
jdt deploy ssh pi@<dev-node>.local .      # Pi over SSH
```

## Test

```bash
jdt test .          # full package validation
jdt validate .      # fast manifest-only
```

## License

MIT
