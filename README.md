# Drive Reliability

Fleet reliability modeling and failure forecasting on [Backblaze hard drive data](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data): about 300k drives, daily SMART snapshots, real failures.

**The question:** for a fleet of hard drives, how many will fail next year, which drive models are wearing out, and which model should you buy? Answered with uncertainty, not point estimates.

## Two layers

1. **Fleet layer (statistical inference).** A hierarchical Bayesian Weibull model of time to failure per drive model, pooled by manufacturer. It handles right censoring (drives still running) and left truncation (drives that enter the data already aged). Outputs:
   - failure regime per drive model (shape β: infant mortality, random, or wear-out), with probabilities
   - failures forecast for the next 12 months, with intervals
   - replacement budget as P50 / P90
   - head-to-head comparisons: P(model A fails sooner than model B)
2. **Drive layer (ML).** A gradient-boosted classifier on SMART attributes predicting "fails within 30 days". Heavily imbalanced, with a temporal split and a cost-based threshold. Served as an API on Azure and monitored for drift as new quarters arrive.

## Status

Phase 0: data ingestion. See [docs/PLAN.md](docs/PLAN.md).

## Setup

```bash
uv sync
uv run bb-download 2013Q2 2026Q2   # full history, ~35 GB of zips into data/raw/
uv run bb-convert                  # one Parquet file per archive into data/parquet/
uv run pytest
```

## Data

Backblaze publishes the data free of charge. Per their terms: cite Backblaze as the source, accept that you are solely responsible for how you use the data, and do not sell the data itself. Raw data is not committed to this repo.
