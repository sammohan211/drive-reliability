# Hard drive basics

Just enough about how a hard drive works to make sense of SMART data and failure patterns. For the SMART attributes themselves, see [SMART.md](SMART.md).

## The parts that matter

- **Platters.** Spinning metal disks (typically 5,400–7,200 RPM) that hold the data. The surface is divided into **sectors**, small fixed-size blocks of storage. A worn or damaged spot becomes a *bad sector*, which is what SMART 5, 197 and 198 count.
- **Spare sectors.** Every drive ships with reserve sectors. When a sector goes bad, the drive quietly swaps in a spare (*reallocation*). Running out of spares, or using them up quickly, is a classic sign of a dying drive.
- **Read/write heads.** Tiny arms floating a few nanometres above the spinning platter. If a head touches the surface (a *head crash*), the drive usually dies suddenly, which is one reason many failures give no SMART warning.
- **Motor and bearings.** These spin the platters and wear mechanically over time, so age (SMART 9, power-on hours) matters.
- **Electronics.** The circuit board and firmware. These can also fail suddenly and without warning.

## Ideas that link the hardware to the statistics

- **The bathtub curve.** Failure risk is high when drives are new (manufacturing defects, *infant mortality*), low for a few years (*random failures*), then rises again as they wear out (*wear-out*). The Weibull shape parameter β captures which phase a drive model is in: β < 1 means infant mortality, β ≈ 1 random failures, β > 1 wear-out.
- **Gradual vs. sudden failure.** Surface wear shows up in SMART first, so the classifier can catch it. Head crashes and electronics faults are sudden, so it can't. This caps how good any SMART-based predictor can be.
- **Environment matters.** Heat, vibration from neighbouring drives in the same chassis, and power cycling all add wear. Backblaze runs drives 24/7 in data-centre storage pods, which is very different from a laptop or desktop.
- **Model and brand differences.** Each drive model has its own design, components and quality, so failure rates vary a lot between models. That is why the fleet model estimates each model separately, pooled by manufacturer.

## What you can skip for now

Magnetic recording physics, CMR vs. SMR recording, helium-filled vs. air-filled drives, and firmware internals. Look them up later if a specific drive model behaves oddly.

## Further reading

- Wikipedia, "Hard disk drive": the *Components* and *Failures and metrics* sections.
- Backblaze's quarterly Drive Stats blog posts: how a large real fleet behaves, which is what this project models.
