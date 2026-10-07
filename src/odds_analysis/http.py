"""Polite HTTP client for arsiv.mackolik.com: fixed headers, <=1 request/sec, retries with backoff."""

from __future__ import annotations

import gzip
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
# Mackolik returns bursts of 500/502: 3 retries after 5, 15 and 45 seconds. A request that still fails is logged
# by the job and retried in the next run (see retry.py).
BACKOFF_SECONDS = (5, 15, 45)
LIST_BACKOFF_SECONDS = BACKOFF_SECONDS

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
    timeout_s: float = 20.0
    raw_dir: Path | None = None
    requests: int = field(default=0, init=False)  # HTTP attempts, retries included
    calls: int = field(default=0, init=False)  # logical requests (get() calls)
    failed: int = field(default=0, init=False)  # logical requests that still failed after all retries
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

    def get(self, path: str, *, referer: str | None = None, save_as: str | None = None,
            backoff: tuple[int, ...] | None = None, follow_redirects: bool = False) -> FetchResult:
        url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
        headers = {"referer": referer} if referer else None
        start = time.monotonic()
        last_error: str | None = None
        status: int | None = None
        text = ""
        attempts = 0
        delays = BACKOFF_SECONDS if backoff is None else backoff
        self.calls += 1
        for attempt in range(len(delays) + 1):
            attempts = attempt + 1
            self._throttle()
            self.requests += 1
            try:
                resp = self._client.get(url, headers=headers, follow_redirects=follow_redirects)
                status, text, last_error = resp.status_code, resp.text, None
                if status not in RETRY_STATUSES:
                    break
                last_error = f"HTTP {status}"
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < len(delays):
                log.warning("retry %s after %s (%s)", url, delays[attempt], last_error)
                time.sleep(delays[attempt])
        if status is not None and status != 200 and last_error is None:
            last_error = f"HTTP {status}"
        if last_error is not None:
            self.failed += 1
        if self.raw_dir and save_as:
            path = self.raw_dir / save_as
            path.parent.mkdir(parents=True, exist_ok=True)
            if save_as.endswith(".gz"):
                path.write_bytes(gzip.compress(text.encode("utf-8"), mtime=0))
            else:
                path.write_text(text, encoding="utf-8")
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


def morebets_path(match_id: int | str) -> str:
    """The program's 'Tümü' data keyed by mackolik match id (fallback when the popup resolves the wrong match)."""
    return f"AjaxHandlers/IddaaHandler.aspx?command=morebets&mac={match_id}&type=ByDate"


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
