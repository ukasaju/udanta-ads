# Udanta — published ads

The live ad feed for the [Udanta](https://github.com/ukasaju/udanta) app.

**Editing `ads.json` changes what every install shows on its next launch.** No app
update, no store review. The app re-reads it at most every 15 minutes.

- `ads.json` — the feed
- `*.png` — artwork, referenced from `ads.json` by its raw URL

## Adding an ad

Append an object to `ads`. Only five fields are required:

```json
{
  "id": "unique-and-permanent",
  "advertiser": "Who is paying",
  "headline": "The line people read",
  "cta": "Button text",
  "url": "https://where-it-goes"
}
```

Optional: `body`, `media`, `active`, `startsAt`, `endsAt`, `weight` (1–10),
`lang` (`en`/`ne`, omit for both), `placements`, `screens`, `audiences`, `tint`.

## Removing one

Set `"active": false` rather than deleting it, so there is still a record of
what ran. `disabled` holds ids of creatives built into the app itself.

## Rules the app enforces

Links must be `https://`. Images must be `https://`. Anything malformed is
dropped; if the whole file is bad the app keeps serving the last good copy. So
a broken edit fails quietly — validate your JSON if a change does not appear.

Full reference: `docs/ads.md` in the app repo.

## bank-rates.json

The interest-rate sheet the Market tab reads. **Rebuilt automatically** by
`.github/workflows/bank-rates.yml`, which runs on the 1st and 16th of each
Gregorian month — Bikram Sambat months begin between the 14th and the 18th,
so twice a month avoids labelling a sheet with the wrong month's name.

Every column is scraped. Savings, fixed deposit, base rate and home loan
come back for all nineteen banks, vehicle loan and the term ladders for
most; a bank the source does not list that month keeps last month's figure
and the run says so.

Term ladders were the last manual column, on the grounds that banks bracket
tenures differently and mapping a bracket onto "1 year" is a judgement.
`/detail/fd-individual` publishes a normalised Tenure column — "9 months",
"2 years" — which makes that judgement once, consistently, for every bank.
Fractional years are refused: the page writes a `>3Y to 5Y` bracket as
"3.08 years", and that is a range's floor, not a term anybody can deposit
for.

Two guards, because the ways this fails are not the same:

- A column that returns fewer than three-quarters of the banks fails the
  run. Without it a scrape can report success while every bank quietly
  keeps last month's figure, which is what happened the first time the
  fixed-deposit column was added.
- A column whose median month-over-month move exceeds one point fails the
  run. Rates move in fractions; a whole column shifting means a site added
  a column and every figure is being read one cell out.

Either way the old sheet stays published and the app keeps showing it with
its own month on screen, which is the honest failure.

Run it by hand from the Actions tab, optionally passing a Bikram Sambat
year and month. The source is bankbyaj; see `docs/bank-rates.md` in the app
repo for why one aggregator rather than nineteen banks' own sites.
