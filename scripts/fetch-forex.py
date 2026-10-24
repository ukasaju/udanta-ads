#!/usr/bin/env python3
"""
Mirrors Nepal Rastra Bank's foreign exchange rates.

    python3 scripts/fetch-forex.py

── Why this exists ──
NRB's API went down on 24 October 2026 — not blocking us, genuinely
offline: a GitHub runner got the same refused connection on 443 as a
laptop in another country. Every install fetched NRB directly, so a
new install during the outage had nothing at all to show, and an old
one showed whatever it had cached.

The app had no second place to look. This is the second place.

── Why the app should not fetch NRB itself ──
Rates are set once a day. A per-install fetch meant every phone asking
NRB several times a day for a number that changes at most once — and,
during an outage, four timeouts apiece before giving up. One scheduled
fetch serves everybody, is kinder to a central bank's small server,
and turns an outage into a file that is a day old rather than a screen
that is empty.

── Why NRB's own shape, not ours ──
This writes the payload exactly as NRB returns it, so the app's
existing `parseSnapshot` reads the mirror with no second parser and no
second set of bugs. The mirror is a cache of the source, not a
reinterpretation of it.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / 'forex.json'

ENDPOINT = 'https://www.nrb.org.np/api/forex/v1/rates'
UA = 'Mozilla/5.0 (compatible; Udanta/1.0; +https://github.com/ukasaju/udanta-ads)'
TIMEOUT = 30

# A week, so a run that lands on a holiday still finds the last
# published day rather than an empty range.
WINDOW_DAYS = 7


def nepal_today() -> dt.date:
    """Nepal is UTC+05:45, and the rate date follows Nepali business days."""
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=45)).date()


def fetch() -> dict | None:
    today = nepal_today()
    start = today - dt.timedelta(days=WINDOW_DAYS)
    url = f'{ENDPOINT}?page=1&per_page=10&from={start}&to={today}'
    request = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError,
            json.JSONDecodeError) as error:
        print(f'NRB unreachable: {error}', file=sys.stderr)
        return None


def latest_date(body: dict) -> str | None:
    payload = (body.get('data') or {}).get('payload')
    if not isinstance(payload, list) or not payload:
        return None
    return max((str(day.get('date', '')) for day in payload), default=None)


def main() -> int:
    body = fetch()

    if body is None:
        # Keeping yesterday's mirror is the entire point of having one.
        # A failed run must never replace good rates with nothing, so it
        # exits 1 to be visible and leaves the file alone.
        if OUT.exists():
            print('kept the existing mirror; nothing overwritten', file=sys.stderr)
        else:
            print('no mirror exists yet and NRB is unreachable', file=sys.stderr)
        return 1

    date = latest_date(body)
    if not date:
        print('NRB answered but the payload held no dated rates', file=sys.stderr)
        return 1

    # Refuse to go backwards. A source that briefly serves an older day —
    # or an empty one dressed as a response — must not overwrite a newer
    # mirror, which is the one way this could make things worse.
    if OUT.exists():
        try:
            current = latest_date(json.loads(OUT.read_text(encoding='utf-8'))) or ''
        except (json.JSONDecodeError, OSError):
            current = ''
        if current and date < current:
            print(f'refusing to publish {date}; the mirror already has {current}',
                  file=sys.stderr)
            return 1

    OUT.write_text(json.dumps(body, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    rates = len(((body.get('data') or {}).get('payload') or [{}])[-1].get('rates', []))
    print(f'mirrored NRB rates for {date} ({rates} currencies)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
