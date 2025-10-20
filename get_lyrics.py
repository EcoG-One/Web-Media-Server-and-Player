# Most of this file is part of beets.
# Copyright 2016, Adrian Sampson.
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.


from __future__ import annotations
import atexit
import itertools
import math
import re
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from functools import cached_property, partial, total_ordering
from html import unescape
from http import HTTPStatus
from typing import TYPE_CHECKING, Iterable, Iterator, NamedTuple
from urllib.parse import quote, quote_plus, urlencode, urlparse
import requests
from bs4 import BeautifulSoup
from unidecode import unidecode
import plugins
from distance import string_dist

if TYPE_CHECKING:
    from tasks import ImportTask
    from models import Item
    from beets.logging import BeetsLogger as Logger
    from collections.abc import Collection, Sequence

    from _typing import (
        GeniusAPI,
        JSONDict,
        LRCLibAPI,
    )


def sanitize_choices(
    choices: Sequence[str], choices_all: Collection[str]
) -> list[str]:
    """Clean up a stringlist configuration attribute: keep only choices
    elements present in choices_all, remove duplicate elements, expand '*'
    wildcard while keeping original stringlist order.
    """
    seen: set[str] = set()
    others = [x for x in choices_all if x not in choices]
    res: list[str] = []
    for s in choices:
        if s not in seen:
            if s in list(choices_all):
                res.append(s)
            elif s == "*":
                res.extend(others)
        seen.add(s)
    return res


class NotFoundError(requests.exceptions.HTTPError):
    pass


class CaptchaError(requests.exceptions.HTTPError):
    pass


class TimeoutSession(requests.Session):
    def request(self, *args, **kwargs):
        """Wrap the request method to raise an exception on HTTP errors."""
        kwargs.setdefault("timeout", 10)
        r = super().request(*args, **kwargs)
        if r.status_code == HTTPStatus.NOT_FOUND:
            raise NotFoundError("HTTP Error: Not Found", response=r)
        if 300 <= r.status_code < 400:
            raise CaptchaError("Captcha is required", response=r)

        r.raise_for_status()

        return r

USER_AGENT = "ecoserver/0.5.5"
INSTRUMENTAL_LYRICS = "[Instrumental]"
r_session = TimeoutSession()
r_session.headers.update({"User-Agent": USER_AGENT})

@atexit.register
def close_session():
    """Close the requests session on shut down."""
    r_session.close()


# Utilities.

def search_pairs(item):
    """Yield a pairs of artists and titles to search for.

    The first item in the pair is the name of the artist, the second
    item is a list of song names.

    In addition to the artist and title obtained from the `item` the
    method tries to strip extra information like paranthesized suffixes
    and featured artists from the strings and add them as candidates.
    The artist sort name is added as a fallback candidate to help in
    cases where artist name includes special characters or is in a
    non-latin script.
    The method also tries to split multiple titles separated with `/`.
    """

    def generate_alternatives(string, patterns):
        """Generate string alternatives by extracting first matching group for
        each given pattern.
        """
        alternatives = [string]
        for pattern in patterns:
            match = re.search(pattern, string, re.IGNORECASE)
            if match:
                alternatives.append(match.group(1))
        return alternatives

    title, artist, artist_sort = (
        item.title.strip(),
        item.artist.strip(),
        item.artist_sort.strip(),
    )
    if not title or not artist:
        return ()

    patterns = [
        # Remove any featuring artists from the artists name
        rf"(.*?) {plugins.feat_tokens()}"
    ]

    # Skip various artists
    artists = []
    lower_artist = artist.lower()
    if "various" not in lower_artist:
        artists.extend(generate_alternatives(artist, patterns))
    # Use the artist_sort as fallback only if it differs from artist to avoid
    # repeated remote requests with the same search terms
    artist_sort_lower = artist_sort.lower()
    if (
        artist_sort
        and lower_artist != artist_sort_lower
        and "various" not in artist_sort_lower
    ):
        artists.append(artist_sort)

    patterns = [
        # Remove a parenthesized suffix from a title string. Common
        # examples include (live), (remix), and (acoustic).
        r"(.+?)\s+[(].*[)]$",
        # Remove any featuring artists from the title
        rf"(.*?) {plugins.feat_tokens(for_artist=False)}",
        # Remove part of title after colon ':' for songs with subtitles
        r"(.+?)\s*:.*",
    ]
    titles = generate_alternatives(title, patterns)

    # Check for a dual song (e.g. Pink Floyd - Speak to Me / Breathe)
    # and each of them.
    multi_titles = []
    for title in titles:
        multi_titles.append([title])
        if " / " in title:
            multi_titles.append([x.strip() for x in title.split(" / ")])

    return itertools.product(artists, multi_titles)


class RequestHandler:
    _log: Logger

    def debug(self, message: str, *args) -> None:
        """Log a debug message with the class name."""
        self._log.debug(f"{self.__class__.__name__}: {message}", *args)

    def info(self, message: str, *args) -> None:
        """Log an info message with the class name."""
        self._log.info(f"{self.__class__.__name__}: {message}", *args)

    def warn(self, message: str, *args) -> None:
        """Log warning with the class name."""
        self._log.warning(f"{self.__class__.__name__}: {message}", *args)

    @staticmethod
    def format_url(url: str, params: JSONDict | None) -> str:
        if not params:
            return url

        return f"{url}?{urlencode(params)}"

    def fetch_text(
        self, url: str, params: JSONDict | None = None, **kwargs
    ) -> str:
        """Return text / HTML data from the given URL.

        Set the encoding to None to let requests handle it because some sites
        set it incorrectly.
        """
        url = self.format_url(url, params)
        self.debug("Fetching HTML from {}", url)
        r = r_session.get(url, **kwargs)
        r.encoding = None
        return r.text

    def fetch_json(self, url: str, params: JSONDict | None = None, **kwargs):
        """Return JSON data from the given URL."""
        url = self.format_url(url, params)
        self.debug("Fetching JSON from {}", url)
        return r_session.get(url, **kwargs).json()

    def post_json(self, url: str, params: JSONDict | None = None, **kwargs):
        """Send POST request and return JSON response."""
        url = self.format_url(url, params)
        self.debug("Posting JSON to {}", url)
        return r_session.post(url, **kwargs).json()

    @contextmanager
    def handle_request(self) -> Iterator[None]:
        try:
            yield
        except requests.JSONDecodeError:
            self.warn("Could not decode response JSON data")
        except requests.RequestException as exc:
            self.warn("Request error: {}", exc)

class BackendClass(type):
    @property
    def name(cls) -> str:
        """Return lowercase name of the backend class."""
        return cls.__name__.lower()

class Backend(RequestHandler, metaclass=BackendClass):
    def __init__(self, config, log):
        self._log = log
        self.config = config

    def fetch(
        self, artist: str, title: str, album: str, length: int
    ) -> tuple[str, str] | None:
        raise NotImplementedError

@dataclass
@total_ordering
class LRCLyrics:
    #: Percentage tolerance for max duration difference between lyrics and item.
    DURATION_DIFF_TOLERANCE = 0.05

    target_duration: float
    id: int
    duration: float
    instrumental: bool
    plain: str
    synced: str | None

    def __le__(self, other: LRCLyrics) -> bool:
        """Compare two lyrics items by their score."""
        return self.dist < other.dist

    @classmethod
    def make(
        cls, candidate: LRCLibAPI.Item, target_duration: float
    ) -> LRCLyrics:
        return cls(
            target_duration,
            candidate["id"],
            candidate["duration"] or 0.0,
            candidate["instrumental"],
            candidate["plainLyrics"],
            candidate["syncedLyrics"],
        )

    @cached_property
    def duration_dist(self) -> float:
        """Return the absolute difference between lyrics and target duration."""
        return abs(self.duration - self.target_duration)

    @cached_property
    def is_valid(self) -> bool:
        """Return whether the lyrics item is valid.
        Lyrics duration must be within the tolerance defined by
        :attr:`DURATION_DIFF_TOLERANCE`.
        """
        return (
            self.duration_dist
            <= self.target_duration * self.DURATION_DIFF_TOLERANCE
        )

    @cached_property
    def dist(self) -> tuple[bool, float]:
        """Distance/score of the given lyrics item.

        Return a tuple with the following values:
        1. Absolute difference between lyrics and target duration
        2. Boolean telling whether synced lyrics are available.

        Best lyrics match is the one that has the closest duration to
        ``target_duration`` and has synced lyrics available.
        """
        return not self.synced, self.duration_dist

    def get_text(self, want_synced: bool) -> str:
        if self.instrumental:
            return INSTRUMENTAL_LYRICS

        if want_synced and self.synced:
            return "\n".join(map(str.strip, self.synced.splitlines()))

        return self.plain

class SearchResult(NamedTuple):
    artist: str
    title: str
    url: str

    @property
    def source(self) -> str:
        return urlparse(self.url).netloc

class LRCLib(Backend):
    """Fetch lyrics from the LRCLib API."""

    BASE_URL = "https://lrclib.net/api"
    GET_URL = f"{BASE_URL}/get"
    SEARCH_URL = f"{BASE_URL}/search"

    def fetch_candidates(
        self, artist: str, title: str, album: str, length: int
    ) -> Iterator[list[LRCLibAPI.Item]]:
        """Yield lyrics candidates for the given song data.

        I found that the ``/get`` endpoint sometimes returns inaccurate or
        unsynced lyrics, while ``search`` yields more suitable candidates.
        Therefore, we prioritize the latter and rank the results using our own
        algorithm. If the search does not give suitable lyrics, we fall back to
        the ``/get`` endpoint.

        Return an iterator over lists of candidates.
        """
        base_params = {"artist_name": artist, "track_name": title}
        get_params = {**base_params, "duration": length}
        if album:
            get_params["album_name"] = album

        yield self.fetch_json(self.SEARCH_URL, params=base_params)

        with suppress(NotFoundError):
            yield [self.fetch_json(self.GET_URL, params=get_params)]

    @classmethod
    def pick_best_match(cls, lyrics: Iterable[LRCLyrics]) -> LRCLyrics | None:
        """Return best matching lyrics item from the given list."""
        return min((li for li in lyrics if li.is_valid), default=None)

    def fetch(
        self, artist: str, title: str, album: str, length: int
    ) -> tuple[str, str] | None:
        """Fetch lyrics text for the given song data."""
        evaluate_item = partial(LRCLyrics.make, target_duration=length)

        for group in self.fetch_candidates(artist, title, album, length):
            candidates = [evaluate_item(item) for item in group]
            if item := self.pick_best_match(candidates):
                lyrics = item.get_text(self.config["synced"])
                return lyrics, f"{self.GET_URL}/{item.id}"

        return None


class MusiXmatch(Backend):
    URL_TEMPLATE = "https://www.musixmatch.com/lyrics/{}/{}"

    REPLACEMENTS = {
        r"\s+": "-",
        "<": "Less_Than",
        ">": "Greater_Than",
        "#": "Number_",
        r"[\[\{]": "(",
        r"[\]\}]": ")",
    }

    @classmethod
    def encode(cls, text: str) -> str:
        for old, new in cls.REPLACEMENTS.items():
            text = re.sub(old, new, text)

        return quote(unidecode(text))

    @classmethod
    def build_url(cls, *args: str) -> str:
        return cls.URL_TEMPLATE.format(*map(cls.encode, args))

    def fetch(self, artist: str, title: str, *_) -> tuple[str, str] | None:
        url = self.build_url(artist, title)

        html = self.fetch_text(url)
        if "We detected that your IP is blocked" in html:
            self.warn("Failed: Blocked IP address")
            return None
        html_parts = html.split('<p class="mxm-lyrics__content')
        # Sometimes lyrics come in 2 or more parts
        lyrics_parts = []
        for html_part in html_parts:
            lyrics_parts.append(re.sub(r"^[^>]+>|</p>.*", "", html_part))
        lyrics = "\n".join(lyrics_parts)
        lyrics = lyrics.strip(',"').replace("\\n", "\n")
        # another odd case: sometimes only that string remains, for
        # missing songs. this seems to happen after being blocked
        # above, when filling in the CAPTCHA.
        if "Instant lyrics for all your music." in lyrics:
            return None
        # sometimes there are non-existent lyrics with some content
        if "Lyrics | Musixmatch" in lyrics:
            return None
        return lyrics, url


    """Fetch lyrics from Genius via genius-api.

    Because genius doesn't allow accessing lyrics via the api, we first query
    the api for a url matching our artist & title, then scrape the HTML text
    for the JSON data containing the lyrics.
    """

    SEARCH_URL = "https://api.genius.com/search"
    LYRICS_IN_JSON_RE = re.compile(r'(?<=.\\"html\\":\\").*?(?=(?<!\\)\\")')
    remove_backslash = partial(re.compile(r"\\(?=[^\\])").sub, "")

    @cached_property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config['genius_api_key']}"}

    def search(self, artist: str, title: str) -> Iterable[SearchResult]:
        search_data: GeniusAPI.Search = self.fetch_json(
            self.SEARCH_URL,
            params={"q": f"{artist} {title}"},
            headers=self.headers,
        )
        for r in (hit["result"] for hit in search_data["response"]["hits"]):
            yield SearchResult(r["artist_names"], r["title"], r["url"])

    @classmethod
    def scrape(cls, html: str) -> str | None:
        if m := cls.LYRICS_IN_JSON_RE.search(html):
            html_text = cls.remove_backslash(m[0]).replace(r"\n", "\n")
            return cls.get_soup(html_text).get_text().strip()

        return None

class Html:
    collapse_space = partial(re.compile(r"(^| ) +", re.M).sub, r"\1")
    expand_br = partial(re.compile(r"\s*<br[^>]*>\s*", re.I).sub, "\n")
    #: two newlines between paragraphs on the same line (musica, letras.mus.br)
    merge_blocks = partial(re.compile(r"(?<!>)</p><p[^>]*>").sub, "\n\n")
    #: a single new line between paragraphs on separate lines
    #: (paroles.net, sweetslyrics.com, lacoccinelle.net)
    merge_lines = partial(re.compile(r"</p>\s+<p[^>]*>(?!___)").sub, "\n")
    #: remove empty divs (lacoccinelle.net)
    remove_empty_tags = partial(
        re.compile(r"(<(div|span)[^>]*>\s*</\2>)").sub, ""
    )
    #: remove Google Ads tags (musica.com)
    remove_aside = partial(re.compile("<aside .+?</aside>").sub, "")
    #: remove adslot-Content_1 div from the lyrics text (paroles.net)
    remove_adslot = partial(
        re.compile(r"\n</div>[^\n]+-- Content_\d+ --.*?\n<div>", re.S).sub,
        "\n",
    )
    #: remove text formatting (azlyrics.com, lacocinelle.net)
    remove_formatting = partial(
        re.compile(r" *</?(i|em|pre|strong)[^>]*>").sub, ""
    )

    @classmethod
    def normalize_space(cls, text: str) -> str:
        text = unescape(text).replace("\r", "").replace("\xa0", " ")
        return cls.collapse_space(cls.expand_br(text))

    @classmethod
    def remove_ads(cls, text: str) -> str:
        return cls.remove_adslot(cls.remove_aside(text))

    @classmethod
    def merge_paragraphs(cls, text: str) -> str:
        return cls.merge_blocks(cls.merge_lines(cls.remove_empty_tags(text)))


class SoupMixin:
    @classmethod
    def pre_process_html(cls, html: str) -> str:
        """Pre-process the HTML content before scraping."""
        return Html.normalize_space(html)

    @classmethod
    def get_soup(cls, html: str) -> BeautifulSoup:
        return BeautifulSoup(cls.pre_process_html(html), "html.parser")


class SearchBackend(SoupMixin, Backend):
    @cached_property
    def dist_thresh(self) -> float:
        return self.config["dist_thresh"].get(float)

    def check_match(
        self, target_artist: str, target_title: str, result: SearchResult
    ) -> bool:
        """Check if the given search result is a 'good enough' match."""
        max_dist = max(
            string_dist(target_artist, result.artist),
            string_dist(target_title, result.title),
        )

        if (max_dist := round(max_dist, 2)) <= self.dist_thresh:
            return True

        if math.isclose(max_dist, self.dist_thresh, abs_tol=0.4):
            # log out the candidate that did not make it but was close.
            # This may show a matching candidate with some noise in the name
            self.debug(
                "({0.artist}, {0.title}) does not match ({1}, {2}) but dist"
                " was close: {3:.2f}",
                result,
                target_artist,
                target_title,
                max_dist,
            )

        return False


class Genius(SearchBackend):
    """Fetch lyrics from Genius via genius-api.

    Because genius doesn't allow accessing lyrics via the api, we first query
    the api for a url matching our artist & title, then scrape the HTML text
    for the JSON data containing the lyrics.
    """

    SEARCH_URL = "https://api.genius.com/search"
    LYRICS_IN_JSON_RE = re.compile(r'(?<=.\\"html\\":\\").*?(?=(?<!\\)\\")')
    remove_backslash = partial(re.compile(r"\\(?=[^\\])").sub, "")

    @cached_property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.config['genius_api_key']}"}

    def search(self, artist: str, title: str) -> Iterable[SearchResult]:
        search_data: GeniusAPI.Search = self.fetch_json(
            self.SEARCH_URL,
            params={"q": f"{artist} {title}"},
            headers=self.headers,
        )
        for r in (hit["result"] for hit in search_data["response"]["hits"]):
            yield SearchResult(r["artist_names"], r["title"], r["url"])

    @classmethod
    def scrape(cls, html: str) -> str | None:
        if m := cls.LYRICS_IN_JSON_RE.search(html):
            html_text = cls.remove_backslash(m[0]).replace(r"\n", "\n")
            return cls.get_soup(html_text).get_text().strip()

        return None



class Tekstowo(SearchBackend):
    """Fetch lyrics from Tekstowo.pl."""

    BASE_URL = "https://www.tekstowo.pl"
    SEARCH_URL = f"{BASE_URL}/szukaj,{{}}.html"

    def build_url(self, artist, title):
        artistitle = f"{artist.title()} {title.title()}"

        return self.SEARCH_URL.format(quote_plus(unidecode(artistitle)))

    def search(self, artist: str, title: str) -> Iterable[SearchResult]:
        if html := self.fetch_text(self.build_url(title, artist)):
            soup = self.get_soup(html)
            for tag in soup.select("div[class=flex-group] > a[title*=' - ']"):
                artist, title = str(tag["title"]).split(" - ", 1)
                yield SearchResult(
                    artist, title, f"{self.BASE_URL}{tag['href']}"
                )

        return None

    @classmethod
    def scrape(cls, html: str) -> str | None:
        soup = cls.get_soup(html)

        if lyrics_div := soup.select_one("div.song-text > div.inner-text"):
            return lyrics_div.get_text()

        return None

class BackendClass(type):
    @property
    def name(cls) -> str:
        """Return lowercase name of the backend class."""
        return cls.__name__.lower()


class Backend(RequestHandler, metaclass=BackendClass):
    def __init__(self, config, log):
        self._log = log
        self.config = config

    def fetch(
        self, artist: str, title: str, album: str, length: int
    ) -> tuple[str, str] | None:
        raise NotImplementedError

class LyricsPlugin(RequestHandler, plugins.BeetsPlugin):
    BACKEND_BY_NAME = {
        b.name: b for b in [LRCLib, Genius, Tekstowo, MusiXmatch]
    }

    @cached_property
    def backends(self) -> list[Backend]:
        user_sources = self.config["sources"].get()
        chosen = sanitize_choices(user_sources, self.BACKEND_BY_NAME)

        return [self.BACKEND_BY_NAME[c](self.config, self._log) for c in chosen]

    def __init__(self):
        super().__init__()
        self.config.add(
            {
                "auto": True,
                "dist_thresh": 0.11,
                "genius_api_key": (
                    "Ryq93pUGm8bM6eUWwD_M3NOFFDAtp2yEE7W"
                    "76V-uFL5jks5dNvcGCdarqFjDhP9c"
                ),
                "fallback": None,
                "force": False,
                "local": False,
                "print": False,
                "synced": False,
                # Musixmatch is NOT disabled by default as they are currently blocking
                # requests with the beets user agent, but here the agent is ecoserver.
                # To disable it by default again, uncomment the line below.
                "sources": [
                    n for n in self.BACKEND_BY_NAME # if n != "musixmatch"
                ],
            }
        )
        self.config["genius_api_key"].redact = True

        if self.config["auto"]:
            self.import_stages = [self.imported]


    def imported(self, _, task: ImportTask) -> None:
        """Import hook for fetching lyrics automatically."""
        for item in task.imported_items():
            self.add_item_lyrics(item, True)

    def find_lyrics(self, item: Item) -> str:
        album, length = item.album, round(item.length)
        matches = (
            [
                lyrics
                for t in titles
                if (lyrics := self.get_lyrics(a, t, album, length))
            ]
            for a, titles in search_pairs(item)
        )

        return "\n\n---\n\n".join(next(filter(None, matches), []))

    def add_item_lyrics(self, item: Item, write: bool) -> None:
        """Fetch and store lyrics for a single item. If ``write``, then the
        lyrics will also be written to the file itself.
        """
        if lyrics := self.find_lyrics(item):
            self.info("🟢 Found lyrics: {}", item)
        else:
            self.info("🔴 Lyrics not found: {}", item)
            lyrics = self.config["fallback"].get()

        if lyrics not in {None, item.lyrics}:
            item.lyrics = lyrics
            if write:
                item.try_write()
            item.store()

    def get_lyrics(self, artist: str, title: str, *args) -> str:
        """Fetch lyrics, trying each source in turn. Return a string or
        None if no lyrics were found.
        """
        self.info("Fetching lyrics for {} - {}", artist, title)
        for backend in self.backends:
            with backend.handle_request():
                if lyrics_info := backend.fetch(artist, title, *args):
                    lyrics, url = lyrics_info
                    return f"{lyrics}\n\nSource: {url}"

        return None

