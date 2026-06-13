"""Shared provenance vocabulary for read-model API responses."""

from typing import Literal

DataProvenance = Literal["imported", "manual", "derived"]
