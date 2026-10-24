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

## Reading

- **Meeker, Escobar & Pascual, *Statistical Methods for Reliability Data*** (2nd ed., Wiley, 2021). Main reference: Weibull models, censoring and truncation, field data, failure prediction, Bayesian reliability. Phases 1–4.
- **McElreath, *Statistical Rethinking*** (2nd ed., CRC, 2020). Bayesian workflow, diagnostics and partial pooling; code ported to PyMC in [pymc-resources](https://github.com/pymc-devs/pymc-resources). Phases 2–3.
- **Klein & Moeschberger, *Survival Analysis: Techniques for Censored and Truncated Data*** (2nd ed., Springer, 2003). Left truncation and Kaplan–Meier risk sets. Phase 1.
- **Gelman et al., *Bayesian Data Analysis*** (3rd ed., CRC, 2013; [free PDF](https://sites.stat.columbia.edu/gelman/book/)). Hierarchical models and model checking. Phase 3.
- **Hamada, Wilson, Reese & Martz, *Bayesian Reliability*** (Springer, 2008). Bayesian methods applied to reliability. Phases 2–3.
- **Molnar, *Interpretable Machine Learning*** ([free online](https://christophm.github.io/interpretable-ml-book/)). SHAP. Phase 5.

## Data

Backblaze publishes the data free of charge. Per their terms: cite Backblaze as the source, accept that you are solely responsible for how you use the data, and do not sell the data itself. Raw data is not committed to this repo.
