# Apify actor selection and integration validation — 2026-09-11

## Scope

Select one LinkedIn Ads Library actor and one Meta Ads Library actor, implement
the live provider boundary, and stop safely if vault authentication is absent.
All actor discovery and documentation inspection used the project's pinned
Scrapling dependency.

## Selected actors

| Platform | Actor | Pinned build | Selection rationale |
| --- | --- | --- | --- |
| LinkedIn | `silva95gustavo/linkedin-ad-library-scraper` | `1.1.52` | Leading relevant Store result by observed adoption; documented account-owner search and destination output |
| Meta | `apify/facebook-ads-scraper` | `0.0.374` | Maintained by Apify; high adoption; documented active-status, result-limit, and detail controls |

Sources:

- [LinkedIn Ads Scraper](https://apify.com/silva95gustavo/linkedin-ad-library-scraper)
- [Facebook Ads Library Scraper](https://apify.com/apify/facebook-ads-scraper)
- [Apify API authentication](https://docs.apify.com/integrations/api)
- [Run Actor API workflow](https://docs.apify.com/api/v2)

## Guardrails

- The API token is retrieved from macOS Keychain account
  `provider-secrets`, service `gtm-signal-engine:apify-token`.
- Authentication uses an `Authorization: Bearer` header, never a URL query
  parameter.
- Actor starts are asynchronous and single-attempt so the run ID is retained
  and an ambiguous network failure cannot trigger duplicate paid execution.
- Each actor is capped at 25 paid dataset items and $0.15 total charge, with a
  180-second server-side timeout.
- Actor metadata, run start/final objects, and dataset payloads use content-hash
  filenames under the ignored run `raw/` directory.
- LinkedIn and Meta use separate provider-specific normalizers. Only records
  with an ad ID and a landing URL on the account domain or a subdomain become
  normalized ad evidence.
- Empty or unmatched results are uncertainty, not proof that the company is not
  advertising.

## Fixture validation

Fixtures reproduce the selected actors' documented shapes, including LinkedIn
`adId`, `availability`, `body`, `headline`, and `clickUrl`, plus Meta
`adArchiveID`, formatted dates, snapshot text, card destinations, and tracking
parameters. Tests cover domain attribution, false-positive exclusion, vault
failure before network access, spend caps, token non-persistence, immutable raw
artifacts, and no paid POST retry.

## Live blocker

Both authoritative commands were attempted locally. Each stopped before any
network or paid actor call because `apify-token` is not present in the configured
Keychain. The run-local `normalized/apify_collection.json` files record
`status: blocked`, `incomplete: true`, and zero normalized records. No Apify
cost was incurred.

After a scoped token is stored in Keychain, rerun:

```bash
uv run gtm-signals collect-apify-ads \
  data/runs/20260910T224631Z-52eaa2e5 dailypay.com --account-name DailyPay

uv run gtm-signals collect-apify-ads \
  data/runs/20260910T224633Z-e599a4a6 coldiq.com --account-name ColdIQ
```
