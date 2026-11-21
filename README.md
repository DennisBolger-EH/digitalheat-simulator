# DigitalHeat Simulator

M0 establishes a project foundation, not a simulator. The UI is intentionally
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
- `data`: future dataset ingestion; CSV is planned for supplied tabular time series.
- `simulation`, `workload`, and `finance`: future calculation and job execution
  modules, independent of the UI.
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
or 25 hours. This does not decide the reference-house heating-day rule.

The JSON adapter accepts a top-level `version` (currently `1`) and `groups` list.
Each group has an `identifier` and `parameters`; each parameter has an
`identifier`, `value`, `data_type` (`integer`, `number`, `string`, or `boolean`),
and `scope` (`unit` or `scenario`). Optional metadata matches the domain types.
Provenance dates use ISO 8601 dates. Invalid input raises an error.

## Case baseline and open decisions

`PROJECT_BRIEF.md` is authoritative. The supplied case materials under
`case_materials\` describe the reference house and the requirement for one
real locally controlled workload. Source materials are not runtime defaults.
The supplied datasets and tariff material require identification and validation
before use; heating-day DST treatment remains deferred until the reference
profile is evaluated. Job arrival rates, workload measurement/scaling, pricing,
annualization, objective formulation, and other missing business rules require
agreement before implementation. Pool data must not be borrowed from the house
case without assessing applicability and obtaining approval.

The eventual scheduler must use the same scheduling logic for annual simulation
and a real job it can pause and resume. No scheduler, optimizer, simulation
results, physical or financial model, or result persistence is implemented in M0.
