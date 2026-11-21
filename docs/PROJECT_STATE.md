# Project state

## Persistent context rule

The repository is the authoritative persistent project memory; do not rely on
conversation history for architectural decisions. Keep this file concise and
decision-oriented, not a transcript. Update it before ending a milestone or
when context is becoming constrained.

After a context reset or at the start of a new AI session, read
`PROJECT_BRIEF.md` and this file; inspect relevant documentation, recent Git
history, and the active milestone's implementation and tests. Reconcile them
before making changes. Ask the user about material ambiguities or contradictions;
do not change an established decision because its original discussion is missing.
Continue to follow the brief's ask-before-guessing and milestone approval rules.

## Milestones and current status

- M0 foundation, M1 deterministic thermal kernel, M2 multi-unit site-local
  scaling, and M3 are accepted and committed. M1 and M2 remain mandatory
  regressions.
- M3 is the accepted deterministic ideal compute/scheduling and
  compute-to-thermal integration baseline. Its foundation was committed as
  `b9fb0c0` and its completion as `b673f29`.
- M4 real computational workload and process-control integration was accepted
  and committed as `1886f51` (worker foundation `cf593f2`). It does not
  complete the entire sprintd case.
- M5 economic and compute-income model was accepted and committed as `64a6009`.
- M6 parameter exploration was accepted and committed as `4e7038b`.
- M7 NiceGUI and Plotly demonstrator is implemented and awaiting review;
  not committed.

## M7 local interface

- The Dashboard is the shared settings workspace; simulation and bounded
  optimization run only on request, off the UI event loop. The reference
  baseline uses the reconstructed 2025 house and accepted tariff/heat value.
  Missing values stay unavailable; a pool requires its own supplied hourly
  profile, provenance and prices. Rack counts are explicitly per site.
- The Optimization view uses M6's result/coverage semantics and the same
  configuration. A separate labeled synthetic scenario demonstrates economic
  optimization. Default candidate budget is 25, maximum 625; annual hourly
  physical searches can still be slow and memory intensive.
- The Real Workload view starts only the registered Windows M4 demonstration
  with synthetic local heat signals; progress and runtime are as of the latest
  acknowledgment, and reference-rack energy is estimated. It does not expose
  arbitrary commands or reconnect via a stored PID. The server binds to
  localhost and has no authentication; use only on a trusted local machine.
- The UI does not create job arrivals or model effective throughput, pool
  physics, other years or market values. M3 scheduling is not configured by
  the initial Dashboard; without a workload, compute utilization/work is
  unavailable. Do not equate configured capacity with delivered work.
- Browser smoke on local Edge: reference simulation produced 6,105 kWh useful
  heat, 25,126.015625 kWh backup, 903 kWh dumped and 8,760 kWh electricity;
  annualized cost and income remained unavailable. Annual, storage, January
  and July plots rendered. Synthetic 625-candidate economic search reported
  the exhaustive CHF 1,948.16 optimum; a 10-candidate search reported the best
  evaluated candidate. Objective controls stayed synchronized across views.
  The registered worker completed 200,000 replicates, with 36.937 s measured
  active runtime, validated output and containment established before work;
  its journal is `artifacts\m4-ui\5e5ced6e44db433ab27020aa4a1796d6\journal.json`.

## M4 demonstrator and limitations

- The selected workload is local CPU analysis of the supplied weather data:
  temperature summary and seeded block-bootstrap regression of temperature
  against irradiance; this does not establish causation. Checkpoint restore is
  checksum- and identity-validated and has a deterministic regression test;
  replacement and checksums do not guarantee survival of power failure.
- The private Windows adapter gates useful work until the launcher and actual
  Python worker are contained in a kill-on-close job object. It validates
  execution IDs and command sequences, waits for acknowledgements, journals
  failures and uncertain periods, and never reattaches to a stored PID.
  The coordinator shares the M3 heat/deadline admission rule for a single
  arbitrary-pause job on an eligible rack, not the entire M3 multi-job policy.
  Callers must reevaluate on signal changes and at the returned permitted end.
- A 200,000-replicate real run took 40.438 s wall time and measured 36.578 s
  active runtime. Progress was 16,518 before the pause request, 16,580 at the
  acknowledgement, still 16,580 after a 3 s pause, and 200,000 at completion.
  Synthetic heat opportunity changes drove run/pause/resume; a checkpoint
  was confirmed at 16,580 and output hash, shape, summary and three regression
  samples were validated. No process restart occurred in this run.
- Configured reference rack, not measured host power: 1 kW electrical, 1 kW
  gross thermal and 0.8 recovery. From measured active runtime, electrical and
  gross thermal energy are each estimated as 0.0101605556 kWh; recoverable
  heat is derived as 0.0081284444 kWh. At the assigned synthetic site
  0.0081248889 kWh was directly used and 0.0000035556 kWh dumped during the
  pause-request delay; a second site received zero heat. Initialization and
  output writing count as active; checkpoint writing, paused waiting and
  controller-side validation do not. Missing power remains unavailable, not zero.
- Local evidence is in ignored `artifacts\m4\dbc4a2f2359e4b42834fc5acdcb1607c`
  (`journal.json`, `checkpoint.json`, `result.json`); the journal records
  input hash, parameters, command sequence, active intervals and classifications.
  These artifacts are not committed. TFLOP and effective-rate calibration are
  unavailable; no work is inferred from runtime or utilization.
- M4 verification: 151 tests passed and Ruff lint and format passed; M1/M2/M3
  regressions passed. Cooperative cancellation, abnormal exit, failed
  containment, timeout, forced child-tree cleanup, atomic journal replacement,
  checkpoint restart/corruption and site isolation were exercised by tests.
  The complete case still requires two specified workload types, sourced
  arrivals and scaling to the reference server, broader annual/financial
  demonstrator features and the remaining project milestones.

## M5 economics

- Finance accepts M2 site-local results, M3 integrated results, or M4 observed
  rack intervals with their physical rack inventory. It retains configured
  inputs/provenance, handles flat and aligned interval tariffs, explicit fixed
  and quantity-based costs including conditional bounds, and does not infer
  sold hours from rack ON time. Sold hours may not exceed unioned physical rack
  hours. Output identifies simulated versus estimated energy; no M4 energy is
  represented as physically metered.
- The supplied 2026 IWB Basel H4 screenshot shows 33.25 Rp/kWh, i.e.
  0.3325 CHF/kWh; access date unknown. The case heat-pump efficiency 2.5
  implies 0.133 CHF/kWh useful-heat value and backup price for that reference
  house. Do not silently use these assumptions for pools or other sites.
- Case break-even is `(rack electricity cost - useful heat value) / sold
  server-hours`, independently of CAPEX/service. Full-cost break-even is a
  separate figure. CAPEX and annual service/other OPEX accept fixed and
  quantity-dependent inputs. Annualized CAPEX uses the approved annuity with
  configured lifetime and discount rate, or straight-line when the rate is
  zero. Full-year results require a complete Zurich calendar year; shorter
  periods are not extrapolated. Empty cost lists explicitly mean zero;
  absent lists and parameters mean unavailable.
- Useful heat is direct delivery plus local storage discharge, not charging
  or dumped heat. Unknown opening storage origin makes discharged-heat value
  unavailable unless explicitly attributed to servers. Absolute cash
  contribution includes residual backup cost and does not also subtract
  avoided backup cost; heat revenue and avoided-heat perspectives are
  mutually exclusive. The avoided-heat full-cost break-even is incremental
  versus no-server heating; heat-revenue mode uses absolute backup cost.
- On the M1 reconstructed reference year, simulated electricity is 8,760 kWh,
  electricity cost CHF 2,912.70, useful heat 6,105 kWh, derived useful-heat
  value CHF 811.965 and backup cost CHF 3,341.760078125. Sold hours and actual
  compute prices are unknown. With explicitly illustrative 8,760 sold hours,
  the case break-even is 0.2398099315 CHF/server-hour, not a market price or
  observed sale. Full-cost break-even remains unavailable without costs,
  lifetime, discount rate, and service/other OPEX assumptions.
- M5 verification: 165 tests passed, including M1–M4 regressions; Ruff lint
  and format passed. The reference economic calculation was run with known
  inputs and separately with explicitly illustrative sold hours.

## M6 parameter exploration

- Deterministic global cross-group or group-only finite-grid search uses the
  existing M2/M3 physical models and M5 finance. A budget chooses exhaustive
  enumeration or bounded coarse-to-fine sampling; only the former establishes
  an optimum within the declared grid. Results retain all candidates, grouped
  parameters/provenance, constraints, scenario inputs, KPIs and financial
  amounts for a future UI. Unsupported optimization bindings are rejected.
- Economic objective minimizes annualized total cost, rejecting missing inputs.
  The independent thermal objective maximizes useful attributable server heat
  then minimizes dumped heat. Heat coverage is contextual. No attribution is
  invented for unknown discharged opening storage. M3 heuristic failures are
  schedule-specific, not proof of global infeasibility.
- The explicitly synthetic full-2025 two-interval benchmark uses one house,
  1–5 always-on racks and no M3 jobs. On Windows 11 / Python 3.12.16 / Intel
  Xeon 6737P, 125 candidates took 0.0277 s (4,507/s; 125 feasible, 0 rejected,
  100 physical-cache hits); 625 took 0.1433 s (4,363/s; 625 feasible, 0 rejected,
  600 hits). Economic optimum on the four-group grid: one rack, 4 kWh storage,
  CHF 100/rack CAPEX and CHF 4/server-hour, yielding CHF 1,948.16 annualized
  cost. Thermal optimum: two racks, 4 kWh storage, 5,000 kWh useful and
  9,012 kWh dumped; economic-only parameters tie at their lowest grid values.
  These synthetic results are not market recommendations. Benchmarks do not
  measure hourly annual M3 workloads; those may be unsuitable for interactive
  search, so M7 should initially use bounded spaces. Per-evaluator caching can
  consume substantial memory for many distinct annual physical scenarios.
- Unresolved actual rack and installation costs, service, other OPEX, lifetime,
  discount rate, sold hours, sale price, pool tariff/heat value, actual job
  arrivals and effective throughput still prevent a defensible real economic
  optimum. No additional optimization dependencies were added.
- M6 verification: 178 tests passed, including all M1–M5 regressions; Ruff
  lint and format checks passed.

## Permanent decisions and approved assumptions

- Modular monolith; domain and simulation independent of NiceGUI and input
  format. Configuration loading is behind a boundary. Objectives are independent
  of simulation and separately selectable; optimization is not M3 scope.
- Thermal energy, storage, dumping and backup are site-local. Heat never moves
  between sites; do not design inter-site thermal distribution. A site may
  eventually host multiple consumers. M2 currently uses one demand series per
  site, and groups sites only if all simulation-relevant inputs and initial
  states are identical.
- Reference-house reconstruction uses the supplied weather timestamps as fixed
  UTC+01:00, converted to Europe/Zurich; each temperature applies to the next
  elapsed hour. Heating days use all local-day samples, including 23/25-hour DST
  days, with the case's fixed 25.6 K denominator. Hot water is 12 kWh uniformly
  over each actual local day. This is not the unavailable official profile.
- M1 baseline: one always-on rack, 1 kW electrical and gross thermal power, 80%
  recovery, 35 kWh lossless local storage with no transfer limits and explicitly
  0 kWh initial energy. Direct heat serves demand first; only opening storage
  may discharge; charge becomes available next interval. Backup is heat required,
  not a modeled heater. Thermal balance tolerance: 1e-9 kWh absolute, 1e-12
  relative.
- Swimming pools are generic; M2 uses supplied, provenance-bearing per-pool
  thermal-demand series, not a physical pool model or house data.
- TFLOP is work; TFLOP/s is a rate. Compute capacity is distinct from electrical
  power, gross heat, recovery efficiency and income. No invented utilization
  power curve or compute-income formula.

## Approved M3 scope

- Keep layers separate: compute domain, deterministic reference scheduler,
  execution segments, compute/thermal integration, existing M2 thermal engine.
  Preserve the M1/M2 explicit rack-operation path and site-local balances.
- Jobs have explicit release, deadline, work, rate, eligibility and interruptibility;
  concurrent jobs may share one physical rack at fixed requested rates without
  exceeding available capacity. ON time is the union of execution segments, so
  concurrent jobs do not duplicate electricity or heat. No job migration after
  placement in M3. Unfinished late jobs may continue; completion at the deadline
  is on time.
- `None` and zero pause steps allow arbitrary-point pauses. Positive steps require
  interruptions at step multiples; completion need not coincide with a multiple.
  Pause/resume is simulated within a run, not persisted across separate runs;
  real checkpoint storage and process control are not implemented.
- Scheduler is consumer-type agnostic and a deterministic heuristic, not a global
  optimizer. Enforce release, eligibility, availability, capacity and permitted
  pauses first; protect predicted deadline feasibility before heat preference.
  Prefer lower predicted dumped heat, then greater remaining local opportunity,
  with earliest deadline and stable identifiers for ordering/ties. An earlier
  deadline may preempt at a permitted pause point. A running non-interruptible
  job continues even if heat is dumped. Deadline projection is greedy and cannot
  guarantee global feasibility; available rack capacity is static within a run.
- Per thermal interval, useful-heat budget is demand plus capacity minus opening
  storage, less already reserved recoverable heat, floored at zero. Reservations
  count unioned physical-rack ON time, not each concurrent job independently.
  A checkpointed job normally must fit its next permitted pause point or completion
  within the remaining budget; deadline-critical execution may exceed it and dump
  heat. Do not double-count demand or storage headroom.
- Sub-hour scheduling produces execution segments; integrate ON energy per
  original thermal interval and use the existing balance once per interval.
  Uniform intrainterval availability is an approved approximation, not a sub-hour
  tank model. Supply storage closing state to the next interval. Compute-driven
  scenarios use individually identified sites (quantity one), matching physical
  rack inventories and off Boolean operation inputs; the original M2 operation
  path remains available separately. Datetime event precision is microseconds.
- Use synthetic execution inputs until real arrivals and throughput are supplied.
  Real-process execution, measurement and scheduler-controlled interruption are
  later work, though required by the sprintd case. Exclude finance/income, tariffs,
  optimization, physical pool losses, major UI and production dashboards in M3.

## Accepted regressions and data

- M1 2025 baseline, kWh: space 26,851.015625; hot water 4,380; total demand
  31,231.015625; electrical and gross heat 8,760 each; recovered 7,008; direct
  5,861.6984375; charge and discharge 243.3015625 each; dumped 903; backup
  25,126.015625; final storage 0. Heating days: 206.
- M2 regression: one rack/house reproduces M1; independent site groups cannot
  exchange heat; grouped identical sites equal independent copies.
- Sprintd case: `case_materials/useful-load-useful-heat.txt`. Supplied weather:
  `case_materials/open-meteo-47.56N7.55E283m.csv`, SHA-256
  `cc99c5a387940e604bb8f7ffcb564397880f33586d54b8cc2764fb9b6b223693`.
  Preserve the raw file. Its source is Open-Meteo's historical archive; the
  export's publication/access dates are unknown.
- ComputeUsers snapshot: `case_materials/compute-users-snapshot.csv`; source
  and access date are documented in README. User confirmed Bodycam work of
  2,200 TFLOP, 168-hour deadline and 0.42-TFLOP interruptible step; Local LLM
  hourly values are average TFLOP/s and zero pause step permits arbitrary pause.
  Blank fields are unresolved, not zero.

## Open questions and last verification

- Job arrivals, effective throughput, real workload runtime/energy measurements,
  and complete sheet-row interpretations are not defined. Actual sold hours,
  compute sale price, rack/other hardware and installation costs, service and
  other OPEX, lifetime and discount rate, and pool tariffs/heat values remain
  unresolved. The official ready-made house profile remains unavailable;
  equivalence is unverified.
- Last verification on 2026-11-21: **187 tests passed**, including M1–M6
  regressions; Ruff lint and format checks passed.
- Synthetic annual benchmarks, traced Python allocations / Windows process peak
  working set: 100 jobs/10 racks 2.117 s, 12.77 / 81.57 MiB; 10,000/100 and
  100,000/1,000 each timed out after 60 s, at sampled peaks 9.80 / 64.13 MiB
  and 59.08 / 225.40 MiB respectively. Larger cases are not demonstrated
  practical; see `scripts/benchmark_m3.py` for the measurement method.
  Repeated rack/eligibility and deadline-projection scans are bottlenecks.
- Functional M3 correctness is accepted despite the current large-workload
  performance limitation. Performance optimization is deferred until real
  workload and optimizer requirements establish meaningful performance targets.
