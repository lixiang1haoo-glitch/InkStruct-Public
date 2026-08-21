# Stroke-order-aware sample alignment v2

Date: 2026-08-21

## Problem and policy

The previous equal-count path zipped captured strokes to standard strokes by index. A sample with
the correct stroke count but wrong order could therefore enter the profile with high confidence
and mix unrelated component strokes.

Alignment v2 computes pairwise costs from local shape, glyph position, endpoints, direction and
length. A Hungarian assignment finds the best standard-to-user permutation, with a weak prior for
the captured order. It also computes the identity cost and the best alternative assignment.

- `corrected`: per-stroke mean improvement is at least 0.04 and the next-best assignment margin is
  at least 0.012. The explicit permutation carries geometry, pressure and timestamps to the right
  standard stroke.
- `ambiguous`: a non-identity assignment has some evidence (improvement at least 0.015) but does
  not pass the correction gate. The sample is excluded from profile extraction and added to the
  rerecord audit.
- `declared`: no sufficiently useful non-identity hypothesis; the captured order is retained.
- `not_applicable`: stroke counts differ, so the existing split/merge dynamic programme is used.

## user_001 replay

The immutable input index contains 385 samples and 294 unique characters.

| Outcome | Samples | Treatment |
|---|---:|---|
| corrected order | 26 | retained using explicit standard-to-user mapping |
| ambiguous order | 41 | excluded from style profile; listed for rerecord |
| stroke-count mismatch | 8 | retained only for safe global/split-merge information |
| optimized profile | 344 | 265 unique characters, version `a6306967b1403f30` |

The machine-readable audit is ignored under
`artifacts/quality/stroke_order_v2/user_001_rerecord.json`. It records each accepted permutation,
order confidence, improvement and alternative margin. Source JSON files are not modified.

## Fixed-fold and structural regression

For a fair comparison, the previous and order-aware reports were restricted to the same 52
non-ambiguous held-out characters:

| Metric | Previous | Alignment v2 | Relative change |
|---|---:|---:|---:|
| polyline distance | 0.079809 | 0.071866 | -10.0% |
| DTW | 0.034603 | 0.030376 | -12.2% |
| SDF distance | 0.017478 | 0.017524 | +0.3% |

Lower is better. The geometry/trajectory metrics improve while rendered SDF is effectively flat.
The full optimized-profile run generated and independently checked all 9,574 supported
characters: zero failures, 100% structure coverage and content-safety pass.

## Compatibility and limitation

Raw samples and `personal_trajectory_v1` output remain unchanged. `AlignedGlyph` is now
`aligned_glyph_v2`, and quality reports are `sample_quality_audit_v2`. Old style profiles still
load normally; rebuilding a profile activates the new gate.

Geometry alone cannot reliably distinguish perfectly overlapping or near-identical strokes.
Those cases intentionally remain `ambiguous` instead of being force-corrected.
