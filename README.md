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
