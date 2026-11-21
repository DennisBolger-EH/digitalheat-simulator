"""Immutable, extensible parameters and source metadata."""

from dataclasses import dataclass
from datetime import date
from math import isfinite
from typing import Literal

ParameterValue = int | float | str | bool
ParameterType = Literal["integer", "number", "string", "boolean"]
ParameterScope = Literal["unit", "scenario"]


@dataclass(frozen=True)
class Provenance:
    source: str
    publication_date: date | None = None
    access_date: date | None = None
    unit: str | None = None
    applicability: str | None = None
    transformation: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source.strip():
            raise ValueError("Provenance source must be a non-empty string")
        for name in ("publication_date", "access_date"):
            item = getattr(self, name)
            if item is not None and type(item) is not date:
                raise ValueError(f"{name} must be a date")
        for name in ("unit", "applicability", "transformation"):
            item = getattr(self, name)
            if item is not None and not isinstance(item, str):
                raise ValueError(f"{name} must be a string")


@dataclass(frozen=True)
class Parameter:
    identifier: str
    value: ParameterValue
    data_type: ParameterType
    scope: ParameterScope
    unit: str | None = None
    label: str | None = None
    description: str | None = None
    minimum: int | float | None = None
    maximum: int | float | None = None
    step: int | float | None = None
    default: ParameterValue | None = None
    uncertainty_range: tuple[float, float] | None = None
    optimizable: bool | None = None
    enabled: bool | None = None
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("Parameter identifier must be a non-empty string")
        if self.scope not in ("unit", "scenario"):
            raise ValueError("Parameter scope must be unit or scenario")
        if self.data_type not in ("integer", "number", "string", "boolean"):
            raise ValueError("Unsupported parameter data type")
        self._validate_value(self.value, "value")
        if self.default is not None:
            self._validate_value(self.default, "default")
        numeric = self.data_type in ("integer", "number")
        if numeric and (not isinstance(self.unit, str) or not self.unit.strip()):
            raise ValueError("Numeric parameters require an explicit unit")
        for name in ("minimum", "maximum", "step"):
            bound = getattr(self, name)
            if bound is not None and (
                not numeric or type(bound) not in (int, float) or not isfinite(bound)
            ):
                raise ValueError(f"{name} must be a finite number on a numeric parameter")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum must not exceed maximum")
        if self.step is not None and self.step <= 0:
            raise ValueError("step must be positive")
        if numeric:
            for name in ("value", "default"):
                item = getattr(self, name)
                if item is not None and (
                    (self.minimum is not None and item < self.minimum)
                    or (self.maximum is not None and item > self.maximum)
                ):
                    raise ValueError(f"{name} is outside the parameter bounds")
        if self.uncertainty_range is not None:
            bounds = self.uncertainty_range
            if (
                not numeric
                or not isinstance(bounds, tuple)
                or len(bounds) != 2
                or any(type(bound) not in (int, float) or not isfinite(bound) for bound in bounds)
                or bounds[0] > bounds[1]
            ):
                raise ValueError("uncertainty_range must contain two ordered finite numbers")
        for name in ("optimizable", "enabled"):
            flag = getattr(self, name)
            if flag is not None and type(flag) is not bool:
                raise ValueError(f"{name} must be a boolean")
        for name in ("unit", "label", "description"):
            item = getattr(self, name)
            if item is not None and not isinstance(item, str):
                raise ValueError(f"{name} must be a string")
        if self.provenance is not None and not isinstance(self.provenance, Provenance):
            raise ValueError("provenance must be a Provenance instance")

    def _validate_value(self, value: ParameterValue, name: str) -> None:
        valid = {
            "integer": type(value) is int,
            "number": type(value) in (int, float),
            "string": type(value) is str,
            "boolean": type(value) is bool,
        }[self.data_type]
        if not valid or (type(value) in (int, float) and not isfinite(value)):
            raise ValueError(f"{name} does not match {self.data_type}")


@dataclass(frozen=True)
class ParameterGroup:
    identifier: str
    parameters: tuple[Parameter, ...]
    label: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier.strip():
            raise ValueError("Group identifier must be a non-empty string")
        if not isinstance(self.parameters, tuple) or not all(
            isinstance(parameter, Parameter) for parameter in self.parameters
        ):
            raise ValueError("Group parameters must be a tuple of Parameter instances")
        identifiers = [parameter.identifier for parameter in self.parameters]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Parameter identifiers must be unique within a group")
        for name in ("label", "description"):
            item = getattr(self, name)
            if item is not None and not isinstance(item, str):
                raise ValueError(f"{name} must be a string")
