# Capability-aware Research and Trade Investigation

## Problem this stage addresses

The initial research engine treated all questions as price calibration and a
generic buy-YES/buy-NO simulation. It could produce mathematical results that
had no relationship to the user's actual request.

This stage preserves **what the user actually asked**, selects different
research capabilities based on the task, and independently checks whether
the necessary evidence was acquired.

It is an extension of the market-agnostic research-first branch. NFL player
props and other examples are regression scenarios, NOT the architecture's
default use case.

## Supported request types

The request parser classifies:

- **Market investigation:** discover current relevant market series and
  attempt genuine historical pricing research, without claiming universal
  coverage or independent probability forecasts.
- **Comparative historical study:** identify expressly requested categories
  and market types, allocate retrieval across them, run the same baseline
  rules, and refuse unsupported rankings when one group lacks observations.
- **Event analysis:** verify an exact exchange event or use a supported
  independent event schedule before examining related contracts.
- **Multi-leg trade construction:** preserve event/date, requested leg count,
  player-prop constraints, recent-game lookback and target combined
  probability. Use a dedicated evidence workflow, not a generic backtest.

The first task-specific external schedule / game-log adapter supports
**dated NFL games** through public ESPN site endpoints (unofficial,
provider subject to change). Other markets use Kalshi's event/series
metadata where they can be verified. The adapters are extensible but
unconnected domains cannot be claimed as verified.

## Preserved requirements

Typed research plans record, where applicable:

- Exact number of requested legs
- Market type restrictions
- Exact contract identifier
- Event date or weekday resolved relative to the request date
- Requested recent-game lookback
- Target joint probability band
- Named comparison groups
- Data provenance and the numerical experiment

The parser preserves explicit constraints even if optional model assistance
would otherwise propose an unrelated or easier analysis. Later explicit
constraints in chat can supersede earlier values without silently deleting
other requirements.

## Trade assembly

For a dated supported sports event, the workflow:

1. Resolves the scheduled game from an independently retrieved sports
   scoreboard. The event ID, date, and teams come from provider records,
   not an LLM assertion.
2. Searches relevant live Kalshi series and contracts within a bounded
   date window. Missing results are recorded as partial coverage.
3. Retrieves the linked Kalshi event and checks relationship evidence.
   Market/event relationships that are only inferred from a verified
   player and date are marked **provisional**.
4. Uses actual completed team-game IDs preceding kickoff and retrieved
   individual player boxscore fields, respecting the requested lookback.
5. Recognizes supported player-prop conditions using explicit numerical
   strike and direction semantics (over/under/inclusive). Ambiguous
   conditions are rejected instead of guessed.
6. Where enough verified statistics exist, constructs a **provisional
   research-only leg structure**. This is NOT an endorsed or executable
   multi-leg order.
7. Displays observed recent-game frequencies and optional mathematical
   independence / Frechet *scenarios*, never pretending they are
   calibrated probabilities for the upcoming game.
8. Reports whether the joint probability, target band, actual combo
   quotation and exchange execution requirements remain unmet.

**No native Kalshi RFQ is requested**. The deprecated multivariate lookup
endpoint is not used. There is no real-money order submission.

## Completion contract

Each request has individually tracked requirements:

- verified: source-grounded evidence exists and satisfies the criterion
- partial: some relevant facts exist but the criterion cannot be certified
- blocked: required evidence or a supported capability is missing

A mathematically valid unrelated backtest cannot fulfill a request for
a four-leg combination.

For a trade request the full task remains **incomplete** unless the
event, contracts, recent game evidence, individual probabilities, joint
distribution, target range, and execution availability have actually been
verified.

The UI shows these checks before any purported conclusion and does
not display generic simulation returns as a substitute for a trade.

Historical comparison requests can be labeled descriptive only when
every explicitly requested comparison group has enough distinct event
observations under the same rules and the results are reproducible.
Descriptive historical returns are not realized fills or a proven
future edge.

## Data trust and statistical limits

- Kalshi metadata identifies actual listed contracts; it does not
  independently verify a sporting event's result or probability.
- Current web search provides only contextual evidence and must not
  be inserted retrospectively into a historical strategy.
- A sample of seven games is not enough to establish calibrated
  future outcomes, especially correlated multi-leg combinations.
- Historical quote candles do not prove fill quantity or execution.
- Cross-market series discovery is bounded and incomplete by design.
- The ESPN adapter is unofficial and requires live compatibility tests.
- No live key permission, even read/write, enables production orders
  in this codebase.

## API and user interface

The existing Explore, Research and Trade navigation remains.

The background research API uses the same job endpoint. The returned
report now identifies a task type and includes a completion checklist.
Trade requests show actual verified event information, player game-log
coverage, exchange-linked contract candidates, provisional leg
structures, and explicitly unavailable forecasts/quotes.

Copilot clarifications retain the session context for requests
missing necessary details. Users may revise a completed trade request
without losing its other explicit constraints.

## Tests

- tests/test_intent_and_trade_workflow.py covers extraction of
  dates, leg counts, probability ranges, requested lookbacks,
  sports event verification, player statistic parsing, incomplete
  probability gates and source-grounded provisional trade structure.
- tests/test_desk_core.py covers market-neutral historical comparisons
  and the existing automatic data collector.
- tests/browser_desk.py ensures an incomplete combo report
  **never appears as a generic backtest**.
- tests/external_smoke.py makes only read-only public requests to
  Kalshi and the sports schedule provider. This CI step is nonblocking
  because network access and unofficial provider schemas may change.

## Outstanding engineering and provider dependencies

A universal trading and prediction engine requires further work.
Specifically absent are:

1. Calibrated joint probability and correlation models for every
   supported outcome and sport.
2. Full officially supported native Kalshi combo RFQ quotation and
   execution, with separate live authorizations and safeguards.
3. Licensed historical player/team and other event datasets
   for all market domains, with provider-specific schema monitoring.
4. Comprehensive resuming historical backfill, market relationship
   graphs, and historical order-book execution fidelity.
5. Arbitrary third-party model adapters with independent validation.

These gaps must never be concealed by LLM-generated probabilities or
pretend progress. This branch is for test and review, and has not been
deployed to the user's live Railway environment.
