#!/usr/bin/env python3
"""
Assembles a candidate bank interest rate sheet.

    python3 scripts/fetch-bank-rates.py

── Why this exists ──
Bank rates are the one table in the app with no machine-readable source
behind it (see docs/bank-rates.md), so somebody keys them in at the start
of every Nepali month. Done entirely by hand that is five sources, ten
page visits and about forty minutes of copying numbers into JSON without
typos, twelve times a year — which is exactly the kind of chore that
quietly stops getting done, leaving the app showing Ashwin's rates in
Magh.

This does the fetching and the arithmetic. It does not decide anything:
it writes a candidate file next to the live one and prints what it could
not reach, and a human reads the diff before publishing. A source that
changes shape drops out with a note rather than emitting a wrong number.

── What it can and cannot do ──
Savings, home and vehicle come off comparison tables that are plain
HTML, so those three are fully automatic.

Two are not, and deliberately are not. The highest fixed-deposit rate
lives in a monthly round-up written as prose — "Prabhu Bank set the
highest at 4.55 percent, followed by ... which all offered 4.50" — and
a regex that reads that correctly this month will silently mis-assign
a rate the month the writer rephrases it. Base rates come from a page
whose table is half-rendered server-side. Both are left to a human.

Term ladders are never scraped either: the banks bracket tenures
differently, so mapping a bracket onto "1 year" is a judgement, not a
parse.

Whatever cannot be fetched is carried over from the previous sheet and
listed at the end, so a bank does not drop out of the table because a
site was down — but a carried-over figure is last month's, and the
report says so.
"""
# Python 3.9 on this machine, so annotations are strings.
from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Udanta/1.0'
ROOT = Path(__file__).resolve().parent.parent
# The sheet currently published. Anything the run cannot fetch is
# carried over from here, so a source being down costs you last
# month's figure rather than the whole row.
# In this repo the live sheet and the output are the same file: the
# workflow commits what it writes. The candidate-then-review step
# belonged in the app repo, where a person did the reviewing; here the
# guards in `main` do it, and a run that cannot vouch for the sheet
# fails instead of writing one.
LIVE = ROOT / 'bank-rates.json'
OUT = ROOT / 'bank-rates.json'

# Every id the app knows, with the spellings the sources use for it. The
# match is on a normalised, lowercased name, longest alias first, so
# "nepal investment mega bank" cannot be swallowed by "nepal bank".
BANKS = {
    'prabhu': ('Prabhu Bank', 'प्रभु बैंक', 'PRVU', ['prabhu']),
    'machhapuchchhre': ('Machhapuchchhre Bank', 'माछापुच्छ्रे बैंक', 'MBL',
                        ['machhapuchchhre', 'machhapuchhre', 'machapuchchhre']),
    'nmb': ('NMB Bank', 'एनएमबी बैंक', 'NMB', ['nmb']),
    'sanima': ('Sanima Bank', 'सानिमा बैंक', 'SANIMA', ['sanima']),
    'nimb': ('Nepal Investment Mega Bank', 'नेपाल इन्भेष्टमेन्ट मेगा बैंक', 'NIMB',
             ['nepal investment mega', 'nepal investment']),
    'nabil': ('Nabil Bank', 'नबिल बैंक', 'NABIL', ['nabil']),
    'nepal-bank': ('Nepal Bank', 'नेपाल बैंक', 'NBL', ['nepal bank']),
    'nsbi': ('Nepal SBI Bank', 'नेपाल एसबिआई बैंक', 'SBI', ['nepal sbi']),
    'global-ime': ('Global IME Bank', 'ग्लोबल आइएमई बैंक', 'GBIME', ['global ime']),
    'nic-asia': ('NIC Asia Bank', 'एनआईसी एशिया बैंक', 'NICA', ['nic asia']),
    'prime': ('Prime Commercial Bank', 'प्राइम कमर्सियल बैंक', 'PCBL', ['prime commercial', 'prime']),
    'rbb': ('Rastriya Banijya Bank', 'राष्ट्रिय वाणिज्य बैंक', None,
            ['rastriya banijya', 'rastrya banijya']),
    'himalayan': ('Himalayan Bank', 'हिमालयन बैंक', 'HBL', ['himalayan']),
    'laxmi-sunrise': ('Laxmi Sunrise Bank', 'लक्ष्मी सनराइज बैंक', 'LSL', ['laxmi sunrise']),
    'citizens': ('Citizens Bank', 'सिटिजन्स बैंक', 'CZBIL', ['citizens']),
    'siddhartha': ('Siddhartha Bank', 'सिद्धार्थ बैंक', 'SBL', ['siddhartha']),
    'scb': ('Standard Chartered Bank Nepal', 'स्ट्यान्डर्ड चार्टर्ड बैंक नेपाल', 'SCB',
            ['standard chartered']),
    'everest': ('Everest Bank', 'एभरेष्ट बैंक', 'EBL', ['everest']),
    'kumari': ('Kumari Bank', 'कुमारी बैंक', 'KBL', ['kumari']),
}

# Longest alias first so the specific name wins over the general one.
ALIASES = sorted(
    ((alias, bank_id) for bank_id, (_, _, _, aliases) in BANKS.items() for alias in aliases),
    key=lambda pair: -len(pair[0]),
)

# Plain HTML tables, one row per bank per product. These are fetched.
SOURCES = {
    'savings': 'https://bankbyaj.com/detail/current-savings',
    'home': 'https://bankbyaj.com/detail/home-loan-nepali-banks',
    'auto': 'https://bankbyaj.com/detail/auto-loan',
    # Added 20 October 2026. Both of these were in BY_HAND, on the
    # grounds that the fixed-deposit figure lived in a prose round-up
    # and the base-rate table was only half-rendered. Neither is true
    # any more: bankbyaj serves both as plain server-side tables, one
    # bank per row, 48 rows each. Checked by fetching them.
    #
    # This is the difference between a sheet that needs a person every
    # month and one that does not, so it is worth saying why it was
    # not done before: the old sources genuinely could not be parsed
    # safely. These can.
    'fixed': 'https://www.bankbyaj.com/deposite',
    'base': 'https://www.bankbyaj.com/baserate',
    # Term ladders. Also once in BY_HAND, and for a reason that has
    # stopped applying: the objection was that banks bracket tenures
    # differently, so mapping a bracket onto "1 year" is a judgement.
    # This page has already made that judgement and publishes a Tenure
    # column — "9 months", "2 years" — normalised across every bank,
    # which is the whole difficulty handled consistently in one place.
    'ladder': 'https://www.bankbyaj.com/detail/fd-individual',
}

# What is still left to a person.
#
# Term ladders only. The banks bracket tenures differently — three
# months here, ninety days there, "upto 1 year" somewhere else — so
# mapping a bracket onto "1 year" is a judgement rather than a parse,
# and no aggregator publishes the ladders at all.
# Nothing left. Every column the app shows is fetched.
BY_HAND: dict[str, str] = {}

# ── Bank marks ──
#
# The app draws a bank's logo where the sheet gives it one and its
# NEPSE ticker where it does not, at a fixed 50x28 either way.
#
# These are each bank's own favicon, taken from its own site, which is
# the only square-ish mark a bank reliably publishes: the logos on
# their homepages are wide lockups of logo plus wordmark that are
# illegible shrunk into that tile. Four banks have none that could be
# fetched — Citizens, Prabhu and Siddhartha serve an HTML page at the
# favicon path and Kumari serves nothing — so those four keep their
# ticker, which is what the fallback is for.
#
# Committed here rather than hot-linked: a bank redesigning its site
# should not blank a column, and these are small.
LOGO_BASE = 'https://raw.githubusercontent.com/ukasaju/udanta-ads/main/bank-logos/'
LOGO_DIR = ROOT / 'bank-logos'


def logo_for(bank_id: str) -> str | None:
    """The published mark for a bank, or None if we do not have one."""
    return f'{LOGO_BASE}{bank_id}.png' if (LOGO_DIR / f'{bank_id}.png').exists() else None


problems: list[str] = []


def note(message: str) -> None:
    problems.append(message)
    print(f'  ! {message}', file=sys.stderr)


def get(url: str) -> str | None:
    """One page, politely, or None with a note. Never raises."""
    try:
        request = urllib.request.Request(url, headers={'User-Agent': UA})
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        return body.decode('utf-8', errors='replace')
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as error:
        note(f'{url} — {error}')
        return None


def rows_of(html: str) -> list[str]:
    """
    HTML to one string per table row.

    Splitting on cells was the first attempt and it found nothing: in a
    rate table the bank's name and its rate are in different cells, so
    a cell never contains both. Rows are the unit that holds a fact.
    """
    html = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html)
    html = re.sub(r'(?i)</(tr|p|li|h[1-6])>', '\n', html)
    html = re.sub(r'(?i)</(td|th)>', ' | ', html)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = (html.replace('&nbsp;', ' ').replace('&amp;', '&')
                .replace('&#39;', "'").replace('&quot;', '"'))
    html = re.sub(r'[ \t\xa0]+', ' ', html)
    return [line.strip() for line in html.split('\n') if line.strip()]


# Only commercial banks belong in these tables. The comparison sites
# list development banks, finance companies and microfinance in the
# same table, and several of their names contain a commercial bank's —
# "Mahalaxmi Bikas Bank" matched Laxmi Sunrise on the first run and
# quietly overwrote its rate with a development bank's.
def table_rows_of(html: str) -> list[str]:
    """
    The same, but splitting on `</tr>` alone.

    `rows_of` also breaks on `</p>`, `</li>` and headings, because some
    sources list a bank per paragraph rather than per table row. On
    bankbyaj's deposit and base-rate tables that is actively wrong: the
    cells contain paragraph markup, so a row arrives split into pieces
    with one figure each. `Bank | 2.75% | 4.15%` became `Bank | 2.75%`,
    and the fixed-deposit column silently came back empty — the scrape
    reported nothing while the output file looked full, because every
    bank had quietly kept last month's figure.

    Worth the second function rather than a flag: the two rules are
    different readings of what a row is, and a caller should have to
    say which one it means.
    """
    html = re.sub(r'(?is)<(script|style).*?</\1>', ' ', html)
    html = re.sub(r'(?i)</tr>', '\n', html)
    html = re.sub(r'(?i)</(td|th)>', ' | ', html)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = (html.replace('&nbsp;', ' ').replace('&amp;', '&')
                .replace('&#39;', "'").replace('&quot;', '"'))
    html = re.sub(r'[ \t\xa0]+', ' ', html)
    return [line.strip() for line in html.split('\n') if line.strip()]


NOT_COMMERCIAL = re.compile(r'(?i)\b(bikas|bikash|laghubitta|finance|microfinance|development)\b')


def match_bank(line: str) -> str | None:
    if NOT_COMMERCIAL.search(line):
        return None
    lowered = re.sub(r'[^a-z ]+', ' ', line.lower())
    lowered = re.sub(r'\s+', ' ', lowered)
    for alias, bank_id in ALIASES:
        if alias in lowered:
            return bank_id
    return None


# "4.55%" and "4.55 percent" both appear: the comparison tables use the
# sign, the monthly round-ups are prose and spell it out.
PERCENT = re.compile(r'(\d{1,2}(?:\.\d{1,2})?)\s*(?:%|per\s?cent)', re.I)


def percents(line: str) -> list[float]:
    """Every plausible percentage on a line, in order."""
    found = []
    for raw in PERCENT.findall(line):
        value = float(raw)
        # Deposit and lending rates in Nepal live between about 2 and
        # 15. Anything else on the line is a share of something, a year,
        # or a phone number that happened to catch the pattern.
        if 1 <= value <= 20:
            found.append(value)
    return found


def scrape_one_per_bank(url: str, pick, reader=rows_of) -> dict[str, float]:
    """
    A bank per line, one figure taken from each. `pick` chooses it.

    `reader` is how the page is cut into lines — `rows_of` for the
    comparison pages, `table_rows_of` where a row must stay whole
    because the figure wanted is not the first one on it.
    """
    html = get(url)
    if not html:
        return {}
    out: dict[str, float] = {}
    for line in reader(html):
        bank_id = match_bank(line)
        if not bank_id:
            continue
        values = percents(line)
        if not values:
            continue
        chosen = pick(line, values)
        if chosen is None:
            continue
        # "From" columns keep the lowest seen; a bank appears on several
        # rows of these tables, one per product.
        out[bank_id] = min(out[bank_id], chosen) if bank_id in out else chosen
    return out


# Products nobody can choose to qualify for, and products that are a
# different thing than the one being compared. Same rule the hand-kept
# sheet uses; docs/bank-rates.md explains why each is out.
# `fixed` bare, not just "fixed rate": the sheets also write "Auto
# Loan-Fixed", which slipped through the first version and put Nepal
# SBI's 8.99% fixed-rate product in a column of floating ones. These
# are loan pages, so nothing here is a fixed *deposit*.
EXCLUDE = re.compile(r'(?i)\b(fixed|festive|army|quake|earthquake|victim)\b')


def loan_from(line: str, values: list[float]) -> float | None:
    if EXCLUDE.search(line):
        return None
    return min(values)


def scrape_spreads(url: str) -> dict[str, dict[str, float]]:
    """
    Lowest and highest savings rate per bank, from one comparison table.

    A bank appears on several rows here, one per savings product, so
    the spread is the floor and ceiling across all of its rows. Taking
    it from one table rather than from nineteen bank sheets is what
    makes the column comparable down its own length — and what makes it
    possible at all, since most bank sheets are JavaScript or PDF.
    """
    html = get(url)
    if not html:
        return {}
    seen: dict[str, list[float]] = {}
    for line in rows_of(html):
        bank_id = match_bank(line)
        if not bank_id:
            continue
        seen.setdefault(bank_id, []).extend(v for v in percents(line) if 1 <= v <= 12)
    return {
        bank_id: {'min': min(values), 'max': max(values)}
        for bank_id, values in seen.items()
        if values
    }


# The rungs the app draws. A tenure that is not one of these is a
# product we do not have a column for, and is dropped rather than
# rounded into the nearest — "18 months" is not a 1-year rate.
LADDER_TERMS = {6: '6m', 12: '1y', 24: '2y', 60: '5y'}

TENURE = re.compile(r'(?i)([\d.]+)\s*(month|year)')


def tenure_months(text: str) -> int | None:
    """
    A tenure cell to a whole number of months, or None.

    Fractional years are refused. The page writes a `>3Y to 5Y` bracket
    as "3.08 years", which is the lower bound of a range rather than a
    term anybody can deposit for; rounding it to 37 months and then to
    the 5-year rung would put a bracket's floor in a column labelled as
    its ceiling.
    """
    found = TENURE.search(text)
    if not found:
        return None
    value, unit = float(found.group(1)), found.group(2).lower()
    if unit == 'month':
        return round(value)
    return round(value * 12) if value == int(value) else None


def scrape_ladders(url: str) -> dict[str, dict[str, float]]:
    """
    The fixed-deposit ladder per bank: term to the best rate at it.

    One row per product, so a bank appears many times and the highest
    rate at each term wins — the same rule the `best` column uses, and
    the one a depositor would apply themselves.
    """
    html = get(url)
    if not html:
        return {}
    out: dict[str, dict[str, float]] = {}
    for line in table_rows_of(html):
        bank_id = match_bank(line)
        if not bank_id:
            continue
        values = percents(line)
        if not values:
            continue
        months = tenure_months(line)
        rung = LADDER_TERMS.get(months) if months else None
        if not rung:
            continue
        rungs = out.setdefault(bank_id, {})
        rungs[rung] = max(rungs.get(rung, 0.0), values[0])
    return out


def second_column(_line: str, values: list[float]) -> float | None:
    """
    The second percentage on the row.

    `/deposite` is `Bank | Saving | Fixed`, and `/baserate` is
    `Bank | Base Rate | NPA`. In both the figure wanted is the second,
    and in both the first is a number this script already has from a
    better source — so taking position rather than a label keeps one
    function for two tables.

    A row with one percentage is a bank quoting nothing for that
    column, and gets nothing rather than having its other figure
    misread as this one.
    """
    return values[1] if len(values) >= 2 else None


def first_column(_line: str, values: list[float]) -> float | None:
    """The first percentage on the row — the base rate on `/baserate`."""
    return values[0] if values else None


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if len(args) != 2:
        print(__doc__)
        print('usage: fetch-bank-rates.py <bs-year> <bs-month>\n'
              '   eg: fetch-bank-rates.py 2083 7', file=sys.stderr)
        return 2
    year, month = int(args[0]), int(args[1])

    previous = {}
    if not LIVE.exists():
        note(f'{LIVE.name} not found — nothing to carry over, so the by-hand '
             f'columns will be missing entirely')
    else:
        for bank in json.loads(LIVE.read_text()).get('banks', []):
            previous[bank['id']] = bank

    print('Reading sources…', file=sys.stderr)
    savings = scrape_spreads(SOURCES['savings'])
    time.sleep(1)
    home = scrape_one_per_bank(SOURCES['home'], loan_from)
    time.sleep(1)
    auto = scrape_one_per_bank(SOURCES['auto'], loan_from)
    time.sleep(1)
    # Second column of `Bank | Saving | Fixed`.
    fixed_best = scrape_one_per_bank(SOURCES['fixed'], second_column, table_rows_of)
    time.sleep(1)
    # First column of `Bank | Base Rate | NPA`. NPA is not a rate the
    # app shows and must not be mistaken for one.
    base = scrape_one_per_bank(SOURCES['base'], first_column, table_rows_of)
    time.sleep(1)
    ladders = scrape_ladders(SOURCES['ladder'])

    banks = []
    for bank_id, (name_en, name_ne, symbol, _) in BANKS.items():
        entry: dict = {'id': bank_id, 'name': {'en': name_en, 'ne': name_ne}}
        if symbol:
            entry['symbol'] = symbol
        logo = logo_for(bank_id)
        if logo:
            entry['logo'] = logo

        was = previous.get(bank_id, {})
        if bank_id in savings:
            entry['savings'] = savings[bank_id]
        elif 'savings' in was:
            entry['savings'] = was['savings']

        # Term ladders are never scraped: the banks bracket tenures
        # differently and mapping a bracket onto a term is a judgement,
        # not a parse. Last month's are carried over for a human to
        # check against the sheet.
        # Replaced wholesale for a bank we have rungs for, not merged
        # into last month's. Merging would leave a row with a fresh
        # 6-month rate beside a stale 2-year one and no way for a
        # reader to tell which is which — the same objection the sheet
        # already makes to folding one month over another. A bank the
        # page does not list keeps its old ladder and is reported.
        ladder = dict(ladders[bank_id]) if bank_id in ladders else dict(was.get('fixed', {}))
        if bank_id in fixed_best:
            ladder['best'] = fixed_best[bank_id]
        elif 'best' in was.get('fixed', {}):
            ladder['best'] = was['fixed']['best']
        if ladder:
            entry['fixed'] = ladder

        loans = {}
        for kind, table in (('base', base), ('home', home), ('auto', auto)):
            if bank_id in table:
                loans[kind] = table[bank_id]
            elif kind in was.get('loans', {}):
                loans[kind] = was['loans'][kind]
        if loans:
            entry['loans'] = loans

        if 'savings' in entry or 'fixed' in entry or 'loans' in entry:
            banks.append(entry)

    sheet = {
        '_comment': f'Candidate sheet built by scripts/fetch-bank-rates.py. '
                    f'Review against the sources before publishing; term ladders are '
                    f'carried over from the previous sheet and must be checked by hand.',
        'bs': {'year': year, 'month': month},
        'banks': banks,
    }
    OUT.write_text(json.dumps(sheet, ensure_ascii=False, indent=2) + '\n')

    print(f'\nWrote {OUT.relative_to(ROOT)}', file=sys.stderr)
    total = len(BANKS)
    print('  fetched:', file=sys.stderr)
    for label, table in (
        ('savings', savings),
        ('fixed (highest)', fixed_best),
        ('base rate', base),
        ('home loan', home),
        ('vehicle loan', auto),
        ('term ladders', ladders),
    ):
        short = total - len(table)
        # A column that came up short says so here rather than being
        # noticed a month later in the app: the missing banks keep last
        # month's figure, which is the one thing a reader cannot tell
        # from the table itself.
        carried = f'   ({short} carried over)' if short else ''
        print(f'    {label:16} {len(table):2}/{total}{carried}', file=sys.stderr)
    if BY_HAND:
        print('  carried over from last sheet — update these by hand:',
              file=sys.stderr)
        for what, where in BY_HAND.items():
            print(f'    {what:16} {where}', file=sys.stderr)
    # A column that came back mostly empty is a parser that has stopped
    # working, not a month where fifteen banks withdrew a product. In
    # `--strict` — which is how the scheduled job runs it — that fails
    # the run instead of publishing a sheet where most rows quietly kept
    # last month's figure. This is the exact failure that hid here once
    # already: `fixed` reported 0/19 while the output file looked
    # complete, because every bank had carried over.
    # ── Did a column move more than a month plausibly can? ──
    #
    # `--strict` below catches a column that comes back empty. It cannot
    # catch one that comes back full of the wrong numbers, which is what
    # happens when a site adds a column and every figure shifts one to
    # the left. Interest rates move in fractions month to month, so a
    # median absolute move above a point across a whole column is not
    # the market, it is a misread.
    #
    # Median rather than maximum: one bank genuinely repricing by two
    # points is news, not a bug, and should not fail the run.
    #
    # Deliberately not a per-bank alarm. A cross-check against the banks'
    # own pages was tried first and abandoned — see docs/bank-rates.md —
    # because a generic parser reads 10.2 off NMB's page where the
    # aggregator says 5.01, and a check that is wrong most months is a
    # check nobody reads.
    def column_moves(getter) -> list[float]:
        moves = []
        for bank in banks:
            now, was = getter(bank), getter(previous.get(bank['id'], {}))
            if isinstance(now, (int, float)) and isinstance(was, (int, float)):
                moves.append(abs(now - was))
        return moves

    for label, getter in (
        ('savings (max)', lambda b: b.get('savings', {}).get('max')),
        ('fixed (highest)', lambda b: b.get('fixed', {}).get('best')),
        ('base rate', lambda b: b.get('loans', {}).get('base')),
        ('home loan', lambda b: b.get('loans', {}).get('home')),
        ('vehicle loan', lambda b: b.get('loans', {}).get('auto')),
    ):
        moves = sorted(column_moves(getter))
        if len(moves) < 5:
            continue
        median = moves[len(moves) // 2]
        if median > 1.0:
            note(f'{label}: median move {median:.2f} points since last sheet '
                 f'— that is a misread column, not a month of rates')

    if '--strict' in sys.argv:
        floor = max(3, int(len(BANKS) * 0.75))
        thin = [
            f'{label} {len(table)}/{len(BANKS)}'
            for label, table in (
                ('savings', savings),
                ('fixed', fixed_best),
                ('base', base),
                ('home', home),
                ('auto', auto),
            )
            if len(table) < floor
        ]
        suspicious = [p for p in problems if 'misread column' in p]
        if thin or suspicious:
            if thin:
                print(f'\nSTRICT: refusing to publish — {", ".join(thin)} '
                      f'(need {floor} of {len(BANKS)})', file=sys.stderr)
            for p in suspicious:
                print(f'STRICT: refusing to publish — {p}', file=sys.stderr)
            return 1

    if problems:
        print(f'\n{len(problems)} source(s) could not be read at all:', file=sys.stderr)
        for problem in problems:
            print(f'  - {problem}', file=sys.stderr)
        print('  Their figures are last month\'s. Fix or remove them before publishing.',
              file=sys.stderr)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
