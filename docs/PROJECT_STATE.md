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
- M4 real computational workload and process-control integration was approved
  and is **in progress, not complete or accepted**. The sprintd-required
  scheduler-controlled real-process demonstrator remains unimplemented.

## M4 work in progress

- The selected workload is local CPU analysis of the supplied weather data:
  temperature summary and seeded block-bootstrap regression of temperature
  against irradiance. The internal worker can acknowledge cooperative
  pause/resume, write a checksum-checked checkpoint, and restore it; its test
  verifies unchanged progress during an acknowledged pause and identical output
  after restart. Regression does not imply causation.
- `simulate_rack_intervals` integrates physical rack ON interval unions into
  the existing site-local thermal balance without fabricating ideal TFLOP work.
  Its power inputs are configured, not measured.
- This is not an end-to-end demonstrator: a real execution adapter with safe
  Windows process-tree containment, live M3 scheduler decisions and
  acknowledgement feedback, monotonic occupancy-to-thermal accounting,
  calibration/provenance, execution journal, and a complete demonstration are
  still needed. The worker's file replacement and checksum do not establish
  checkpoint durability across machine or power failure. It is not yet a safe
  public process-execution interface.
- The planned physical energy report must keep measured progress and runtime,
  configured power and efficiency, estimated electrical energy, and derived
  thermal values separate. Missing power must yield unavailable energy, not zero.
- Last M4 work-in-progress verification: 137 tests passed, Ruff lint and format
  passed, and the M1 annual reference values remained unchanged. This does not
  establish M4 acceptance.

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
  and complete sheet-row interpretations are not defined. The official
  ready-made house profile remains unavailable; equivalence is unverified.
- Last verification on 2026-11-21: **130 tests passed**, Ruff lint and format
  checks passed, the M1 annual baseline was reproduced, and M2 regressions passed.
- Synthetic annual benchmarks, traced Python allocations / Windows process peak
  working set: 100 jobs/10 racks 2.117 s, 12.77 / 81.57 MiB; 10,000/100 and
  100,000/1,000 each timed out after 60 s, at sampled peaks 9.80 / 64.13 MiB
  and 59.08 / 225.40 MiB respectively. Larger cases are not demonstrated
  practical; see `scripts/benchmark_m3.py` for the measurement method.
  Repeated rack/eligibility and deadline-projection scans are bottlenecks.
- Functional M3 correctness is accepted despite the current large-workload
  performance limitation. Performance optimization is deferred until real
  workload and optimizer requirements establish meaningful performance targets.
