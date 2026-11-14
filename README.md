# No-Receipt Class Action Finder

`index.html` shows open class action settlements you can claim without a receipt.
`settlements.json` is the data. A GitHub Action rebuilds it every 4 hours with `scripts/scrape.py`.

## Setup (about 5 minutes)
1. Create a new GitHub repository and upload everything in this folder (including the hidden `.github` folder).
2. Repo Settings > Pages > Build from branch `main`, folder `/ (root)`. Your site appears at `https://<you>.github.io/<repo>/`.
3. Repo Settings > Actions > General > Workflow permissions > "Read and write permissions".
4. Actions tab > "Update settlements" > Run workflow. Check the log: it should say how many pages it found and kept.

## How it works
- `data_seed.json` holds hand-curated entries (edit it any time).
- `scrape.py` reads the OpenClassActions no-proof list, opens each settlement page, keeps ones whose
  "Proof Required" starts with "No", drops expired deadlines, and merges with the seed.
- If the list page can't be fetched or has no links, the run fails and `settlements.json` is left alone.
  GitHub emails you about failed runs.

## Known limits
- The scraper was written without being able to test it against the live site. Read the first run's log.
  If it keeps 0 items, the site's layout differs from what the script expects; the label names in
  `parse_detail()` are the place to adjust.
- It reads four sources (OpenClassActions, ClaimDepot, ClaimWatch, FileYourClaim). ClassAction.org and Top Class Actions are link-only: one loads its data with JavaScript, the other blocks bots. Top Class Actions blocks automated requests (HTTP 403), so it stays link-only. Each is isolated, so one breaking doesn't stop the others. The log prints `[Source] kept N` for each; a source stuck at 0 needs its parser adjusted. To add a site, write another `src_*` function and add it to `SOURCES`.
- Settlements that only pay people on a notice list (data breaches, wage cases, etc.) are filtered out by `NOTICE_ONLY`; tweak that pattern if it's too strict or too loose.
- Check each site's terms before scraping, keep the 1-second delay, and always confirm details on the
  official settlement site before filing.
