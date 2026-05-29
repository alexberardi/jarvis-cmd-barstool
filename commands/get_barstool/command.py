"""GetBarstoolCommand — fetch the latest Barstool Sports headlines.

Barstool doesn't publish an RSS feed or a public news API. They do publish a
monthly XML sitemap that's updated within seconds of each new post going live,
so we use that as the source of truth for "what's new on Barstool".

Each sitemap entry is a `<loc>` URL of the form:
    https://www.barstoolsports.com/{kind}/{post_id}/{slug}
where `kind` is `blog`, `video`, etc., and `slug` is the human-readable title
hyphen-separated. The `<lastmod>` element is the publish/update timestamp.

We parse out the freshest N entries, turn the slug back into a title, and
optionally filter by sport (NFL, NBA, MLB, NHL, etc.) using keyword matching
against the slug. No HTML scraping required.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

try:
    from jarvis_log_client import JarvisLogger
except ImportError:
    import logging

    class JarvisLogger:  # noqa: E303
        def __init__(self, **kw: str) -> None:
            self._log = logging.getLogger(kw.get("service", __name__))
        def info(self, msg: str, **kw: object) -> None: self._log.info(msg)
        def warning(self, msg: str, **kw: object) -> None: self._log.warning(msg)
        def error(self, msg: str, **kw: object) -> None: self._log.error(msg)
        def debug(self, msg: str, **kw: object) -> None: self._log.debug(msg)


from jarvis_command_sdk import (
    CommandExample,
    CommandResponse,
    IJarvisCommand,
    IJarvisParameter,
    IJarvisSecret,
    JarvisPackage,
    JarvisParameter,
    RequestInformation,
)

logger = JarvisLogger(service="cmd.get_barstool")

SITEMAP_BASE = "https://www.barstoolsports.com/sitemap"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Slug keywords used to bucket posts into sport categories. The slug is the
# article title lowercased with non-alphanumeric chars replaced by dashes, so
# substring matching is reliable when we look for whole words wrapped in `-`.
_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "nfl": [
        "nfl", "quarterback", "qb", "super-bowl", "patriots", "giants",
        "eagles", "cowboys", "jets", "bills", "ravens", "chiefs", "49ers",
        "packers", "lions", "vikings", "bears", "steelers", "browns",
        "dolphins", "saints", "buccaneers", "rams", "chargers", "raiders",
        "commanders", "broncos", "colts", "jaguars", "titans", "panthers",
        "falcons", "seahawks", "cardinals", "texans", "bengals",
    ],
    "nba": [
        "nba", "knicks", "celtics", "lakers", "warriors", "heat", "nets",
        "76ers", "sixers", "bulls", "cavaliers", "cavs", "pistons", "pacers",
        "bucks", "hawks", "hornets", "magic", "wizards", "clippers", "suns",
        "kings", "nuggets", "timberwolves", "thunder", "blazers", "jazz",
        "mavericks", "mavs", "rockets", "grizzlies", "pelicans", "spurs",
        "jokic", "lebron", "curry", "doncic", "luka",
    ],
    "mlb": [
        "mlb", "yankees", "red-sox", "mets", "dodgers", "astros", "phillies",
        "braves", "orioles", "blue-jays", "rays", "white-sox", "guardians",
        "tigers", "royals", "twins", "angels", "athletics", "mariners",
        "rangers", "marlins", "nationals", "cubs", "reds", "brewers",
        "pirates", "cardinals", "diamondbacks", "rockies", "padres",
        "giants", "grand-slam", "no-hitter", "home-run",
    ],
    "nhl": [
        "nhl", "bruins", "rangers", "islanders", "devils", "flyers",
        "penguins", "capitals", "hurricanes", "panthers", "lightning",
        "maple-leafs", "canadiens", "senators", "sabres", "red-wings",
        "blackhawks", "blues", "predators", "stars", "wild", "jets",
        "avalanche", "ducks", "kings", "sharks", "kraken", "canucks",
        "flames", "oilers", "golden-knights", "blue-jackets",
        "stanley-cup", "mcdavid", "matthews",
    ],
    "college": [
        "college-football", "college-basketball", "ncaa", "march-madness",
        "buckeyes", "wolverines", "crimson-tide", "tigers", "longhorns",
        "sooners", "fighting-illini", "boilermakers", "blue-devils",
        "tar-heels", "jayhawks", "wildcats", "cornhuskers", "badgers",
    ],
    "golf": [
        "golf", "pga", "liv-golf", "masters", "us-open", "british-open",
        "ryder-cup", "tiger-woods", "rory", "scheffler", "the-open",
    ],
    "mma": [
        "ufc", "mma", "octagon", "fight-night", "title-fight",
    ],
    "soccer": [
        "soccer", "premier-league", "champions-league", "world-cup",
        "messi", "ronaldo", "uefa", "epl",
    ],
    "gambling": [
        "parlay", "odds", "spread", "moneyline", "bet", "sportsbook",
        "props", "picks", "gambling",
    ],
    "viral": [
        "viral", "tiktok", "instagram", "twitter",
    ],
}

_CATEGORIES = ["all"] + list(_CATEGORY_KEYWORDS.keys())

# Article-kind URL segments we want to surface as "news". Skip podcast pages,
# layout pages, etc. (the sitemap is mostly blog + video.)
_NEWS_KINDS = {"blog", "video"}

# Words that look like noise in a converted slug. The slug substitutes "$" with
# "dollar" inside dollar amounts ("$10000000" → "dollar10000000"); the original
# article title shows the dollar sign. Keep the conversion simple and leave it
# as-is — the LLM will turn it into spoken language.
_DOLLAR_RE = re.compile(r"\bdollar(\d)")


def _slug_to_title(slug: str) -> str:
    """Best-effort conversion of a Barstool URL slug into a human title."""
    if not slug:
        return ""
    text = slug.replace("-", " ").strip()
    # Re-insert "$" before bare digits that used to be dollar amounts.
    text = _DOLLAR_RE.sub(r"$\1", text)
    # Sentence-case (Barstool titles are mostly sentence-case in the slug).
    if text:
        text = text[0].upper() + text[1:]
    return text


def _categorize(slug: str) -> List[str]:
    """Return all matching category keys for a slug."""
    s = f"-{slug}-"
    matches: List[str] = []
    for cat, words in _CATEGORY_KEYWORDS.items():
        for w in words:
            if f"-{w}-" in s:
                matches.append(cat)
                break
    return matches


class GetBarstoolCommand(IJarvisCommand):

    @property
    def command_name(self) -> str:
        return "get_barstool"

    @property
    def description(self) -> str:
        return (
            "Get the latest Barstool Sports headlines. Supports filtering by "
            "sport: nfl, nba, mlb, nhl, college, golf, mma, soccer, gambling, "
            "or viral. Pulls directly from Barstool's article sitemap; no API "
            "key required."
        )

    @property
    def keywords(self) -> List[str]:
        return [
            "barstool", "barstool sports", "stool",
            "pardon my take", "pmt",
            "barstool news", "barstool headlines",
        ]

    @property
    def parameters(self) -> List[IJarvisParameter]:
        return [
            JarvisParameter(
                "category",
                "string",
                required=False,
                description=(
                    "Sport category filter. Use 'all' or omit for everything."
                ),
                enum_values=_CATEGORIES,
            ),
            JarvisParameter(
                "count",
                "int",
                required=False,
                description="Number of headlines to return (default 5, max 25).",
            ),
        ]

    @property
    def required_secrets(self) -> List[IJarvisSecret]:
        return []

    @property
    def required_packages(self) -> List[JarvisPackage]:
        return [JarvisPackage("httpx")]

    def generate_prompt_examples(self) -> List[CommandExample]:
        return [
            CommandExample(
                voice_command="What's on Barstool?",
                expected_parameters={},
                is_primary=True,
            ),
            CommandExample(
                voice_command="Give me the latest Barstool headlines",
                expected_parameters={"count": 5},
            ),
            CommandExample(
                voice_command="Any Barstool NFL news?",
                expected_parameters={"category": "nfl"},
            ),
            CommandExample(
                voice_command="What's Barstool saying about the NBA?",
                expected_parameters={"category": "nba"},
            ),
            CommandExample(
                voice_command="Top 3 Barstool stories",
                expected_parameters={"count": 3},
            ),
        ]

    def generate_adapter_examples(self) -> List[CommandExample]:
        examples: List[CommandExample] = [
            CommandExample(voice_command="What's on Barstool?", expected_parameters={}, is_primary=True),
            CommandExample(voice_command="What's Barstool saying today?", expected_parameters={}),
            CommandExample(voice_command="Give me Barstool headlines", expected_parameters={}),
            CommandExample(voice_command="Latest from Barstool Sports", expected_parameters={}),
            CommandExample(voice_command="Anything new on Barstool?", expected_parameters={}),
            CommandExample(voice_command="Read me Barstool", expected_parameters={}),
            CommandExample(voice_command="Top 3 Barstool stories", expected_parameters={"count": 3}),
            CommandExample(voice_command="Top 10 Barstool headlines", expected_parameters={"count": 10}),
            CommandExample(voice_command="Give me one Barstool headline", expected_parameters={"count": 1}),
        ]
        for cat in ("nfl", "nba", "mlb", "nhl", "college", "golf", "mma", "soccer", "gambling"):
            examples.append(CommandExample(
                voice_command=f"Any Barstool {cat.upper() if len(cat) <= 4 else cat} news?",
                expected_parameters={"category": cat},
            ))
            examples.append(CommandExample(
                voice_command=f"What's Barstool saying about {cat}?",
                expected_parameters={"category": cat},
            ))
        return examples

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        request_info: RequestInformation,
        **kwargs: Any,
    ) -> CommandResponse:
        category_raw = kwargs.get("category") or "all"
        category = category_raw.lower().strip()
        if category not in _CATEGORIES:
            category = "all"

        try:
            count = int(kwargs.get("count") or 5)
        except (TypeError, ValueError):
            count = 5
        count = max(1, min(count, 25))

        try:
            entries = self._fetch_latest_entries()
        except Exception as exc:
            logger.error("Barstool sitemap fetch failed", error=str(exc))
            return CommandResponse.error_response(
                error_details=f"Could not reach Barstool: {exc}",
            )

        if not entries:
            return CommandResponse.error_response(
                error_details="Barstool sitemap returned no entries.",
            )

        if category != "all":
            filtered = [e for e in entries if category in e["categories"]]
            if not filtered:
                return CommandResponse.success_response(
                    context_data={
                        "category": category,
                        "count": 0,
                        "message": (
                            f"No recent Barstool stories tagged {category}. "
                            "Try a different sport or omit the category."
                        ),
                        "articles": [],
                    },
                    wait_for_input=False,
                )
            entries = filtered

        articles = entries[:count]

        # Strip internal `categories` list from response — keep the wire data
        # tight and let the LLM compose the spoken summary.
        slim_articles = [
            {
                "title": a["title"],
                "url": a["url"],
                "published": a["published"],
                "kind": a["kind"],
            }
            for a in articles
        ]

        return CommandResponse.success_response(
            context_data={
                "category": category,
                "count": len(slim_articles),
                "source": "Barstool Sports",
                "articles": slim_articles,
            },
            wait_for_input=False,
        )

    # ------------------------------------------------------------------
    # Sitemap fetching
    # ------------------------------------------------------------------

    def _fetch_latest_entries(self) -> List[Dict[str, Any]]:
        """Return all news-kind entries from the current month's sitemap,
        sorted newest first. Falls back to previous month if the current one
        is empty (e.g., on the 1st of the month before any posts go up).
        """
        now = datetime.now(timezone.utc)

        candidates = [now]
        # Try previous month too — covers month rollover and weekend dry spells.
        if now.month == 1:
            candidates.append(now.replace(year=now.year - 1, month=12))
        else:
            candidates.append(now.replace(month=now.month - 1))

        all_entries: List[Dict[str, Any]] = []
        for ts in candidates:
            url = f"{SITEMAP_BASE}/{ts.year:04d}-{ts.month:02d}.xml"
            try:
                entries = self._parse_sitemap(url)
            except Exception as exc:
                logger.warning("Sitemap parse failed", url=url, error=str(exc))
                continue
            all_entries.extend(entries)
            # Once we have ~30 entries from the current month, that's plenty.
            if len(all_entries) >= 30:
                break

        all_entries.sort(key=lambda e: e["_sort_ts"], reverse=True)
        for e in all_entries:
            e.pop("_sort_ts", None)
        return all_entries

    def _parse_sitemap(self, url: str) -> List[Dict[str, Any]]:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": "jarvis-cmd-barstool/1.0"})
            resp.raise_for_status()
            body = resp.text

        root = ET.fromstring(body)
        entries: List[Dict[str, Any]] = []
        for url_el in root.findall("sm:url", SITEMAP_NS):
            loc_el = url_el.find("sm:loc", SITEMAP_NS)
            lastmod_el = url_el.find("sm:lastmod", SITEMAP_NS)
            if loc_el is None or not loc_el.text:
                continue

            href = loc_el.text.strip()
            kind, post_id, slug = self._split_barstool_url(href)
            if kind not in _NEWS_KINDS:
                continue

            lastmod = (lastmod_el.text or "").strip() if lastmod_el is not None else ""
            sort_ts = self._lastmod_to_epoch(lastmod)

            entries.append({
                "title": _slug_to_title(slug),
                "url": href,
                "published": lastmod,
                "kind": kind,
                "post_id": post_id,
                "categories": _categorize(slug),
                "_sort_ts": sort_ts,
            })
        return entries

    @staticmethod
    def _split_barstool_url(url: str) -> tuple[str, str, str]:
        """Pull (kind, post_id, slug) out of a Barstool article URL."""
        # Strip protocol + host.
        path = url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
        parts = [p for p in path.split("/") if p]
        # Expect: ['blog', '3570445', 'shoutout-lego-batman...']
        if len(parts) >= 3:
            return parts[0], parts[1], parts[2]
        if len(parts) == 2:
            return parts[0], "", parts[1]
        return ("", "", parts[0] if parts else "")

    @staticmethod
    def _lastmod_to_epoch(value: str) -> float:
        if not value:
            return 0.0
        try:
            # Sitemap timestamps look like "2026-05-28T17:45:00.000Z".
            normalized = value.replace("Z", "+00:00")
            return datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            return 0.0
