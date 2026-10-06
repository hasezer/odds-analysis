"""Polite HTTP client for arsiv.mackolik.com: fixed headers, <=1 request/sec, retries with backoff."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE = "https://arsiv.mackolik.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_HEADERS = {
    "user-agent": USER_AGENT,
    "referer": f"{BASE}/Iddaa-Programi",
    "x-requested-with": "XMLHttpRequest",
    "accept-language": "tr-TR,tr;q=0.9,en;q=0.8",
}
RETRY_STATUSES = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = (2, 4, 8, 16)

log = logging.getLogger(__name__)


@dataclass
class FetchResult:
    url: str
    status: int | None
    text: str
    elapsed_s: float
    attempts: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


@dataclass
class MackolikClient:
    min_interval_s: float = 1.0
    timeout_s: float = 30.0
    raw_dir: Path | None = None
    _last_request: float = field(default=0.0, init=False)
    _client: httpx.Client = field(init=False)

    def __post_init__(self) -> None:
        self._client = httpx.Client(
            headers=DEFAULT_HEADERS, timeout=self.timeout_s, follow_redirects=False
        )
        if self.raw_dir:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MackolikClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self.min_interval_s - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def get(self, path: str, *, referer: str | None = None, save_as: str | None = None) -> FetchResult:
        url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
        headers = {"referer": referer} if referer else None
        start = time.monotonic()
        last_error: str | None = None
        status: int | None = None
        text = ""
        attempts = 0
        for attempt in range(len(BACKOFF_SECONDS) + 1):
            attempts = attempt + 1
            self._throttle()
            try:
                resp = self._client.get(url, headers=headers)
                status, text, last_error = resp.status_code, resp.text, None
                if status not in RETRY_STATUSES:
                    break
                last_error = f"HTTP {status}"
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < len(BACKOFF_SECONDS):
                log.warning("retry %s after %s (%s)", url, BACKOFF_SECONDS[attempt], last_error)
                time.sleep(BACKOFF_SECONDS[attempt])
        if status is not None and status != 200 and last_error is None:
            last_error = f"HTTP {status}"
        if self.raw_dir and save_as:
            (self.raw_dir / save_as).write_text(text, encoding="utf-8")
        return FetchResult(url, status, text, time.monotonic() - start, attempts, last_error)


def day_list_path(date: str, *, np: int = 0, week: int | str = "") -> str:
    """Endpoint A. date is dd.mm.yyyy or -1 (whole rolling window). np=0 includes played matches."""
    return (
        "AjaxHandlers/IddaaHandler.aspx?command=tab&type=2&st=Football&l=-1"
        f"&d={date}&i=0&t=&ip=1&w={week}&g=7&np={np}&srt=-1&srtd=1"
    )


def odds_popup_path(event_code: str | int) -> str:
    """Endpoint B: every market of one event (the 'Tümü' popup)."""
    return f"AjaxHandlers/IddaaHandler.aspx?command=oddspopup&e={event_code}&s=futbol"


PROGRAM_PATH = "Iddaa-Programi"  # Endpoint C


def match_page_path(match_id: int | str) -> str:
    """Endpoint D: match detail page (header, stadium, referee, server-rendered stats)."""
    return f"Match/Default.aspx?id={match_id}"


def match_data_path(match_id: int | str) -> str:
    """D, AJAX: scores (MS/İY) + events (goals, cards, subs). Loaded by Match.js on the page."""
    return f"Match/MatchData.aspx?t=dtl&id={match_id}&s=0"


def opta_stats_path(match_id: int | str) -> str:
    """D, AJAX: the 'İstatistikler' box (Opta)."""
    return f"AjaxHandlers/MatchHandler.aspx?command=optaStats&id={match_id}"


def rb_stats_path(match_id: int | str) -> str:
    """D, AJAX: secondary stats box (Perform/RB) - fallback when Opta is missing."""
    return f"AjaxHandlers/MatchHandler.aspx?command=rbStats&id={match_id}"


def match_referer(match_id: int | str) -> str:
    return f"{BASE}/{match_page_path(match_id)}"
