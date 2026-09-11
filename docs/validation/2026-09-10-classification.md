# Page and form classification validation — 2026-09-10

## Scope

This is a rule-development sample, not a precision benchmark. It validates the
first deterministic page-family, form-purpose, and gating rules against freshly
collected public pages from DailyPay and ColdIQ.

| Account | Pages | Relevant composition |
| --- | ---: | --- |
| DailyPay | 65 | Homepage, 49 case studies, 14 ebooks, 1 white paper |
| ColdIQ | 50 | Homepage, 16 case studies, 27 guides, 1 webinar, 4 tool pages, 1 use-case page |

## Confirmed behaviors

- A blog page mentioning reports and webinars in repeated navigation/footer copy
  is not promoted to a substantial asset.
- ColdIQ product names containing “guide,” “report,” or “webinar” remain tool
  pages when they live under `/tools/`.
- ColdIQ's repeated GTM playbook form is classified as asset access, but it does
  not make the case study containing it gated.
- ColdIQ guide delivery forms are distinct from the repeated newsletter form;
  `unsubscribe` no longer creates a false `subscribe` match.
- DailyPay ebook pages with both a Marketo asset form and a direct PDF link are
  classified as optional gates.
- DailyPay case studies with substantial visible content are classified as fully
  ungated even when unrelated forms occur elsewhere in the page template.
- ColdIQ's “Webinar Replay” page is fully ungated without requiring a form.

## Latest output

### DailyPay

- Assets: 49 case studies, 14 ebooks, 1 white paper.
- Gating: 51 fully ungated assets and 13 optional gates.
- Forms: 65 site-search forms, 13 asset-access forms, 1 newsletter form, and 4
  unresolved forms.
- Page-family unknowns: 0 in this targeted sample.

### ColdIQ

- Assets: 16 case studies, 27 guides, 1 webinar.
- Gating after replay handling: 17 fully ungated, 26 summary-ungated/full-asset-
  gated, and 1 unknown (the guide index).
- Forms: 42 asset-access forms and 50 newsletter forms.
- Page-family and form-purpose unknowns: 0 in this targeted sample.

## Remaining limitations

- The sample was selected through deterministic crawl priority and is not a
  randomized labeled set; it cannot establish the target precision percentages.
- Repeated-template detection is inferred from rule context rather than a stored
  cross-page DOM/template model.
- Some JavaScript-injected fields are not present in raw server HTML. A form may
  be classified from its container and surrounding copy without knowing the
  final rendered field count.
- Conversion CTA extraction still lacks anchor-text-to-destination pairing and
  is not validated in this increment.
- Publication date extraction and substantial-content quality remain future
  milestones.
