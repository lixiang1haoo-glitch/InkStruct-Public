# Vector-font research provenance

InkStruct v5 reimplements task-appropriate ideas from prior research while keeping
online handwriting topology under `CharacterGraph` control. It does not copy model
code or import external font datasets.

- **LF-Font / DM-Font:** motivates writer-by-component localized style factors and
  explicit memory for observed component instances.
- **DeepVecFont-v2:** motivates auxiliary curve samples, tangent-aware alignment and
  a bounded context refinement stage.
- **VecFontSDF / diffvg:** motivates comparing trajectories in a differentiably
  rendered distance-field space rather than supervising control points alone.
- **VecFusion:** motivates a cascade in which stable global geometry guides a more
  precise vector refinement stage.

The transferred mechanisms are independently implemented for open centerline
trajectories. Font outlines are not treated as sources of stroke order, pressure,
duration or writer identity.
