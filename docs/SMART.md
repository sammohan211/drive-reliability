# SMART reference

What SMART is, how Backblaze records it, and what to watch out for when using it as model input (Phase 1 entry age, Phase 5 classifier).

## What SMART is

**SMART** (Self-Monitoring, Analysis and Reporting Technology) is firmware on a hard drive or SSD that tracks internal health counters and reports them to the host. It came out of IBM and Compaq work in the 1990s and is part of the ATA standard. The standard defines the reporting mechanism, not the attributes: which attributes a drive reports, what they mean and what units they use is up to each vendor, and sometimes each model or firmware version.

Each attribute has a numeric **ID** (1–255) and several fields:

| Field | Meaning | In Backblaze data |
|---|---|---|
| **Raw value** | The underlying counter or measurement (sector count, hours, degrees C). Up to 48 bits, vendor-defined encoding. | `smart_<id>_raw` |
| **Normalized value** | Vendor-scaled health score, usually 1–253, **higher is better**. Fresh drives often start at 100, 200 or 253. | `smart_<id>_normalized` |
| **Worst** | Lowest normalized value ever recorded. | not published |
| **Threshold** | Vendor-set floor. If normalized ≤ threshold on a pre-fail attribute, the drive declares SMART failure ("predicted failure"). | not published |
| **Flags** | Pre-fail vs. old-age, online vs. offline collection, etc. | not published |

Because worst, threshold and flags are missing, the drive's own pass/fail verdict cannot be reconstructed from the dataset. In practice that verdict is a weak signal anyway: vendors set thresholds conservatively to avoid warranty returns, so most failing drives never trip one.

## How Backblaze records it

- One row per drive per day: `date`, `serial_number`, `model`, `capacity_bytes`, `failure`, location fields (from 2023), then a raw/normalized pair for each SMART ID.
- The column set grows over time as new drive models report new IDs (97 IDs by Q4 2025; see `bb-audit`). A column is NULL before it first appears, and NULL for any drive that doesn't report that ID. **NULL means "not reported", not zero.**
- `failure = 1` on a drive's last day means Backblaze removed it as failed (it stopped working or was about to). The drive then leaves the data. Drives that leave with `failure = 0` were retired or migrated: censored, not failed.
- The fleet is mostly HDDs; SSDs (boot drives) appear from 2018 and report different attributes.

## Key attributes

### Backblaze's five failure predictors

Backblaze has repeatedly found that these five raw counters, all of which should stay at zero on a healthy drive, are the most useful early-warning signals. A non-zero value on any of them raises failure risk sharply, but plenty of failed drives show none of them, and some healthy drives run for years with small non-zero counts.

| ID | Name | Raw value | Notes |
|---|---|---|---|
| **5** | Reallocated Sectors Count | Sectors remapped to spare area after read/write errors | The classic one. Growth over time matters more than the level. |
| **187** | Reported Uncorrectable Errors | Errors ECC could not recover | Mostly Seagate. |
| **188** | Command Timeout | Aborted operations due to timeout | Seagate packs three 16-bit counters into the raw value; decode or use with care. Can reflect cabling/power, not only the drive. |
| **197** | Current Pending Sector Count | Unstable sectors waiting to be remapped | Can go back down when a sector is rewritten successfully or reallocated (moves into 5). |
| **198** | Offline Uncorrectable | Sectors that failed an offline scan | Often tracks 197 closely. |

### Age, usage and environment

| ID | Name | Raw value | Notes |
|---|---|---|---|
| **9** | Power-On Hours | Hours powered on | Used for **entry age** (left truncation). Some vendors/models count minutes or seconds, or pack extra bits; check for resets, jumps and implausible values per model. |
| **12** | Power Cycle Count | Number of power-on events | Low in a datacenter; spikes can indicate a troubled chassis. |
| **4** | Start/Stop Count | Spindle start/stop cycles | |
| **193** | Load/Unload Cycle Count | Head parking cycles | Wear indicator; vendor-rated limits (often 300k–600k). |
| **194** | Temperature | Degrees C | Raw often packs current temp in the low byte and min/max in higher bytes. Mask with `raw & 0xFF`. |
| **190** | Airflow Temperature | Degrees C (Seagate, WDC) | Normalized is often `100 − temp`. |
| **240** | Head Flying Hours | Hours heads spent over platters | Seagate may pack extra fields. |
| **241** / **242** | Total LBAs Written / Read | Logical blocks transferred | Usually 512-byte LBAs on HDDs; SSDs may use other units (GiB, 32 MiB). Some raw values were rounded in the Excel-damaged files (see PLAN). |

### Error-rate and mechanical attributes

| ID | Name | Notes |
|---|---|---|
| **1** | Raw Read Error Rate | Seagate's raw value is a packed 48-bit field (high 16 bits: errors, low 32 bits: operations), so it looks like large random numbers. Don't use the Seagate raw value as a plain count. |
| **7** | Seek Error Rate | Same Seagate packing as ID 1. |
| **195** | Hardware ECC Recovered | Same Seagate packing; vendor-specific elsewhere. |
| **3** | Spin-Up Time | Milliseconds or vendor units. |
| **10** | Spin Retry Count | Should be 0; non-zero suggests motor/bearing trouble. |
| **184** | End-to-End Error | Parity mismatch in the drive's data path. Should be 0. |
| **189** | High Fly Writes | Head flew outside normal height during a write. |
| **191** | G-Sense Error Rate | Shock/vibration events. |
| **196** | Reallocation Event Count | Number of remap operations (vs. sectors remapped in 5). |
| **199** | UDMA CRC Error Count | Interface/cable errors. Usually points at the cable or backplane, not the drive. |

### SSD attributes

SSDs report a largely different, even more vendor-specific set: wear leveling, percentage of rated life used, program/erase fail counts, spare blocks (e.g. 173, 177, 202, 231, 233, 235). Treat SSD rows as a separate population or drop them; the HDD failure model doesn't transfer.

## Caveats for modeling

1. **Semantics are per vendor, sometimes per model.** The same ID can mean different things or use different encodings across manufacturers. Features should be computed and compared within model (or at least within manufacturer), and the model should see `model`/manufacturer.
2. **Normalized values are not comparable across vendors.** Start points (100, 200, 253) and scaling differ. Raw values of the zero-is-healthy counters (5, 187, 188, 197, 198) are the most portable signals.
3. **Missing ≠ zero.** Encode "not reported" separately (or let a gradient-boosted model handle NULLs natively) rather than filling with 0.
4. **Trajectories beat levels.** A jump in ID 5 or 197 over the last 7–30 days is more informative than its absolute value. Hence the delta features in Phase 5.
5. **Leakage near the failure date.** On the last few days a failing drive may show extreme values, or Backblaze may pull the drive *because* of its SMART values. A classifier predicting "fails within 30 days" must use a temporal split and should be checked for how much of its skill comes from the final days.
6. **Many failures are silent.** Research (Google, Pinheiro et al. 2007; Backblaze's own analyses) finds a large share of failed drives, on the order of a third or more, show no warning in the main counters. SMART-based prediction has a ceiling; mechanical and electronic failures often give no notice.
7. **Data damage.** Some raw counters (mostly `smart_242`) were rounded to 6 significant figures in the 2018-02-25 and 2019-06-17 files. See [PLAN.md](PLAN.md).

## Further reading

- Backblaze blog: "What SMART Stats Tell Us About Hard Drives" (2016) and "Hard Drive SMART Stats" posts; the quarterly Drive Stats reports.
- Pinheiro, Weber & Barroso, "Failure Trends in a Large Disk Drive Population", FAST 2007.
- [smartmontools](https://www.smartmontools.org/) `drivedb.h`: per-model attribute names and raw-value encodings; the best practical reference for vendor quirks.
- Wikipedia, "Self-Monitoring, Analysis and Reporting Technology": attribute table with vendor notes.
