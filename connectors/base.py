"""Interface commune à tous les connecteurs de sources."""

from abc import ABC, abstractmethod
from core.model import Race


class Connector(ABC):
    source: str = "base"

    @abstractmethod
    def fetch(self) -> list[Race]:
        raise NotImplementedError
