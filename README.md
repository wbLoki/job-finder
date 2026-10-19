# Job Finder

A local web app that searches **Welcome to the Jungle** (~90k jobs, incl. many company career pages that Google/LinkedIn/Indeed miss) and **Working Nomads** (~5k remote jobs) in one place.

## Run

Requires Python 3.9+ (no packages to install).

```
python server.py
```

It opens http://localhost:8765 in your browser. On Windows you can also double-click `start.bat`. Stop it with Ctrl+C.

Options: `python server.py --no-browser`, or set `PORT=9000` to change the port.

## Filters

| Filter | Welcome to the Jungle | Working Nomads |
|---|---|---|
| Keywords (titles only, or titles + descriptions/tags) | ✓ | ✓ |
| Country / city | ✓ | "Same country" matches jobs open to that country, plus "work from anywhere" jobs if ticked |
| My experience (max years) | uses the posting's minimum years | Entry ≈ 0, Mid ≈ 2, Senior ≈ 5 years |
| Job category | WTTJ categories | WN categories |
| Contract | ✓ | full-time / part-time / freelance |
| Work mode (remote / hybrid / on-site) | ✓ | remote only, so it's hidden when you ask for non-remote |
| Posted within, language | ✓ (language: WTTJ only) | ✓ (posted within) |

Filters, saved (★) jobs and the "already opened" list are kept in your browser's local storage.

## Seen (👁) and New

The app remembers one date per source: the publish time of the **newest job any of your searches returned**. When you open the app, it takes that date from your last visit, and every listing published at or before it shows 👁; newer ones show **New** (the header counts them). Your searches during this visit move the date forward for next time. A search only counts after it's been on screen for 3 seconds, so half-typed keywords don't.

- "Hide seen jobs (👁)" in the sidebar shows only listings newer than the mark (exact, filtered on the server).
- "Clear seen history" starts over.
- Stored in `data/seen.json`: just two timestamps, e.g. `{"wttj": 1792231321, "wn": 1792321531}`.
- Since it compares dates, not specific jobs, older listings under a filter you've never searched before also show as seen.

## How it gets the data

- **WTTJ**: queries the same public Algolia search index the WTTJ website uses (credentials are read from `welcometothejungle.com/api/env` at startup, the same way your browser gets them).
- **Working Nomads**: downloads their public job feed once (read-only) and refreshes it every 30 minutes; filtering happens locally.

Both are unofficial: if either site changes its internals, that source will show an error in the app while the other keeps working.
