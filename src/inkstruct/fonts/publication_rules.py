"""Choices for one font publication. Source tasks keep their own confirmations."""

from dataclasses import dataclass, field


RuleKey = tuple[str, str]


@dataclass(frozen=True)
class DonorChoice:
    target: RuleKey
    sample_id: str
    sha256: str


@dataclass(frozen=True)
class PublicationRules:
    disabled: frozenset[RuleKey] = frozenset()
    donors: tuple[DonorChoice, ...] = ()


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
