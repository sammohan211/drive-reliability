# Plan

Started 2026-10-24. Each phase ends with something that runs and is tested.

## Phase 0: Data ingestion and audit

- [x] Downloader (`bb-download`): yearly archives for 2013–2015, quarterly from 2016; resumes interrupted files, retries network errors, checks size and zip CRCs
- [x] Window: **full history, 2013Q2–2026Q2** (45 archives, ~35 GB zipped). Older models add failures, late-life wear-out data and a longer backtest; left truncation is still handled for drives already aged at first sighting
- [x] Download the full history into `data/raw/` (zips kept as the raw copy)
- [x] Convert to Parquet (`bb-convert`), one archive at a time: extract CSVs to a temp folder, write one Parquet file per archive with all columns, delete the CSVs. Peak temp use ~13 GB; expected total on disk ~50–65 GB (zips + Parquet)
- [x] Handle column drift: SMART columns and fields like `datacenter` were added over time. Each Parquet file keeps its own columns; DuckDB aligns them by name (`union_by_name`). Checked by `bb-audit`: 197 columns, no gaps, renames or type conflicts, NULL before a column first appears. Location fields (`datacenter`, `cluster_id`, `pod_id`, `pod_slot_num`, `vault_id`) and `is_legacy_format` only start in Q2/Q3 2023
- [ ] Build a **drive lifecycle table**, one row per serial number: model, capacity, first/last seen, entry age (SMART 9, power-on hours, at first sighting), failed flag, age at failure or at censoring
- [ ] Data-quality audit. Known so far: `2018-02-25.csv` and `2019-06-17.csv` were re-saved in Excel before publication (M/D/YY dates; `capacity_bytes` on 2018-02-25 and some SMART raw counters, mostly smart_242, rounded to 6 significant digits; 9 failures recorded on those days, kept). The 2019-06-17 file also holds one row dated 2019-06-15: the failure record of `ZCH0CJC3` (last seen 2019-06-16, never after), with power-on hours that don't match its other days. Treat it as failing on 2019-06-17. Take per-drive capacity from undamaged days. Also check: serials that disappear without failing, failures followed by reappearance, power-on-hours resets or implausible values, drive models with too few drives
- **Gate:** list of drive models with enough data (e.g. ≥ 1,000 drives and ≥ 20 failures). Others enter only through pooling

## Phase 1: Baselines

What the Bayesian model has to beat.

- [ ] Annualized failure rate per drive model, Backblaze's own formula (failures / drive-days × 365), to reproduce their published numbers as a sanity check
- [ ] Kaplan–Meier curves per drive model, **with left truncation** (risk set by age, not calendar time)
- [ ] Frequentist Weibull MLE with censoring + truncation (SciPy), compared against a naive fit that ignores truncation, to show the bias in numbers
- [ ] Naive forecast: next quarter's failures = trailing AFR × drives in service

## Phase 2: Single-model Bayesian Weibull

- [ ] PyMC model for one high-volume drive model: Weibull likelihood with right censoring and left truncation
- [ ] **Parameter-recovery test** on simulated fleets (known β, η, entry ages, censoring): 90% intervals contain the truth. This is the pytest that keeps the model honest
- [ ] Prior predictive check: priors on β and on 1-year failure probability give plausible fleets
- [ ] Diagnostics: R-hat < 1.01, ESS > 400, no divergences; posterior predictive check vs. Kaplan–Meier
- [ ] Compare with the Phase 1 MLE

## Phase 3: Hierarchical model and backtest

- [ ] All eligible drive models, partially pooled by manufacturer (log β and logit 1-year failure probability)
- [ ] **Temporal backtest:** fit on data through quarter T, forecast failures in T+1…T+4, roll forward. Report MAE vs. the naive baseline and interval coverage (80% intervals should cover ~80%)
- [ ] Shrinkage plot: per-model estimates before and after pooling

## Phase 4: Decision outputs

- [ ] 12-month failure forecast for the current fleet, P50 / P90
- [ ] Replacement budget and spares count as a distribution (assumed unit cost per capacity)
- [ ] Pairwise P(model A worse than model B) at matched age; a "which drive to buy" table
- [ ] Write-up: results with plots, in plain language

## Phase 5: Drive layer (SMART classifier)

- [ ] Labels: fails within the next 30 days. Temporal split (train on older quarters, test on the latest)
- [ ] Features: SMART raw and normalized values, deltas over 7/30 days, age, model, capacity
- [ ] LightGBM with imbalance handling; PR-AUC, recall at a fixed false-alarm rate, calibration
- [ ] Cost-based threshold: cost of a surprise failure vs. cost of a needless swap
- [ ] SHAP: which SMART attributes drive risk

## Phase 6: Serve and deploy

- [ ] FastAPI: `/fleet/forecast` (from saved posterior) and `/drive/risk` (classifier)
- [ ] Docker image, tested in CI
- [ ] Deploy to Azure (Container Apps or an Azure ML managed online endpoint)
- [ ] Monitoring: each new quarter, log forecast vs. actual failures and feature drift; flag when interval coverage drifts

## Phase 7: Polish

- [ ] README results section with the key plots and numbers
- [ ] Short method note: censoring, truncation, pooling, what the model does not capture (failure modes, datacenter environment)

## Engineering conventions

- Data in `data/` (git-ignored); every derived table is rebuilt from scripts
- Modeling code is pure functions in `src/drive_reliability/`, tested on synthetic data; notebooks for exploration only
- Fixed random seeds; save fitted posteriors (`.nc`) so every reported number traces to a fit
- Dependencies are added per phase (`pymc arviz` in Phase 2, `lightgbm shap` in Phase 5, `fastapi` in Phase 6)
