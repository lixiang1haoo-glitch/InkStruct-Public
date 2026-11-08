"""Document-owned optical corrections; raw glyphs and selection identities stay frozen."""

import math
from dataclasses import dataclass, replace
from types import SimpleNamespace


@dataclass(frozen=True)
class GlyphCorrection:
    scope: str = "occurrence"
    character: str = ""
    occurrence_id: str = ""
    asset_id: str = ""
    dx_em: float = 0
    dy_em: float = 0
    scale_x: float = 1
    scale_y: float = 1

    def __post_init__(self):
        if self.scope not in {"occurrence", "character", "document"}:
            raise ValueError("无效的字符校正范围")
        if any(not isinstance(v, str) or len(v) > 256 for v in
               (self.character, self.occurrence_id, self.asset_id)):
            raise ValueError("无效的字符校正身份")
        if self.scope == "document":
            valid = not (self.character or self.occurrence_id or self.asset_id)
        else:
            valid = len(self.character) == 1 and not 0xD800 <= ord(self.character) <= 0xDFFF
            valid = valid and bool(self.occurrence_id) == (self.scope == "occurrence")
        if not valid:
            raise ValueError("字符校正范围与目标不一致")
        for value, low, high in ((self.dx_em, -2, 2), (self.dy_em, -2, 2),
                                 (self.scale_x, .25, 4), (self.scale_y, .25, 4)):
            if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                raise ValueError("字符校正超出范围：位移 ±200%，缩放 25–400%")

    @property
    def key(self):
        return self.scope, self.character, self.occurrence_id, self.asset_id

    def matches(self, fragment):
        return (self.scope == "document" or (
            self.character == fragment.text
            and (not self.asset_id or self.asset_id == fragment.asset_id)
            and (self.scope != "occurrence" or self.occurrence_id == fragment.occurrence_id)))

    def point(self, x, y, *, baseline=.88):
        return x * self.scale_x + self.dx_em, baseline + (y - baseline) * self.scale_y + self.dy_em


def correction_for(records, fragment):
    # A specific occurrence overrides character rules, which override the whole
    # document. Within character rules an exact sample overrides all samples.
    candidates = [r for r in records if r.matches(fragment)]
    return max(candidates, key=lambda r: (r.scope == "occurrence", r.scope == "character",
                                         bool(r.asset_id)), default=None)


def update_corrections(records, targets, fragments, *, reset=False):
    """Replace the entire chosen range, including older occurrence overrides.

    Sample and all-sample UI scopes both persist as exact character/asset rules,
    keeping the existing document format and frozen-font identity contract.
    Legacy whole-document rules remain outside the affected range.
    """
    targets = tuple(targets)
    if not targets or any(t.scope not in {"occurrence", "character"} or not t.asset_id
                          for t in targets):
        raise ValueError("校正操作需要明确的出现位置或样本身份")
    keys = {t.key for t in targets}
    samples = {(t.character, t.asset_id) for t in targets if t.scope == "character"}
    occurrences = {(t.character, t.occurrence_id, t.asset_id) for t in targets
                   if t.scope == "occurrence"}
    affected_ids = {f.occurrence_id for f in fragments if (f.text, f.asset_id) in samples}

    def covered(old):
        if old.key in keys:
            return True
        if old.scope != "occurrence":
            return False
        if (old.character, old.asset_id) in samples or old.occurrence_id in affected_ids:
            return True
        return any(old.character == c and old.occurrence_id == o and
                   (not old.asset_id or old.asset_id == a) for c, o, a in occurrences)

    retained = [r for r in records if not covered(r)]
    if not reset:
        return (*retained, *targets)
    # Restoring a range means the original font, even if a legacy broad rule
    # remains for unrelated characters. An identity rule masks that fallback.
    for target in targets:
        probe = SimpleNamespace(text=target.character, asset_id=target.asset_id,
                                occurrence_id=target.occurrence_id)
        if correction_for(retained, probe) is not None:
            retained.append(replace(target, dx_em=0, dy_em=0, scale_x=1, scale_y=1))
    return tuple(retained)
