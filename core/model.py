"""Format pivot commun à toutes les sources de courses."""

from dataclasses import dataclass, asdict
from typing import Optional

RACE_TYPES = ("route", "trail", "other")


@dataclass
class Race:
    source: str
    external_id: str
    date: Optional[str]
    pays: Optional[str]
    ville: Optional[str]
    distance_km: Optional[float]
    type: str                         # "route" | "trail" | "other"
    prix: Optional[float]
    devise: Optional[str] = None

    def __post_init__(self):
        if self.type not in RACE_TYPES:
            raise ValueError(f"type invalide: {self.type!r}")

    def as_dict(self) -> dict:
        return asdict(self)
