"""Choices for one font publication. Source tasks keep their own confirmations."""

from dataclasses import dataclass, field


RuleKey = tuple[str, str]
SHARED_FAMILIES = {
    "shared": "全角与半角",
    "latin_italic": "英文正体与斜体",
    "greek": "拉丁正体与希腊大写",
}


@dataclass(frozen=True)
class DonorChoice:
    target: RuleKey
    sample_id: str
    sha256: str


@dataclass(frozen=True)
class PublicationRules:
    disabled: frozenset[RuleKey] = frozenset()
    donors: tuple[DonorChoice, ...] = ()
    enabled: frozenset[RuleKey] = frozenset()
    families: tuple[tuple[str, bool], ...] = ()

    def allows(self, key: RuleKey, *, confirmed=False):
        if key in self.disabled:
            return False
        if key in self.enabled:
            return True
        return dict(self.families).get(key[0], key[0] in {"shared", "constructed"} or confirmed)


@dataclass
class RuleEvidence:
    confirmed: set[RuleKey] = field(default_factory=set)
    donors: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RuleRow:
    key: RuleKey
    kind: str
    target: str
    source: str
    donor_status: str
    enabled: bool
    outcome: str
    donor_character: str = ""
