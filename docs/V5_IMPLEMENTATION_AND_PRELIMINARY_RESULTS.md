# InkStruct v5 implementation and preliminary results

Date: 2026-08-20

## Reproducibility record

- Formal report commit: `4d6e85ea474c4df42e38300d1113f8bd9617708f`
- Worktree state: clean (`dirty=false`)
- User index SHA-256: `bd27ddb04a140bc2f807024f21bc0e6a1450ce9b94fd38636e2062490c352b18`
- MakeMeAHanzi / structure version: `bddc96d41bef78427ed0e034e9f7e31d71fd1b92`
- Formal ablation config SHA-256: `ec26f6ca544ff1f977c1901f6e7fe95cd68d145482cccf0debaa2d2328db89ff`
- Environment: Python 3.13.9, NumPy 2.5.2, PyTorch 2.11.0+cu128, NVIDIA GeForce RTX 5070 Ti
- Formal three-way ablation runtime: 75.53 seconds

The machine-readable reports and generated trajectories remain under ignored `artifacts/`
paths. They intentionally are not committed because they contain experiment intermediates and
may derive from user samples.

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

## Clean-worktree v4 controls

The following values use the same first grouped fold (58 evaluated characters; one input sample
was skipped for a pre-existing user/structure stroke-count mismatch).

| Variant | Polyline distance | DTW | DTW 95% bootstrap CI | SDF distance | Style similarity |
|---|---:|---:|---:|---:|---:|
| skeleton | 0.138704 | 0.064604 | [0.059078, 0.071159] | 0.023085 | 0.988766 |
| v4 component-off | 0.086021 | 0.039695 | [0.034344, 0.045936] | 0.018303 | 0.989662 |
| v4 adaptive | **0.080638** | **0.036820** | **[0.031750, 0.043079]** | **0.017705** | **0.990544** |

## Budget protocol smoke result

At budget 8 on one fixed fold, DTW was 0.041293 for random and 0.040915 for both coverage and
information gain. SDF distance was 0.019335 for random and 0.018266 for coverage/information
gain. This run validates the protocol only. With one budget row the sweet-spot detector correctly
returns `insufficient_budget_rows`; therefore no sweet point has been found.

The complete five-fold configuration covering budgets 8/16/24/32/48/64/96/128/192/all-train,
five random selection seeds and three final training seeds is in
`configs/experiments/v5_budget_user001.json`.

## Structural and blind-evaluation status

- Full structure validation: 9,574 / 9,574 generated, zero failures, 100% structure coverage and
  content-safety pass. Stroke count, order, standard stroke ID, finite/ranged coordinates,
  pressure and monotonic time were checked independently.
- A 60-character stratified blind pack was generated successfully. Formal preference confidence
  intervals are intentionally absent until every scored item has at least three independent
  ratings.
- One reviewer has completed all 60 items. After decoding the randomized sides, v4 adaptive was
  preferred on 57 items, three were ties and the v5 smoke candidate was preferred on zero items.
  Counting a tie as 0.5 gives an exploratory v5 preference of 2.5%. This single-reviewer result
  has no formal confidence interval and cannot pass the production gate, but it is a strong
  negative signal for the current smoke candidate.
- Promotion requires at least 60% v5 preference with a 95% CI lower bound above 50%; 70% remains
  the ideal target.

## Production decision

Keep `ComponentTrajectory v4 adaptive` as the production default. The v5 model remains an
experimental option until matched-compute checkpoints are trained with the configured seeds,
the complete budget/ablation matrix is run on a clean worktree, and blind ratings pass the
promotion gate. No statistically significant v5-over-v4 claim is made from smoke checkpoints.
