"""Versioned document-owned variation; font resources remain immutable."""
import math
from dataclasses import asdict, dataclass

LEGACY = "inkstruct_han_variation_v1"
NATURAL = "inkstruct_han_variation_v2"


@dataclass(frozen=True)
class HanVariation:
    enabled: bool = False
    seed: int = 0
    strength: float = 0.55
    schema_version: str = NATURAL
    size_strength: float = 0.3
    spacing_strength: float = 0.35
    baseline_strength: float = 0.2

    def __post_init__(self):
        if self.schema_version not in {LEGACY, NATURAL}:
            raise ValueError("Unknown Han variation version")
        if type(self.enabled) is not bool or type(self.seed) is not int or not 0 <= self.seed <= 2147483647:
            raise ValueError("Chinese variation requires a boolean switch and a seed within 0–2147483647")
        for value in (self.strength, self.size_strength, self.spacing_strength, self.baseline_strength):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                raise ValueError("Chinese variation strengths must be within 0–1")


def variation_record(config):
    record = asdict(config)
    if config.schema_version == LEGACY:
        for key in ("size_strength", "spacing_strength", "baseline_strength"):
            record.pop(key)
    return record
