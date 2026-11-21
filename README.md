# DigitalHeat Simulator

The local NiceGUI demonstrator provides Dashboard, Optimization and Real
Workload views over the M1–M6 models.

## Project context

The repository is the authoritative persistent project memory. Before starting
a new AI session or after a context reset, follow the mandatory recovery and
update procedure in [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md).

## Quick start

### Prerequisites

- [Git](https://git-scm.com/downloads) to clone the repository.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) installed and
  available on `PATH`. The simulator requires Python 3.12; uv can download
  it automatically if it is not already installed.
- A modern web browser and an internet connection for the initial Python and
  dependency downloads. NiceGUI, Plotly and the other Python packages are
  installed by uv; they do not need to be installed separately.

The local interface can be used without the Real Workload demonstration. That
demonstration uses the existing Windows-specific worker.

### Start the simulator

After cloning the repository, open PowerShell in its root directory and run:

```powershell
uv sync --no-dev
uv run --no-dev digitalheat-simulator
```

Keep the terminal open and go to **http://127.0.0.1:8080** in your browser.
On the Dashboard, select a starting scenario and press **Run Simulation**.
Stop the server with Ctrl+C in the terminal. If you change application code,
stop and start it again, then refresh the browser.

If uv was installed as a Python module rather than an executable on `PATH`,
use `python -m uv sync --no-dev` and
`python -m uv run --no-dev digitalheat-simulator` instead.

The server listens only on the local machine and has no authentication. Use
it on a trusted machine and do not expose it to a network.

### Prepare and share scenarios

In the Dashboard's **Scenario Files** area, use **Download Template** to
prepare your inputs, **Import Scenario** to load a CSV, and **Export Scenario**
to save the current configuration. Importing marks the configuration modified;
press **Run Simulation** explicitly to calculate results.

See [Scenario parameters and data preparation](docs/SCENARIO_PARAMETERS.md)
for the input checklist, required sources, CSV editing guidance and data still
needed for a real scenario. The template is distinct from the Reference House
and Synthetic Complete Demo starting scenarios.

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
- `finance`: explicit site-local tariffs, cost inputs and economic calculations.
- `optimization`: independently selectable economic and thermal grid searches.
- `application`: use-case services coordinating domain and adapters.
- `ui`: local NiceGUI interface and Plotly presentation.

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

M4 provides a narrow real-process demonstration using the M3 single-rack
heat/deadline admission rule. M5 adds a calculation-only finance model; M6
provides bounded deterministic parameter exploration. The complete sprintd
case still has unresolved inputs and workload requirements.

## M7 local interface

Start with `python -m uv run digitalheat-simulator`, then open
`http://127.0.0.1:8080`. The app binds to loopback and has no authentication:
use it only on a trusted local machine, do not expose it to a network, and do
not treat it as a multi-user or security-hardened service.

Dashboard settings are shared with Optimization. Editing marks the state
modified; Run Simulation and Find Sweet Spot are explicit actions. The default
is the reconstructed 2025 reference house with configured always-on racks per
house, not a scheduled compute workload. Missing prices, costs, sold hours and
compute work remain unavailable. A pool requires one user-supplied kWh value
per reference interval and a provenance source; pool prices are separate.
House and pool groups have distinct per-site rack counts and local storage.
Reference energy prices are not automatically applied to pools. Configured
compute capacity is shown as installed capacity, not work or income.

Select the clearly labeled synthetic demo to explore M6 using non-market
assumptions. Set the objective, enabled variables and ranges in Optimization;
the candidate budget is capped at 625 (default 25). Sampled results are only
the best evaluated candidate. Hourly annual scenarios may consume substantial
time and memory: start with small budgets. Switching starting scenario does not
automatically run anything.

### Scenario CSV and examples

The Dashboard's **Scenario Files** card contains **Import Scenario**,
**Export Scenario**, and **Download Template**. The template is a reference-
based starting point for your own data, not the Synthetic Complete Demo. See
[Scenario parameters](docs/SCENARIO_PARAMETERS.md) for a data-collection
checklist and spreadsheet guidance.

**Export Scenario** downloads the complete editable configuration, including
the other demo's stored parameter values, optimization ranges, objective,
candidate budget, and any supplied pool profile. It does not export calculated
KPIs or optimization results. **Import Scenario** validates the entire file
before replacing the shared Dashboard and Optimization settings. Import and
scenario selection mark the configuration modified, clear previous results,
and never start a run. Invalid files leave the current configuration unchanged.
Files are UTF-8 CSV, with standard quoting for commas and multiline pool
profiles; the upload limit is 2 MB. Start from an export or one of the files in
`src\digitalheat_simulator\config\defaults`.

The version 1 header is exactly:

```csv
version,kind,group,identifier,label,value,data_type,unit,enabled,optimizable,minimum,maximum,step,uncertainty_min,uncertainty_max,source,source_unit,publication_date,access_date,applicability,transformation,description,default
```

Every row has version `1`. `parameter` rows contain every supported input ID,
including empty values for unavailable optional inputs; types, groups, and
units must match the exported template. Integer values and bounds must be
whole numbers within JavaScript's safe integer range; other numeric values
must be finite. Nonempty values require a provenance `source`. ISO dates,
description, default, source unit, applicability, transformation, uncertainty
bounds, flags, and parameter bounds are optional where applicable. When
present, Boolean flags are exactly `true` or `false`. Required physical inputs
cannot be disabled; optional economic inputs and installed compute capacity
can be disabled, and editing one in the UI enables it again. Parameters without
a value cannot carry metadata, other than their standard label and unit.
An edited reference value must use its actual provenance rather than retain the
unchanged reference source.

`range` rows use the existing M6 group and parameter identifiers, the
corresponding type and unit, `enabled=true`, and `optimizable=true|false`.
The latter is the search checkbox. Active ranges require minimum, maximum
and positive step; range rows override parameter optimization metadata.
`setting` rows contain `mode`, `objective`, `budget`, `pool_source` and
`pool_profile`. A supplied profile must have exactly 8,760 nonnegative hourly
kWh values. All parameter and setting rows are required; range rows are
optional. Unknown, duplicated, malformed or unsupported rows are rejected,
including result rows. An active range must correspond to an input applicable
to the selected scenario. The exact header is versioned; future schemas
require an explicit version change. For example, the complete demo includes:

```csv
1,parameter,Hardware costs,hardware_costs:per_rack,Hardware per rack,12000.0,number,CHF/rack,,,,,,,,synthetic complete demonstration; not a market value,CHF/rack,,,illustrative only,,,
```

**Reference House** retains the accepted physical baseline and sourced
reference energy values, with unknown costs, sold hours and compute prices
unavailable. **Synthetic Complete Demo** uses the same house and explicitly
synthetic, non-market assumptions: 2 TFLOP/s per rack, CHF 12,000/rack
hardware, CHF 1,500 installation, CHF 300/year service, CHF 100/year other
OPEX, five-year lifetime, 4% discount rate, 4,000 sold server-hours and
CHF 0.30/server-hour. It enables an eight-candidate economic grid. Its
financial results are illustrative, not recommendations or sourced prices.
Utilization and compute work remain unavailable because no jobs are invented.
The separate original synthetic optimization demo is still available.

The Real Workload view can start only the existing registered M4 weather
demonstration on Windows. Its synthetic heat signal drives the existing
coordinator's start/pause/checkpoint/resume sequence; measured progress and
active time are shown as of the latest acknowledgement. Configured reference
power is not a host measurement. Energy is estimated and recovered heat is
derived; no TFLOP calibration or arbitrary executable is exposed. Journals
and output are placed under ignored `artifacts\m4-ui`. An interrupted server
does not reattach to a persisted PID; existing job-object cleanup applies.

## M5 economic calculations

`finance.model.evaluate` accepts an M2 `ScenarioResult` or M3
`IntegratedResult` plus `Economics` inputs, and returns itemized amounts with
units in their names and an unavailable reason where an input is missing. For
M4 observed occupancy, supply both `observed_intervals` and `observed_racks`;
the thermal result must match those intervals. Intervals are unioned per
physical rack. The result labels these energy quantities estimated, whereas
M2/M3 energy is simulated; neither is a physical meter reading.

Use explicit provenance-bearing `Parameter` values. Six extensible groups can be
mapped using `economics_from_groups`: `hardware_costs`, `installation_costs`,
`running_service_costs`, `energy_costs`, `finance_parameters`, and
`compute_income`. Cost keys are `fixed`, `per_rack`, `per_site`, `per_house`,
`per_pool`, with `service_` or `other_` prefixes for running costs. Prices
must use the corresponding `CHF`, `CHF/rack`, `CHF/site`, `CHF/house`,
`CHF/pool`, or per-year unit. Site-specific energy keys are
`electricity_price:<site>`, `heat_value:<site>` and `backup_price:<site>` in
`CHF/kWh`; finance keys are `lifetime_years`, `discount_rate`, and compute
keys are `sold_server_hours`, `price_per_server_hour`. For explicit zero costs,
use a provenance-bearing true `no_costs`, `service_no_costs` or
`other_no_costs`; an omitted input is unknown. Unrelated groups remain allowed.
The direct API additionally supports per-interval prices and additive cost
lines with inclusive quantity bounds. Price intervals must match exactly.

Physical rack ON time is not automatically sold. Sold server-hours must be
explicitly configured and no greater than the unioned physical rack hours.
Income is sold hours times configured CHF/server-hour, never installed TFLOP/s.
Useful heat is direct supply plus storage discharge, not heat merely stored or
dumped. If opening storage's server-heat origin is unknown and storage is
discharged, useful-heat-dependent results are unavailable unless its origin is
explicitly established. No heat is transferred between sites.

The case break-even is `(electricity cost - useful heat value) / sold hours`;
it deliberately excludes CAPEX and service. Full-cost break-even is separate:
for avoided-heat mode it is incremental cost versus the no-server heating
baseline; for heat-revenue mode it uses absolute site costs including residual
backup, less heat revenue. Absolute cash contribution and annualized total cost
include residual backup cost and do not subtract avoided heat a second time.
Avoided value and heat revenue are mutually exclusive scenario perspectives.
Zero sold hours yields an unavailable break-even; negative values are retained.
Annual service/OPEX and annualized total cost require a complete Zurich
calendar year. A shorter period is not extrapolated. Annualized CAPEX uses
the configured discount rate and lifetime, with straight-line CAPEX/lifetime
for a zero discount rate.

Reproduce the known reference figures without inventing costs or sale prices:

```powershell
uv run python -m digitalheat_simulator.application.reference_economics case_materials\open-meteo-47.56N7.55E283m.csv
```

For an illustrative—not actual—sale, add `--example-sold-hours 8760`. The
reference tariff is the supplied 2026 IWB H4 screenshot's 33.25 Rp/kWh
(0.3325 CHF/kWh); the access date is unknown. The case heat-pump efficiency
2.5 gives a derived heat value and backup price of 0.133 CHF/kWh. These
reference-house inputs are not automatically applied to pools. CAPEX,
service, lifetime, discount rate, sale price and other unsupplied costs remain
unavailable until explicitly configured. The reference baseline is reconstructed,
not the unavailable official ready-made house profile.

## M4 local workload demonstration

On Windows, run:

```powershell
uv run python -m digitalheat_simulator.application.real_demo --weather case_materials\open-meteo-47.56N7.55E283m.csv --output-root artifacts\m4
```

The registered worker computes a temperature summary and seeded block-bootstrap
regressions against irradiance; correlation is not causation. The demonstration
uses synthetic local heat signals and explicitly configured reference-rack
electrical power of 1 kW, gross thermal power of 1 kW and recovery efficiency
of 0.8. These are **not measurements** of the VM or host. The versioned JSON
journal records measured replicate progress and monotonic active runtime,
estimated electrical and gross thermal energy, and derived recoverable heat.
TFLOP work and effective throughput remain unavailable. Missing power inputs
produce unavailable energy values, not zero.

The live coordinator reuses M3's heat/deadline admission rule for one eligible
single-rack arbitrary-pause job; it does not implement M3's multi-job placement,
capacity contention or future-job projection. The caller must reevaluate when
the thermal signal changes or the returned permitted end is reached. The
demonstration uses bounded synthetic signals, not an annual real-time run.
Observed active intervals enter the existing site-local thermal balance; another
site receives no heat. Initialization and result writing are counted as active;
paused time, checkpoint writing and controller-side output validation are not.
Pausing is cooperative and the checkpoint is not a power-failure durability
guarantee.

Each execution has an isolated directory containing `journal.json`,
`checkpoint.json` and `result.json`. The adapter uses a Windows kill-on-close
job object and authorizes useful work only after containment. It attempts
cooperative cancellation before abnormal forced cleanup. A stored PID is never
used to reattach; recovery creates a new worker from a checksum- and
identity-validated checkpoint. The output validation checks the input identity,
output hash and shape, temperature summary, and three deterministic regression
samples, not a full independent recomputation. `artifacts\` is ignored by Git;
copy desired evidence elsewhere before cleaning local artifacts.

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
control are separate M4 features, not part of this ideal scheduler.

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
The M3 scheduler does not resume saved progress across separate runs.

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

## M6 parameter exploration

`digitalheat_simulator.optimization.search.search(groups, evaluator, objective,
budget=625, group=None)` returns immutable structured candidate and best-result
records, including groups and provenance, constraints, rejection reasons,
physical metrics, M5 economics and search coverage. `objective` is `"economic"`
or `"thermal"`; `group` limits variables to one group. Only enabled numeric
parameters explicitly marked optimizable with minimum, maximum and step are
searched. Others are fixed. The decimal grid starts at minimum and includes
maximum only if step-aligned; integer metadata must be integral. A full grid
within budget is exhaustive; otherwise deterministic stratified sampling and
local grid refinement returns the best evaluated candidate, not a global
optimum. Ties use ascending canonical group/parameter grid indices.
Explored values retain their source metadata with a transformation identifying
them as grid candidates, not sourced observations.

The economic objective minimizes M5 annualized total cost; unavailable inputs
reject a candidate. The thermal objective maximizes attributable useful server
heat, then minimizes dumped heat, without weighting. Both require a complete
Zurich calendar year. Heat coverage is a separate KPI and is unavailable for
zero demand. If discharged opening storage has unknown origin, useful server
heat is unavailable. Constraints report failures under the evaluated schedule,
not proof that no better schedule exists.

`application.optimization.ScenarioEvaluator` binds the following parameter
names to an explicitly supplied base scenario. Identifiers in bindings must
not contain colons:

| Group | Parameter identifier | Unit / meaning |
|---|---|---|
| `quantities` | `site_count:<site>` | integer count; zero removes the group |
| `quantities` | `rack_count:<site>:<rack-group>` | integer count per site |
| `storage` | `capacity_kwh:<site>` | kWh per site |
| `rack_technical` | `electrical_power_kw:<site>:<rack-group>`, `thermal_power_kw:<site>:<rack-group>` | kW per rack |
| `rack_technical` | `recovery_efficiency:<site>:<rack-group>` | dimensionless |

Economic group names and parameters use `finance.model.economics_from_groups`.
Provided economic groups replace the corresponding base cost category; flat
site-specific rates override the corresponding base rate. Omitted or disabled
parameters retain the explicit base configuration; missing inputs remain
missing. Unsupported optimizable bindings are rejected, not ignored.
Provenance is required for physical bindings and economic inputs.

With `jobs=None`, the evaluator uses each rack group's explicitly supplied
on/off sequence (M2). For M3 scheduling, pass explicit jobs and a `Capacity`
per site/rack-group; rack operation must be off. Site groups expand to
individually identified sites, and job eligibility is expanded from group IDs.
Work/deadline constraints default to required, but can be disabled explicitly.
Physical simulations are cached per evaluator by scenario, jobs and capacities;
economic-only changes reuse them. Results include source and evaluated
scenarios, and scheduled job/rack details. Cache lifetime and memory are
bounded by the evaluator instance, not automatically evicted. M5 may rerun
the M2 physical calculation when validating rack activity.

Run the explicitly synthetic two-interval annual demonstration and benchmarks:

```powershell
uv run python -m digitalheat_simulator.application.optimization_demo
```

Its prices and costs are not market data. The benchmark is not representative
of hourly annual M3 workloads; use a small candidate budget for interactive
use until the actual scenario is measured.

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
