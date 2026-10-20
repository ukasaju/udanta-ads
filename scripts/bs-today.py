#!/usr/bin/env python3
"""
Today's Bikram Sambat year and month, as GitHub Actions outputs.

Exists so the scheduled rates job does not need the month typed in.
The conversion table lives in TypeScript (`src/lib/nepaliDate.ts`) and
is not importable from Python, so this derives the month from the
Gregorian date instead: a BS month starts somewhere between the 14th
and the 18th, so before the 14th we are still in the month that began
last Gregorian month.

That is an approximation and it is allowed to be. The month only has
to be right to within a fortnight for the job to label the sheet
correctly, and `workflow_dispatch` takes an explicit year and month
for the times it matters.
"""
import datetime as dt

# BS month N begins in Gregorian month (N + 3), wrapping at 12.
# Baisakh (1) begins mid-April (4), Kartik (7) begins mid-October (10).
today = dt.date.today()
g_month = today.month if today.day >= 14 else (today.month - 1 or 12)
bs_month = (g_month - 3 - 1) % 12 + 1
# The BS year rolls over at Baisakh, which is mid-April.
bs_year = today.year + 57 if (today.month, today.day) >= (4, 14) else today.year + 56

print(f'year={bs_year}')
print(f'month={bs_month}')
