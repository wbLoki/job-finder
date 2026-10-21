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

## Remote job scanner (`scan.py`)

A command-line scan for remote TypeScript / React / Node roles that someone outside the US/EU can apply to. It checks:

- the public job boards (Greenhouse, Lever, Ashby) of about 110 remote-friendly companies;
- the Remotive, Remote OK, We Work Remotely and Himalayas feeds.

```
python scan.py          # only matches you haven't been shown before
python scan.py --all    # every current match
```

Double-clicking `scan.bat` does the same. Everything it keeps is in `data/` (git-ignored):

- `data/applied.txt`: companies to skip, one per line (matched as part of the company name).
- `data/scan_seen.json`: URLs of matches already shown.
- `data/scan_latest.csv`: every match from the last run, to open in a spreadsheet.

To add companies, put their board name into `GREENHOUSE`, `LEVER` or `ASHBY` at the top of the file (the part after `boards.greenhouse.io/`, `jobs.lever.co/` or `jobs.ashbyhq.com/`). The title, stack and location filters are the regexes below those lists.

It's tuned for a frontend-leaning developer with about 2 years of experience: backend-only titles are skipped, postings whose description asks for more than `MAX_YEARS` (3) years are dropped, and senior-sounding titles are kept but marked `senior`, since some of them only ask for 2 years.
