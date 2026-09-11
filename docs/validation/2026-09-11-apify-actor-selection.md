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
- LinkedIn and Meta use separate provider-specific normalizers. A record needs
  an ad ID and landing URL, plus either an exact normalized advertiser-name
  match or a landing destination on the account domain. This admits attributable
  first-party short links while rejecting similarly named advertisers.
- Meta uses exact-phrase account search. The normalizer accepts both direct ad
  rows and the actor's zero-result envelope.
- Corrective runs can target one platform while retaining the other platform's
  evidence and run metadata. Saved datasets can be replayed without starting a
  paid actor.
- Prefer a verified LinkedIn company ID when available. Name search can return a
  completed zero-result dataset even when the company-ID Ad Library page has
  active ads.
- An attributable ad remains ad-activity evidence when the actor omits its click
  URL. Store a null destination and exclude it from destination/tracking metrics
  instead of discarding the ad.
- Empty or unmatched results are uncertainty, not proof that the company is not
  advertising.

## Fixture validation

Fixtures reproduce the selected actors' documented shapes, including LinkedIn
`adId`, `availability`, `body`, `headline`, and `clickUrl`, plus Meta
`adArchiveID`, formatted dates, snapshot text, card destinations, and tracking
parameters. Tests cover domain attribution, false-positive exclusion, vault
failure before network access, spend caps, token non-persistence, immutable raw
artifacts, and no paid POST retry.

## Live validation

The token was stored in the configured Keychain. Sandboxed processes could not
initially see the user's Keychain item; running the scoped collector with host
Keychain access resolved the blocker without copying the token into a file or
command argument.

The first DailyPay canary returned 25 LinkedIn rows and 25 Meta rows. Four
LinkedIn ads were attributable to the exact `DailyPay` advertiser, but their
destinations used `bit.ly` or LinkedIn, exposing a false negative in the
domain-only attribution rule. The original unordered Meta keyword search
returned unrelated advertisers, all of which the attribution gate rejected.
Replaying the immutable datasets after adding exact advertiser-name attribution
recovered the four LinkedIn records without another paid call.

The v2 exact-phrase Meta canary returned 25 candidate rows and four attributable
DailyPay ads; two contain destinations. Replaying the LinkedIn dataset with
optional destinations retained all 25 exact-advertiser rows, four of which
contain destinations. The final DailyPay profile therefore contains 29 ads: 25
LinkedIn and four Meta. The original LinkedIn run reported $0.09205 usage, the
discarded broad Meta result reported $0.058, and the corrected Meta run reported
$0.00: $0.15005 total DailyPay validation usage. With 442 technology detections
and the saved website assets, retargeting readiness is 80/100 at 0.675
confidence and programmatic readiness is 80/100 at 0.72 confidence. Both gaps
remain null/unknown.

ColdIQ's initial name query returned zero LinkedIn candidates and Meta returned
a completed zero-result envelope. The user then supplied its authoritative
LinkedIn Ad Library URL with company ID `65826193`, which visibly contradicted
the name-query result. A LinkedIn-only company-ID run returned 25 records, all
with advertiser `ColdIQ`; 13 contain destinations. The initial name run reported
$0.00005, the company-ID run $0.08805, and Meta $0.00: $0.08810 total ColdIQ
validation usage. ColdIQ retargeting readiness is now 80/100 at 0.675 confidence
and programmatic readiness is 70/100 at 0.72, both provisional-pass. Both gap
components remain null/unknown.

The complete deterministic suite passes 116/116 tests, and the source and wheel
artifacts build successfully with both v1 and v2 Apify configurations packaged.
