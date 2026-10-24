#!/usr/bin/env python3
"""
Refuses to let a broken ads.json reach the app.

    python3 scripts/check-ads.py

── Why this exists ──
A single missing comma took every published ad off every new install
for as long as it sat here. The file stayed valid-looking, GitHub
rendered it without complaint, and nothing told anybody: the app
catches a parse failure and falls back to its cache, so existing
installs carried on showing the old ads while new ones showed none.
The only visible symptom was "it works on my phone and not on a fresh
one", which is the hardest kind to chase.

── What it checks ──
Valid JSON first, then the same rules `parseAd` applies in the app, so
a file that parses but would be silently dropped ad-by-ad also fails.
An ad the app would discard is worse than a syntax error, because the
file looks fine.
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ADS = ROOT / 'ads.json'

# Mirrors `link()` in src/ads/remote.ts.
SCHEMES = ('https://', 'app://', 'mailto:')
REQUIRED = ('id', 'advertiser', 'headline', 'cta', 'url')


def media_urls(media: object) -> list[str]:
    """A promo's media is one item or a gallery; both are checked."""
    items = media if isinstance(media, list) else [media]
    out = []
    for item in items:
        if isinstance(item, dict) and item.get('type') in ('image', 'video'):
            out.append(str(item.get('url', '')))
    return out


def main() -> int:
    if not ADS.exists():
        print(f'{ADS.name} not found', file=sys.stderr)
        return 1

    try:
        data = json.loads(ADS.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        print(f'{ADS.name} is not valid JSON: {error}', file=sys.stderr)
        return 1

    ads = data.get('ads')
    if not isinstance(ads, list) or not ads:
        print('no ads array', file=sys.stderr)
        return 1

    # Ids the app ships a copy of, and suppresses its own copy of when
    # the published file uses the same one. Renaming these does not
    # create a new ad, it un-suppresses the bundled twin and the reader
    # sees it twice.
    BUNDLED_IDS = {'appeal-flood-relief'}

    problems: list[str] = []
    seen: set[tuple] = set()

    for index, ad in enumerate(ads):
        where = ad.get('id') or f'ad #{index + 1}'

        for field in REQUIRED:
            if not ad.get(field):
                problems.append(f'{where}: missing {field}')

        url = ad.get('url')
        if isinstance(url, str) and not url.startswith(SCHEMES):
            problems.append(f'{where}: url scheme not allowed — {url[:40]}')

        # A creative that opens something must carry the block it opens.
        if url == 'app://promo' and not ad.get('promo'):
            problems.append(f'{where}: app://promo with no promo block')
        if url == 'app://share' and not ad.get('share'):
            problems.append(f'{where}: app://share with no share block')

        for candidate in media_urls(ad.get('media')) + media_urls(
            (ad.get('promo') or {}).get('media')
        ):
            if not candidate.startswith('https://'):
                problems.append(f'{where}: media must be https — {candidate[:40]}')

        lang = ad.get('lang')
        if lang not in (None, 'en', 'ne'):
            problems.append(f'{where}: lang must be en, ne or absent — got {lang!r}')

        # Two ads may share an id when they differ by language — that is
        # how the same creative is published in both, and only one
        # language is ever served at a time. Sharing an id *within* one
        # language is a React key collision and one of them will not
        # render.
        #
        # More than tidiness: the app suppresses its bundled copy of an
        # appeal when the published file carries the same id. Rename the
        # published one and both serve, so the reader sees the appeal
        # twice and it pushes another ad out of the strip. The id is
        # load-bearing, so this check must not encourage changing it.
        key = (ad.get('id'), ad.get('lang'))
        if key in seen:
            problems.append(f'{where}: duplicate id for lang={ad.get("lang")!r}')
        seen.add(key)

    # A warning rather than a failure: an appeal may legitimately be
    # retired from the published file, and this cannot tell that from a
    # rename. But a rename is the likelier mistake and it is invisible
    # in the app except as a duplicated banner.
    published_ids = {ad.get('id') for ad in ads}
    for bundled in sorted(BUNDLED_IDS - published_ids):
        near = [i for i in published_ids if isinstance(i, str) and i.startswith(bundled)]
        if near:
            print(
                f'warning: {near[0]!r} looks like a renamed {bundled!r}. The app '
                f'only suppresses its bundled copy on an exact id match, so both '
                f'will serve and the reader will see it twice.',
                file=sys.stderr,
            )

    if problems:
        print(f'{len(problems)} problem(s) in {ADS.name}:', file=sys.stderr)
        for problem in problems:
            print(f'  - {problem}', file=sys.stderr)
        return 1

    print(f'{ADS.name}: {len(ads)} ads, all would be served.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
