"""Identifiers for displayed results, grouped by presentation surface.

Editable settings and selected optimization parameters are inputs, not results.
Labels, worker state, site identity, journal paths and rejection text are status
or metadata. A chart series has one explanation, not one per plotted point.
"""

PRIMARY_CARDS = (
    ("Heat coverage", ("heat_coverage",)),
    ("Useful server heat", ("useful_heat",)),
    ("Backup heat", ("backup_heat_kwh",)),
    ("Dumped heat", ("dumped_heat_kwh",)),
    ("Electricity consumption", ("electrical_energy_kwh",)),
    ("Compute utilization / work", ("compute_utilization", "compute_work")),
    ("Annualized cost", ("annualized_cost",)),
    ("Compute income", ("compute_income",)),
)

THERMAL_DETAILS = (
    "demand_kwh",
    "direct_supply_kwh",
    "storage_charge_kwh",
    "storage_discharge_kwh",
    "dumped_heat_kwh",
    "backup_heat_kwh",
    "space_heat",
    "hot_water",
    "storage_final",
    "gross_heat_kwh",
    "recoverable_heat_kwh",
)
COMPUTE_DETAILS = ("rack_hours", "installed_capacity", "compute_work", "compute_utilization")
ECONOMIC_DETAILS = (
    "capex",
    "annualized_capex",
    "electricity_cost",
    "service",
    "opex",
    "backup_cost",
    "heat_value",
    "compute_income",
    "case_break_even",
    "full_break_even",
    "annualized_cost",
)
THERMAL_CHART_SERIES = (
    "chart_demand",
    "chart_recoverable",
    "chart_useful",
    "chart_backup",
    "chart_dumped",
)
STORAGE_CHART_SERIES = ("chart_storage",)
OPTIMIZATION_RESULTS = (
    "optimization_objective",
    "optimization_grid_size",
    "optimization_evaluated",
    "optimization_feasible",
    "optimization_rejected",
)
OPTIMIZATION_CHART_SERIES = ("optimization_candidates",)
WORKLOAD_RESULTS = (
    "workload_progress",
    "workload_runtime",
    "workload_decision",
    "workload_opportunity",
    "workload_checkpoint",
    "workload_power",
    "workload_electricity",
    "workload_gross_heat",
    "workload_heat",
)

DISPLAYED_BY_SURFACE = {
    "primary": frozenset(key for _, keys in PRIMARY_CARDS for key in keys),
    "thermal_details": frozenset(THERMAL_DETAILS),
    "compute_details": frozenset(COMPUTE_DETAILS),
    "economic_details": frozenset(ECONOMIC_DETAILS),
    "dashboard_optimization": frozenset(OPTIMIZATION_RESULTS),
    "charts": frozenset(THERMAL_CHART_SERIES + STORAGE_CHART_SERIES),
    "optimization": frozenset(OPTIMIZATION_RESULTS + OPTIMIZATION_CHART_SERIES),
    "workload": frozenset(WORKLOAD_RESULTS),
}
