"""Explicit dimensional conversion for foundation types."""

from pint import UnitRegistry


def _registry() -> UnitRegistry:
    registry = UnitRegistry()
    registry.define("CHF = [currency]")
    registry.define("floating_point_operation = [floating_point_operation] = FLOP")
    registry.define("FLOPS = FLOP / second")
    return registry


def convert(value: float, source_unit: str, target_unit: str) -> float:
    if not source_unit.strip() or not target_unit.strip():
        raise ValueError("Source and target units must be explicit")
    registry = _registry()
    return float(registry.Quantity(value, source_unit).to(target_unit).magnitude)
