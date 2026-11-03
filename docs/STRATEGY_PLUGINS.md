# Data and strategy contracts

## Import a native strategy

Strategy Lab can export/import a JSON configuration conforming to `Strategy` in `backend/models.py`. Unknown fields are rejected. Saving produces a new version, retaining the prior version for reproducibility. Supported families are `longshot` and `model_edge`.

```json
{
  "name": "Low-price NO research",
  "family": "longshot",
  "side": "no",
  "category": "All",
  "min_probability": 0.02,
  "max_probability": 0.15,
  "min_edge": 0.04,
  "min_volume": 10,
  "risk_fraction": 0.01,
  "event_cap": 0.05,
  "total_cap": 0.30,
  "sizing": "fixed_fraction"
}
```

The longshot family selects a YES-ask band; it does not claim that every selected contract is mispriced. `min_edge` is used by the model-edge family, which requires independent point-in-time probabilities. Live paper deployment currently supports only the longshot family.

## Import historical observations

Data & Intelligence accepts JSON rows, or a JSON object containing `rows`. Supply a dataset name, provenance and an accurate synthetic/non-synthetic declaration. A declaration of historical data is not independent verification. An upload must contain 2 to 50,000 observations with at least two observations per traded contract. The simulator will not enter on the first observation.

```json
[
  {
    "ticker": "EXAMPLE-1",
    "event_id": "EXAMPLE-EVENT",
    "category": "Weather",
    "observed_at": "2025-01-01T10:00:00Z",
    "available_at": "2025-01-01T10:00:05Z",
    "yes_bid": 0.09,
    "yes_ask": 0.11,
    "volume": 1000,
    "outcome": "no",
    "settled_at": "2025-01-02T12:00:00Z",
    "quote_size": 20,
    "model_probability": 0.04,
    "model_asof": "2025-01-01T09:59:00Z"
  }
]
```

The single row above is a schema illustration, not a sufficient dataset. Add subsequent observations with distinct timestamps. Prices/probabilities use dollars/fractions, not cents/percentages. All timestamps require a timezone. Bid cannot exceed ask. Observation time must precede availability, which must precede settlement. Outcomes and settlement metadata must remain consistent within each ticker. Duplicate ticker/availability pairs are rejected. `quote_size` is optional; when missing the simulator uses an explicitly modeled bar-volume participation cap. `model_probability` and `model_asof` are either both present or both absent. A model timestamp later than information availability is rejected.

This interface permits an independently developed model to supply historical probability estimates without giving it credentials or execution authority. Verify that model training itself did not use future information; timestamp checks cannot prove that.

## GitHub integrations

Integrations accepts `owner/repository`, reads metadata and pins the most recent commit SHA for review. It reports the declared license and archive status. It does not download dependencies, run repository code or certify a strategy. A private repository may require the optional read-only server token.

Before an external strategy becomes executable, review license and dependency rights, source integrity, network behavior, tests, data chronology and output compatibility. Do not give an imported repository exchange secrets. The initial release provides the data/configuration integration boundary, not an arbitrary-code plugin marketplace.

No earlier suggested repository has been independently endorsed or incorporated by this release.
