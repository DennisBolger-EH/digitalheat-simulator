"""Finite-grid search and structured, UI-ready candidate records."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import pairwise, product
from math import prod
from typing import Literal

from digitalheat_simulator.domain.compute import ComputeRack, Job
from digitalheat_simulator.domain.parameters import Parameter, ParameterGroup
from digitalheat_simulator.domain.scenario import Scenario
from digitalheat_simulator.finance.model import EconomicResult

Objective = Literal["economic", "thermal"]
Key = tuple[str, str]


@dataclass(frozen=True)
class Constraint:
    name: str
    satisfied: bool
    detail: str


@dataclass(frozen=True)
class Metrics:
    scenario: Scenario
    source_scenario: Scenario
    jobs: tuple[Job, ...] | None
    racks: tuple[ComputeRack, ...] | None
    annual: bool
    useful_heat_kwh: float | None
    dumped_heat_kwh: float
    backup_heat_kwh: float
    heat_coverage: float | None
    electricity_kwh: float
    delivered_work_tflop: float | None
    remaining_work_tflop: float | None
    compute_utilization: float | None
    completed_jobs: int | None
    missed_deadlines: int | None
    economics: EconomicResult


@dataclass(frozen=True)
class Evaluation:
    metrics: Metrics | None
    constraints: tuple[Constraint, ...]
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    groups: tuple[ParameterGroup, ...]
    objective_value: float | tuple[float, float] | None
    feasible: bool
    rejection_reasons: tuple[str, ...]
    evaluation: Evaluation


@dataclass(frozen=True)
class SearchResult:
    objective: Objective
    method: str
    exhaustive: bool
    result_label: str
    grid_size: int
    candidates: tuple[Candidate, ...]
    best: Candidate | None
    evaluated_count: int
    feasible_count: int
    rejected_count: int
    variable_keys: tuple[Key, ...]
    fixed_parameters: tuple[tuple[str, Parameter], ...]
    assumptions: tuple[str, ...]


def _grid(parameter: Parameter) -> tuple[int | float, ...] | None:
    if (
        parameter.enabled is False
        or parameter.optimizable is not True
        or parameter.data_type not in ("integer", "number")
        or parameter.minimum is None
        or parameter.maximum is None
        or parameter.step is None
    ):
        return None
    lower, upper, step = (
        Decimal(str(value)) for value in (parameter.minimum, parameter.maximum, parameter.step)
    )
    if parameter.data_type == "integer" and any(
        value != value.to_integral_value() for value in (lower, upper, step)
    ):
        raise ValueError(f"{parameter.identifier}: integer grid metadata must be integral")
    count = int((upper - lower) // step) + 1
    if count > 1_000_000:
        raise ValueError(f"{parameter.identifier}: grid exceeds one million values")
    values = tuple(lower + i * step for i in range(count))
    result = tuple(
        int(value) if parameter.data_type == "integer" else float(value) for value in values
    )
    if any(left >= right for left, right in pairwise(result)):
        raise ValueError(f"{parameter.identifier}: grid values collapse at numeric precision")
    return result


def search(
    groups: tuple[ParameterGroup, ...],
    evaluator: Callable[[tuple[ParameterGroup, ...]], Evaluation],
    objective: Objective,
    *,
    budget: int = 625,
    group: str | None = None,
) -> SearchResult:
    """Search the declared grid; max is included only when aligned to step."""
    if objective not in ("economic", "thermal"):
        raise ValueError("unknown objective")
    if type(budget) is not int or budget < 1:
        raise ValueError("budget must be a positive integer")
    if len({item.identifier for item in groups}) != len(groups):
        raise ValueError("parameter group identifiers must be unique")
    if group is not None and group not in {item.identifier for item in groups}:
        raise ValueError("unknown parameter group")
    axes: list[tuple[Key, tuple[int | float, ...]]] = []
    fixed = []
    for item in sorted(groups, key=lambda x: x.identifier):
        for parameter in sorted(item.parameters, key=lambda x: x.identifier):
            values = _grid(parameter) if group is None or group == item.identifier else None
            if values is None:
                fixed.append((item.identifier, parameter))
            else:
                axes.append(((item.identifier, parameter.identifier), values))
    size = prod(len(values) for _, values in axes)
    exhaustive = size <= budget
    candidates: list[Candidate] = []
    seen: set[tuple[int, ...]] = set()
    best: Candidate | None = None
    best_key: tuple[float, ...] | None = None
    best_indices: tuple[int, ...] | None = None

    def run(indices: tuple[int, ...]) -> None:
        nonlocal best, best_key, best_indices
        if indices in seen or len(candidates) >= budget:
            return
        seen.add(indices)
        selected = {key: values[index] for (key, values), index in zip(axes, indices, strict=True)}

        def candidate_parameter(group_identifier: str, parameter: Parameter) -> Parameter:
            key = (group_identifier, parameter.identifier)
            if key not in selected:
                return parameter
            provenance = parameter.provenance
            if provenance is not None:
                transformation = (
                    (provenance.transformation + "; ") if provenance.transformation else ""
                ) + "explored grid candidate; not a sourced observation"
                provenance = replace(provenance, transformation=transformation)
            return replace(parameter, value=selected[key], provenance=provenance)

        updated = tuple(
            replace(
                item,
                parameters=tuple(candidate_parameter(item.identifier, p) for p in item.parameters),
            )
            for item in groups
        )
        evaluation = evaluator(updated)
        reasons = [
            constraint.detail for constraint in evaluation.constraints if not constraint.satisfied
        ]
        constraint_rejections = len(reasons)
        metrics = evaluation.metrics
        value: float | tuple[float, float] | None = None
        rank: tuple[float, ...] | None = None
        if metrics is not None:
            if not metrics.annual:
                reasons.append("objective requires a complete Zurich calendar year")
            elif objective == "economic":
                amount = metrics.economics.annualized_total_cost_chf
                if amount.value is None:
                    reasons.append(str(amount.reason))
                else:
                    value, rank = amount.value, (amount.value,)
            elif metrics.useful_heat_kwh is None:
                reasons.append(
                    "useful server heat unavailable: "
                    + str(metrics.economics.useful_heat_kwh.reason)
                )
            else:
                value = (metrics.useful_heat_kwh, metrics.dumped_heat_kwh)
                rank = (-metrics.useful_heat_kwh, metrics.dumped_heat_kwh)
        elif not reasons:
            raise ValueError("evaluator returned neither metrics nor a rejection reason")
        if metrics is not None:
            objective_reasons = tuple(reasons[constraint_rejections:])
            evaluation = replace(
                evaluation,
                constraints=evaluation.constraints
                + (
                    Constraint(
                        "objective availability",
                        not objective_reasons,
                        "; ".join(objective_reasons) if objective_reasons else "available",
                    ),
                ),
            )
        candidate = Candidate(updated, value, not reasons, tuple(reasons), evaluation)
        candidates.append(candidate)
        if (
            candidate.feasible
            and rank is not None
            and (best_key is None or (rank, indices) < (best_key, best_indices))
        ):
            best, best_key, best_indices = candidate, rank, indices

    if exhaustive:
        for indices in product(*(range(len(values)) for _, values in axes)):
            run(indices)
    else:
        # A stratified coarse grid followed by nearest-grid refinement around the best.
        counts = [1] * len(axes)
        coarse_budget = max(1, budget // 2)
        while True:
            changed = False
            for i, (_, values) in enumerate(axes):
                proposed = counts.copy()
                proposed[i] += 1
                if proposed[i] <= len(values) and prod(proposed) <= coarse_budget:
                    counts = proposed
                    changed = True
            if not changed:
                break
        positions = [
            tuple((len(values) - 1) // 2 for _ in range(1))
            if count == 1
            else tuple(i * (len(values) - 1) // (count - 1) for i in range(count))
            for (_, values), count in zip(axes, counts, strict=True)
        ]
        for indices in product(*positions):
            run(indices)
        center = best_indices if best_indices is not None else tuple(p[0] for p in positions)
        for distance in range(1, max(len(values) for _, values in axes)):
            for axis, (_, values) in enumerate(axes):
                for direction in (-1, 1):
                    index = center[axis] + direction * distance
                    if 0 <= index < len(values):
                        indices = list(center)
                        indices[axis] = index
                        run(tuple(indices))
                    if len(candidates) >= budget:
                        break
                if len(candidates) >= budget:
                    break
            if len(candidates) >= budget:
                break
        if len(candidates) < budget:
            for indices in product(*(range(len(values)) for _, values in axes)):
                run(indices)
                if len(candidates) >= budget:
                    break
    feasible = sum(item.feasible for item in candidates)
    return SearchResult(
        objective,
        "exhaustive grid" if exhaustive else "coarse-to-fine grid",
        exhaustive,
        (
            "optimal within declared finite grid"
            if best is not None and exhaustive
            else "best evaluated candidate"
            if best is not None
            else "no feasible evaluated candidate"
        ),
        size,
        tuple(candidates),
        best,
        len(candidates),
        feasible,
        len(candidates) - feasible,
        tuple(key for key, _ in axes),
        tuple(fixed),
        ("Grid maximum included only if aligned to step.", "Ties use ascending grid indices."),
    )
