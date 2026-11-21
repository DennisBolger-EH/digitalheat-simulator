# DigitalHeat Simulator

M3 adds ideal compute execution and a deterministic, heat-aware reference
scheduler to the independent site-local thermal model. The UI remains minimal;
it does not calculate results, edit parameters, or run jobs.

## Project context

The repository is the authoritative persistent project memory. Before starting
a new AI session or after a context reset, follow the mandatory recovery and
update procedure in [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md).

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
- `data.pool_demand`: supplied per-pool energy profiles; no physical pool model.
- `simulation.thermal`: format- and UI-independent thermal energy balance.
- `domain.scenario` and `simulation.scenario`: local site inputs, grouped
  independent sites, per-site and aggregated energy flows.
- `workload`: ideal compute execution accounting and reference scheduling.
- `finance`: future financial calculations.
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

The eventual demonstrator must use the same scheduling logic for annual simulation
and a real job it can pause and resume. No real-job adapter, optimizer, financial
model, or result persistence is implemented.

## M3 ideal compute and scheduling

`Job` specifies total work in TFLOP, a fixed requested rate in TFLOP/s, release,
deadline, eligible sites and pause rules. `ComputeRack` distinguishes installed
and available compute capacity from electrical and thermal power. Work equals
rate times elapsed seconds; neither compute rate nor work is income.

`workload.scheduler.schedule(scenario, jobs, racks)` returns execution segments,
per-job progress and deadline outcomes, and integrated per-site and aggregate
thermal results. The scenario must represent individually identified physical
sites (`SiteGroup.quantity == 1`); the physical compute racks must match the
site rack inventory, and explicit Boolean rack operations must be off to avoid
mixing two operation sources. The original `simulate_scenario` Boolean-operation
API remains unchanged. For externally supplied segments,
`simulation.compute_thermal.simulate_execution` validates and integrates them
without running the scheduler.

The event-driven scheduler orders jobs by deadline and stable identifier.
It enforces release, placement, fixed-rate capacity and pause constraints; a
bounded lookahead protects projected deadline feasibility before ranking local
heat opportunity. It is not a global optimizer or a guarantee that every
feasible workload will meet its deadline. Late work can continue, and completion
at the deadline is on time. No job migrates after placement. Running
non-interruptible jobs continue to completion, including through thermal
boundaries. Interruptible jobs with `None` or zero pause step can pause at any
progress point; positive steps restrict pauses to multiples of the step, except
that completion is always permitted. Real checkpoint persistence and process
control are not implemented.

For each site and interval, the scheduler uses `demand + storage capacity -
opening storage` as the useful-heat budget, less heat reserved by physical rack
ON-time unions. Candidates prefer less incremental dumped heat, then greater
remaining opportunity, then stable site/rack identifiers; consumer kind is
irrelevant. Critical work can run despite dumping. An admitted checkpoint step
or non-interruptible job may continue across an interval boundary when the next
interval has less opportunity. Compute events use elapsed UTC time with Python
datetime's microsecond resolution; unrepresentable execution or pause durations
are rejected rather than silently rounded outside work tolerances.

The integration counts overlapping jobs on the same rack once, aggregates actual
ON seconds to each thermal interval, then reuses the M2 site-local balance.
Demand and rack heat are treated as uniformly available within that interval;
this is not a sub-hour tank model. Rack usage reports work, ON time and
available-capacity utilization over the period and while ON; utilization is
undefined (`None`) when the corresponding capacity-time denominator is zero.
The scheduler does not resume saved progress across separate runs.

Repeatable synthetic annual benchmarks are available via
`uv run python scripts\benchmark_m3.py --jobs 100 --racks 10 --timeout 60`;
they use Python allocation tracing, Windows process peak working set and a
bounded child process, not measured real-job data. The benchmark currently
requires Windows.

`case_materials\compute-users-snapshot.csv` records the supplied
[ComputeUsers sheet](https://docs.google.com/spreadsheets/d/1kABU3xqjJ45U9bOY2UiuPWKNoFXd40pA8I6Qoe57P6w/edit?gid=977748296)
as accessed on 2026-11-21; blank cells remain unresolved, not zero. The user
confirmed that Bodycam's work and minimum interruptible step are 2,200 TFLOP
and 0.42 TFLOP; Local LLM profile entries represent average TFLOP/s for each
local hour and its zero pause step allows pausing at any progress point.
The sheet alone does not provide complete job arrivals or rack throughput.

## M2 site-local scenarios

Heat, thermal storage, dumping and backup belong to the site where production
and demand occur. Cross-site heat or storage transfer is prohibited. M2 models
ideal local delivery with no local losses or capacity constraints; it does not
implement distribution, scheduling or house-first dispatch. Callers explicitly
assign racks and their on/off sequences to sites.

`ThermalDemandSeries` contains nonnegative interval energies in kWh, timezone - aware interval boundaries, an identifier, and provenance with `unit="kWh"`.
`ReferenceDemand.as_demand_series()` converts the M1 reconstructed house profile;
`pool_demand()` accepts a caller-supplied per-pool series. Pool profiles are
inputs, not inferred from house data or physical pool equations. No implicit
resampling or missing-data replacement is performed.

Construct a `Scenario` from a tuple of `SiteGroup` objects. Each group represents
one or more identical independent sites: one supplied consumer series per site,
local storage capacity and initial energy, and zero or more `RackGroup` objects.
Each rack group has its own per-site count, electrical and thermal powers,
recovery efficiency, and explicitly timed Boolean operating sequence. Site
groups may have different rack counts, configurations, demand and storage.
Different inputs or initial states must be separate groups. M2 represents one
consumer series per site; a future multi-consumer site will need an explicit
local allocation model.

`simulate_scenario()` balances each representative site independently using the
same local allocation as M1, then multiplies flows by group quantity and sums
them by interval. Per-site-group results and scenario interval results are
retained separately; site and rack counts derive from assigned groups.
Timed demand and operation intervals must match by actual UTC instants across
the scenario, including DST folds. No cross-site energy flow is permitted.
Each site and aggregate interval checks the demand, recovered heat and storage
balances and gross = recovered + unrecovered heat, with the M1 tolerances.

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
