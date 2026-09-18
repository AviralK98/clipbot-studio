# Cost planning

This is an illustrative scenario, not a vendor quote. Source minutes, output yield, model and API contract determine spend. Retail subscriptions may not include API access. Confirm contracts at [Vizard pricing](https://docs.vizard.ai/docs/pricing) and [Opus API](https://www.opus.pro/api).

Assumptions in USD: thirty days/month; eight publishable clips per thirty-minute source; both engines always run; assumed $0.10/source minute/engine; $0.03 AI allowance per published clip; $25 hosting and $5 storage. These assumed rates are NOT verified vendor prices. The scenario excludes tax, bandwidth, API minimums and additional retries/model multipliers.

| Volume | Clips/month | Source minutes/engine | Both engines | AI allowance | Hosting/storage | Scenario total |
|---|---:|---:|---:|---:|---:|---:|
| 3/day | 90 | 337.5 | $67.50 | $2.70 | $30 | $100.20 |
| 10/day | 300 | 1125 | $225.00 | $9.00 | $30 | $264.00 |
| 30/day | 900 | 3375 | $675.00 | $27.00 | $30 | $732.00 |

Formula: published clips / yield × source duration × total engine minute rate + AI + infrastructure. Halving usable yield doubles source-engine cost. Learned single-engine routing may reduce usage after initial comparison.

The ledger records source-minute/credit reservations and AI token counts. VIZARD_COST_PER_CREDIT and OPUS_COST_PER_CREDIT default to zero, meaning unpriced, not free. AI request reservations use configured conservative rates and do not equal invoices. Use actual provider billing for reconciliation. Configure MAX_SOURCE_MINUTES_PER_DAY, MAX_CLIPS_PER_DAY, MAX_VIZARD_CREDITS_PER_DAY, MAX_OPUS_CREDITS_PER_DAY and MAX_AI_COST_PER_DAY before live testing. Provider-level spending limits should complement estimates.
