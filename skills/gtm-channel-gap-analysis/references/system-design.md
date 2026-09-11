# System design

Separate collection, normalization, extraction, evidence, aggregation, scoring, and activation.

Provider adapters should expose narrow operations such as `crawl_domain`, `find_ads`, `enrich_account`, and `search_pages`; they must return normalized records. Persist raw responses for replay and debugging, but never require core classifiers to understand vendor schemas.

Use canonical URLs for identity while retaining observed ad/campaign URLs. Deduplicate pages by canonical URL and content hash. Model every account analysis as a versioned, resumable run. Failed or unavailable providers produce explicit incomplete states—not negative evidence.

Use configuration for crawl budgets, freshness windows, score weights, and qualification thresholds. Record provider cost and stop when configured budgets are reached.
