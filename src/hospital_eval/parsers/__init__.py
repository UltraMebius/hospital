"""Document parser adapters."""

from .base import Parser
from .mineru import MinerUCommandParser

__all__ = ["MinerUCommandParser", "Parser"]

