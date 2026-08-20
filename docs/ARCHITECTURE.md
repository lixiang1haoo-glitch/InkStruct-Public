# InkStruct（墨构）架构

## Data flow

1. `structures build` converts ordered standard medians, IDS metadata and stroke
   matches into a versioned SQLite `CharacterGraph` database. Each graph contains
   a recursive `ComponentNode` tree with canonical identity, glyph variant, role,
   parent/children, stroke ownership and a normalized component bounding box.
2. `samples import` validates `handwriting_single_v1` without copying or changing
   source JSON, then records paths and SHA-256 hashes in one index.
3. `profile build` aligns pen-down strokes to standard order and caches global
   layout, legacy stroke deformation, canonical component layout/stroke
   prototypes, whole-component trajectories, timing, pressure and neural style
   tokens.
4. `generate` reads the database and profile once per run. It either applies the
   deterministic structure residual generator, or the hierarchical model with a
   confidence-gated deterministic fallback.

All coordinates after alignment use a normalized, top-left-origin, Y-down unit
em. Raw logical-pixel coordinates remain in the immutable source samples.

## Structural invariants

- The standard graph exclusively determines stroke count and order.
- A generator emits one trajectory for every standard stroke and cannot emit
  extra stroke identifiers.
- Unsupported characters are reported in the manifest, never substituted.
- Complex input split/merge mappings are retained for global style statistics
  but not copied as topology into generated output.

## Learned model

The model uses a 256-dimensional four-layer style encoder, six-layer structure
encoder and four-layer cross-attention stroke decoder. Each structure token maps
to exactly one standard stroke and predicts eight local B-Spline residual control
points, pressure, duration, density and confidence. CASIA training is episodic:
references and queries share a writer while validation must be writer-disjoint.
The available POT coordinates contain geometry and pen-state flags, but no observed
pressure or timestamps. Formal training therefore supervises geometry, sampling
density and confidence only; generated pressure and duration continue to come from
the user's deterministic v4 memory.

Checkpoint eligibility is explicit through `training_status`. Smoke and legacy
checkpoints always trigger deterministic fallback unless the confidence threshold
is explicitly set to zero for diagnostic pipeline testing. Formal checkpoints use
the writer-disjoint calibrated threshold, independent of their early-stopped step.

Both deterministic and learned generation convert the eight predicted/control
points into an open cubic B-Spline, oversample it, and uniformly resample by arc
length. Every stroke contains 24--128 output nodes, with additional nodes assigned
to longer paths. This keeps the online trajectory smooth without changing stroke
count, order or standard stroke IDs.

## Component collection

`collect recommend` is geometry-only. It measures component identity, variant,
role, parent layout and whole-character layout coverage, then selects from the
project-curated common-character pool. It also chooses existing stability anchors
whose sample count is below the requested target. The output includes a JSON
audit report plus TXT and collector-compatible CSV files.

## Component style layer

The component database, collection planner, profile extraction and conditioned
generator are connected end to end. A component layout prototype stores its box
residual relative to the whole glyph. A component stroke prototype separately
stores its box/start/end residual inside the component and its normalized local
B-Spline shape. This separation preserves long/short stroke preferences that
would otherwise be erased by local normalization.

The profile also contains joint sibling-layout priors keyed by parent layout and
child roles, plus character-specific component layouts for characters actually
written by the user. The former transfers general left/right or top/bottom
balance to unseen characters; the latter prevents special interlocking layouts
such as `我` from being averaged into ordinary radical layouts.

Generation supports `off`, `stroke`, `layout`, `full` and `adaptive` modes. The
default `adaptive` mode requires repeated cross-character evidence, blends the
component residual with the compatible legacy stroke residual and falls back to
legacy/global style when evidence is sparse. `full` remains available as a
diagnostic ablation; it is intentionally not the default because direct
component replacement over-deforms the current `user_001` sample set.

### Whole-component trajectory v4

`style_profile_v4` adds `ComponentTrajectoryPrototype`. Every stroke of a leaf
component is resampled in one shared component-local coordinate frame, so the
profile retains the relative position, length, curvature, pressure and duration
of the complete component. Profiles contain both a cross-character aggregate
and a `character::component` direct prototype for components actually written
by the user. Older profiles load with empty trajectory dictionaries and retain
their previous fallback behavior.

The deterministic generator now follows an explicit hierarchy:

1. Apply whole-glyph scale, offset and slant.
2. Select the component layout and place one component bounding box.
3. Select a direct, exact-context or compatible whole-component trajectory.
4. Blend the complete trajectory bundle with the standard component skeleton in
   that shared box.
5. Emit its individual strokes with standard stroke IDs and order unchanged.

When a whole-component trajectory is active, the generator bypasses unrelated
legacy per-stroke residuals. This prevents a component such as `辶` from mixing
its second and third strokes with generic `root.0` stroke prototypes. Sparse or
unsupported components still use the v3.1 per-stroke path.
