#!/usr/bin/env python3
"""
Checks the puzzle word lists are fit to publish.

    python3 scripts/check-words.py

── Why this exists ──
Word fit started repeating itself within two days, and the cause was not
the seed or the shuffle. The grid asks for about five seven-letter words a
day and the English list held eight of them, so the same handful came up
every morning: `morning` on twenty-five days out of thirty.

Nobody noticed because nothing was watching. A word list does not break
loudly — it quietly gets boring, which is the same outcome as broken and
takes months to spot. This is the thing that watches.

── What it does not do ──
It does not fetch words. There is no free list of common Nepali words that
is not a dictionary, and the open dictionaries are licensed in ways that do
not suit a store binary — which is why these lists were written out by hand
in the first place. Generating vocabulary automatically would mean either
licensing something or scraping the news feeds, and the feeds give inflected
forms, acronyms and transliterated English: fine as guesses a game accepts,
wrong as the answers it sets.

── Thin is a warning, shrinking is an error ──
A band being short is a known state that wants vocabulary, and the Nepali
list is short today: seven words of six letters, two of seven, against the
akshara problem that makes long Nepali words hard to interlock anyway.
Failing the job over that would block every unrelated change until someone
sat down and wrote Nepali, which is how checks get switched off.

What it does fail on is a band getting *smaller* than the published file
already has. That is the regression this was written after — not "the list
is imperfect" but "the list got worse and nobody said".
"""
from __future__ import annotations

import json
import pathlib
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORDS = ROOT / 'words.json'

# Roughly what one puzzle consumes at each length, measured over thirty days
# of real grids. The seven-letter row is the one that bit.
DEMAND_PER_DAY = {4: 1.4, 5: 1.7, 6: 1.1, 7: 4.8}

# How many distinct words a band needs per word the grid takes from it each
# day. Eight sevens against a demand of 4.8 gave `morning` on 25 days in 30;
# ten to one keeps any single word rare.
SUPPLY_RATIO = 10


def letters(word: str) -> int:
    """
    Written letters, not code points.

    Devanagari marks hang off the letter before them, so `पानी` is four
    code points and two letters. The grid is built in letters, so the
    lists have to be measured in letters or the counts here describe a
    different game from the one being played.
    """
    count = 0
    for ch in unicodedata.normalize('NFC', word):
        if unicodedata.combining(ch):
            continue
        if ch == '्':  # virama: joins what follows to what precedes
            count -= 1
        count += 1
    return max(count, 1)


def report(name: str, words: list[str], before: dict[int, int] | None) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    seen: dict[str, int] = {}
    for word in words:
        seen[word] = seen.get(word, 0) + 1
    repeats = sorted(w for w, n in seen.items() if n > 1)
    if repeats:
        problems.append(f'{name}: repeated entries — {", ".join(repeats[:8])}')

    bands: dict[int, int] = {}
    for word in set(words):
        bands[letters(word)] = bands.get(letters(word), 0) + 1

    print(f'  {name}: {len(set(words))} distinct words')
    for length, per_day in sorted(DEMAND_PER_DAY.items()):
        have = bands.get(length, 0)
        want = round(per_day * SUPPLY_RATIO)
        mark = 'ok ' if have >= want else 'THIN'
        print(f'    {length} letters: {have:4d}   wants {want:3d}   {mark}')
        if have < want:
            warnings.append(
                f'{name}: only {have} words of {length} letters; the grid uses '
                f'about {per_day} a day, so this band will repeat'
            )
        was = (before or {}).get(length)
        if was is not None and have < was:
            problems.append(
                f'{name}: the {length}-letter band shrank from {was} to {have}'
            )
    return problems, warnings


def main() -> int:
    if not WORDS.exists():
        print('words.json is missing', file=sys.stderr)
        return 1
    try:
        doc = json.loads(WORDS.read_text(encoding='utf-8'))
    except json.JSONDecodeError as error:
        print(f'words.json will not parse: {error}', file=sys.stderr)
        return 1

    before: dict[str, dict[int, int]] = {}
    if len(sys.argv) > 1:
        # The published file, so a band cannot quietly get smaller.
        baseline = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
        for name in ('en', 'ne'):
            bands: dict[int, int] = {}
            for word in set(str(w) for w in baseline.get(name, [])):
                bands[letters(word)] = bands.get(letters(word), 0) + 1
            before[name] = bands

    problems: list[str] = []
    warnings: list[str] = []
    active = str(doc.get('activeFrom', ''))
    if len(active.split('-')) != 3:
        problems.append('activeFrom must be a Bikram Sambat day, YYYY-MM-DD')

    for name in ('en', 'ne'):
        words = doc.get(name)
        if not isinstance(words, list) or len(words) < 30:
            problems.append(f'{name}: fewer than thirty words; the app would ignore this file')
            continue
        bad, thin = report(name, [str(w) for w in words], before.get(name))
        problems.extend(bad)
        warnings.extend(thin)

    if warnings:
        print('\nthin, and worth topping up:')
        for line in warnings:
            print(f'  - {line}')

    if problems:
        print('\nnot fit to publish:', file=sys.stderr)
        for line in problems:
            print(f'  - {line}', file=sys.stderr)
        return 1

    print('\nword lists are fit to publish')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
