# InkStruct v5 implementation and formal training results

Date: 2026-08-20

## Reproducibility record

- Training and formal ablation commit: `25126b35143489e9c89b99e7f474fdae30168608`
- Worktree state for all formal runs: clean (`dirty=false`)
- User index SHA-256: `bd27ddb04a140bc2f807024f21bc0e6a1450ce9b94fd38636e2062490c352b18`
- CASIA train-writer index SHA-256: `074c615112bc39fe90c0af9667925fe5603fe2c30db4b28f4af24c4fbed9adf3`
- CASIA validation-writer index SHA-256: `461696526fea1a290fb1328fdf38c524300ff2c5f6a22b2cd5aa4819ab966ceb`
- CASIA test index SHA-256: `87c3886c5c8f94d941a51d201de8a0249cb2e7df8f665788e18a8dcde229783d`
- MakeMeAHanzi / structure version: `bddc96d41bef78427ed0e034e9f7e31d71fd1b92`
- Formal ablation config SHA-256: `beac1c6100a809349952460c443f6627affdd64e4887a255c550b450b7f59576`
- Environment: Python 3.13.9, NumPy 2.5.2, PyTorch 2.11.0+cu128, NVIDIA GeForce RTX 5070 Ti
- Three-seed training runtime: 338.26 seconds; four-way ablation runtime: 150.63 seconds

Machine-readable checkpoints, reports, profiles and trajectories remain under ignored
`artifacts/` paths. They are not committed because they contain model weights, experiment
intermediates and data derived from user samples. The executable protocol is
`scripts/train_v5_formal.ps1`; its declarative counterpart is
`configs/training/v5_formal.json`.

## Implemented scope

- Character-grouped five-fold splits and writer-disjoint CASIA train/validation/test checks.
- Extended trajectory, dynamics, SDF/IoU, style descriptor and content-safety metrics.
- Pure PyTorch differentiable open B-Spline rendering, curve/endpoint/tangent/curvature losses,
  multi-scale soft SDF loss and bounded whole-glyph refinement.
- Optional `style_profile_v5.factorized_style` with a 64-dimensional writer latent,
  component/role-layout/stroke-signature context, uncertainty heads and v4 fallback.
- Greedy information-gain collection with virtual posterior updates and stroke-cost penalty.
- Reproducible budget sweep, stratified ablation, blind-pack and blind-score commands.
- Bootstrap confidence intervals by stroke count, layout and component coverage.
- Exact seeded resume, best/last checkpoints, early stopping, threshold calibration, data hashes,
  environment capture and a hard clean-worktree gate for formal training.

## Formal training

All seeds used the same writer split and configuration: 50,000 scanned CASIA train records,
batch 8, eight references, refiner and factorized style enabled, curve loss weight 1.0, SDF loss
weight 0.25, validation every 20 steps and patience 5. The nominal 10,000-step ceiling is not a
quality target; writer-disjoint early stopping selected the following checkpoints.

| Seed | Completed step | Best step | Best validation loss | Status |
|---:|---:|---:|---:|---|
| 1001 | 180 | 80 | 0.684644 | early stopped |
| 2002 | 560 | 460 | **0.655828** | early stopped; selected |
| 3003 | 380 | 280 | 0.668275 | early stopped |

CASIA POT coordinates provide geometry and pen-state flags, not observed pressure or timestamps.
The trainer no longer learns artificial constant pressure/duration labels. Formal v5 generation
therefore takes pressure and duration from deterministic user memory while the neural model
predicts geometry, density, confidence and uncertainty.

The selected seed-2002 checkpoint produced a factorized user profile from 385 samples and 294
unique characters (`profile_version=230d747fc0512a5c`). The calibrated confidence threshold is
0.30.

## Fixed-fold formal ablation

The table uses the same grouped fold (58 evaluated characters; one indexed character is skipped
for a pre-existing user/structure stroke-count mismatch). CASIA writer-style similarity is the
mean of the per-character style embedding metric; higher is better, while other metrics are
lower-is-better.

| Variant | Polyline distance | DTW | SDF distance | CASIA writer-style similarity |
|---|---:|---:|---:|---:|
| skeleton | 0.138704 | 0.064604 | 0.023085 | 0.947502 |
| v4 adaptive | **0.080633** | **0.036816** | **0.017703** | **0.947318** |
| v5 safe adaptive | **0.080633** | **0.036816** | **0.017703** | **0.947318** |
| v5 forced diagnostic | 0.103707 | 0.048835 | 0.020767 | 0.862889 |

All 59 generated files in safe v5 mode used `deterministic_fallback_low_model_confidence`.
Forcing the checkpoint reduced quality: DTW is about 32.6% worse than v4 and SDF distance is
about 17.3% worse. The safety gate is therefore behaving correctly; the formal v5 checkpoint is
not a production improvement.

## Trajectory smoothness and structure safety

The smoke output's visible polylines were caused by sparse output sampling (previously as few as
eight points), independently of the model's semantic quality. Deterministic and learned paths now
use an open cubic B-Spline, oversampling and uniform arc-length resampling. Every stroke receives
24--128 nodes, with longer paths receiving more.

On the ten-character preview `中国湖春天地书法墨构`:

| Generator | Mean nodes/stroke | Segment distance p95 | Maximum segment distance |
|---|---:|---:|---:|
| v4 smooth | 52.24 | 0.009541 | 0.010284 |
| v5 forced smooth | 75.06 | 0.009228 | 0.009709 |

The final v4-adaptive smooth full run generated 9,574 / 9,574 supported characters in 149.58
seconds with zero failures. Independent evaluation checked all 9,574: structural failure count
0, structure coverage 100%, content-safety pass true. Smoothing does not change stroke count,
order or standard stroke IDs.

## Budget and blind-evaluation status

At budget 8 on one fixed fold, DTW was 0.041293 for random and 0.040915 for both coverage and
information gain. SDF distance was 0.019335 for random and 0.018266 for coverage/information
gain. This validates the protocol only; with one budget row no sweet point has been found. The
complete five-fold configuration remains in `configs/experiments/v5_budget_user001.json`.

One reviewer completed the earlier 60-item smoke blind pack: v4 was preferred on 57 items, three
were ties and smoke v5 was preferred on zero. Because there is only one reviewer, no formal human
confidence interval is reported. Given the formal automatic ablation's negative result, scarce
reviewer time should not be spent rating this checkpoint. A new blind pack is warranted only
after a future model first beats v4 on the fixed-fold automatic gate.

## Production decision

Keep the smoothed `ComponentTrajectory v4 adaptive` generator as the production default. The
formal v5 checkpoint remains an opt-in diagnostic artifact behind calibrated fallback. It does
not satisfy the same-budget promotion criterion, and no v5-over-v4 claim is made.
