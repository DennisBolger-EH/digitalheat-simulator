# DigitalHeat Simulator

M1 provides a deterministic, independently testable one-rack/one-house thermal
kernel and an explicitly reconstructed reference baseline. The UI remains
minimal; it does not calculate results, edit parameters, or run jobs.

## Development

Install [uv](https://docs.astral.sh/uv/) and make it available on `PATH`.
uv can install the pinned Python 3.12 interpreter when needed.

```powershell
uv sync --all-groups
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run digitalheat-simulator
```

Open the address printed by NiceGUI. Stop the application with Ctrl+C.
The lockfile fixes runtime and development dependency versions.

## Boundaries

- `domain`: format-independent immutable parameters, provenance, run definitions,
  explicit unit conversion, and elapsed-time grids.
- `config`: a parameter-configuration loader interface and a versioned JSON adapter.
  Other formats can implement the same boundary without changing the domain.
- `data.reference_house`: weather ingestion and the M1 reference reconstruction.
- `simulation.thermal`: format- and UI-independent thermal energy balance.
- `workload` and `finance`: future calculation and job execution modules.
- `optimization`: future independently selectable objectives and optimizer.
  Annualized cost and heat-coverage/dumped-heat objectives are not implemented.
- `application`: future use-case services coordinating domain and adapters.
- `ui`: minimal NiceGUI entry point. Plotly is installed for later visualization.

Numeric parameters require an explicit unit, including `dimensionless` for ratios.
Groups are extensible and distinguish unit and scenario scopes. A run definition
records a scenario identifier, parameter groups, dataset identifiers and versions,
model version, and optional seed. It is not result persistence: future work must
define complete scenario content, dataset identity/versioning, and execution
semantics before claiming that actual simulation runs are reproducible.

Time grids use half-open ranges of timezone-aware instants and advance in elapsed
time, displaying instants in Europe/Zurich by default. Local DST days can have 23
or 25 hours.

The JSON adapter accepts a top-level `version` (currently `1`) and `groups` list.
Each group has an `identifier` and `parameters`; each parameter has an
`identifier`, `value`, `data_type` (`integer`, `number`, `string`, or `boolean`),
and `scope` (`unit` or `scenario`). Optional metadata matches the domain types.
Provenance dates use ISO 8601 dates. Invalid input raises an error.

## Case baseline and open decisions

`PROJECT_BRIEF.md` is authoritative. The supplied case materials under
`case_materials\` describe the reference house and the requirement for one
real locally controlled workload. Job arrival rates, workload measurement/scaling, pricing,
annualization, objective formulation, and other missing business rules require
agreement before implementation. Pool data must not be borrowed from the house
case without assessing applicability and obtaining approval.

The eventual scheduler must use the same scheduling logic for annual simulation
and a real job it can pause and resume. No scheduler, optimizer, financial model,
or result persistence is implemented in M1.

## M1 reconstructed reference baseline

```powershell
uv run python -m digitalheat_simulator.application.reference_baseline case_materials\open-meteo-47.56N7.55E283m.csv
```

The input is the supplied Open-Meteo weather export (SHA-256
`cc99c5a387940e604bb8f7ffcb564397880f33586d54b8cc2764fb9b6b223693`);
source context is in `case_materials\useful-load-useful-heat.txt` and
https://open-meteo.com/en/docs/historical-weather-api. Publication/access dates
for this export are not provided. Its metadata and SHA-256 are returned in the
report. The export is not modified. This is a reconstructed baseline, **not**
the unavailable official ready-made heat-demand profile.

The approved interpretation maps every offset-free timestamp with the file's
fixed UTC+01:00 offset to an instant, then to Europe/Zurich. Each temperature
sample represents the following elapsed hour. A heating day is a Zurich local
day whose mean of all actual samples is strictly below 12 °C, including 23 or
25 samples on DST days. The case formula is
`max(0, 10 kW * (20 °C - T) / 25.6 K)` on heating days, zero otherwise.
There is no upper cap. Power times elapsed hours produces kWh.
Hot water is 12 kWh per Zurich local day, divided uniformly over its actual
hourly intervals. The baseline uses 1 kW electrical and 1 kW gross thermal
power while on, 80% heat recovery, 35 kWh lossless storage with no transfer
limits, explicit 0 kWh initial storage, and an explicitly always-on sequence.
Rack electrical and thermal powers remain separate; no TFLOPS-to-income or
utilization-to-power relationship is inferred.

For each interval, direct recovered heat serves demand first; only the opening
storage state may discharge to meet a shortfall; the remainder is backup heat.
Surplus recoverable heat charges storage, and any remainder is dumped. Charged
heat is available starting with the following interval. Backup energy is
reported as required heat; the backup heater is not modeled. The kernel checks
the demand, recoverable-heat, and storage balances for each interval using
absolute tolerance 1e-9 kWh and relative tolerance 1e-12. Its values are
explicitly named in kW or kWh; dimensionally checked conversion helpers are
available for other input units.
