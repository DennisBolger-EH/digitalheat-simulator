DigitalHeat Simulator
1. Project goal
Develop an interactive simulation and optimization application for the sprintd "Useful Load => Useful Heat" case.

Technology direction:

Python backend
NiceGUI frontend
Plotly visualization
Architecture must remain modular and testable
Other Python libraries are NOT predetermined and must be proposed by the implementation agent before being introduced.
The simulator investigates the relationship between:

useful computing work,
electricity consumption,
heat produced by computing infrastructure,
thermal demand,
infrastructure and operating costs,
compute income,
financial performance.
The simulator must support both thermal-demand scenarios:

reference houses;
swimming pools.
A swimming pool is an abstract configurable thermal consumer. The project does NOT model a specific physical swimming-pool facility.

2. Fundamental scalability requirement
The simulation must not be architected around exactly one rack, one house, or one swimming pool.

A rack, house, and swimming pool are unit models.

A scenario can contain configurable quantities of each.

Examples:

1 rack + 1 house
5 racks + 20 houses
50 racks + 200 houses + 2 swimming pools
250 racks + 1000 houses + 10 swimming pools
Quantities such as the following must be parameters:

number of computing racks;
number of houses;
number of swimming pools.
The architecture must allow larger simulation scenarios without requiring changes to the domain model or UI code.

Do NOT assume that all values scale linearly.

Support both:

unit-level parameters;
scenario/fleet-level parameters.
Future models may contain:

quantity discounts;
fixed versus variable costs;
shared thermal infrastructure;
distribution losses;
shared storage;
electrical capacity limits;
nonlinear maintenance costs;
utilization effects.
3. Computing rack model
One computing rack represents both:

a thermal-energy producer;
a provider of computing capacity.
Required configurable characteristics include, but are not necessarily limited to:

number of racks;
electrical power;
heat output;
heat-recovery efficiency;
compute capacity;
compute utilization;
hardware cost;
installation cost;
service cost.
Compute capacity is expressed using TFLOPS where appropriate.

IMPORTANT:

TFLOPS represents computing capacity and does NOT directly represent income.

The implementation must distinguish between:

available compute capacity;
utilization;
operating time;
compute work actually delivered;
workload/pricing model;
resulting income.
The final income formula must NOT be invented.

If the project data does not define the relationship between compute work and income, the implementation agent must ask the user or propose a model and request approval.

4. Thermal consumers
4.1 Reference house
Implement the reference-house requirements and data described by the sprintd case.

The house must be implemented as a reusable unit model.

The number of houses is configurable.

4.2 Swimming pool
The swimming pool is a generic configurable thermal consumer.

No real address, facility, or specific swimming-pool website is required.

Relevant properties will be supplied through configurable parameter groups.

The number of swimming pools is configurable.

The primary purpose is to compare swimming-pool heat demand against heat produced by computing racks.

5. Time model
Default assumptions:

hourly simulation;
annual simulation period;
Europe/Zurich timezone.
The baseline annual simulation therefore normally contains 8,760 hourly periods.

Do not hard-code this assumption into domain logic if a configurable time resolution can reasonably be supported.

6. Parameter groups
Parameters must be organized into extensible groups.

Initial examples:

Hardware costs
Installation costs
Running/service costs
Energy costs
Finance figures
Income parameters
Rack technical parameters
House parameters
Swimming-pool parameters
Thermal-storage parameters
Workload parameters
Groups are NOT a closed enumeration.

New parameter groups must be possible without redesigning the application.

Parameters within groups are also extensible.

7. Parameter metadata
Parameters may contain:

identifier
label
description
value
unit
data type
minimum
maximum
step
default
uncertainty range
optimizable flag
enabled/disabled state
source
source date/access date
applicable scenario/location
transformation information
Not every parameter needs every property.

Optional metadata must therefore remain optional.

Units must be explicit.

8. Units and defaults
Use:

English for code, UI, and documentation;
CHF for currency;
kWh / MWh for energy;
kW for thermal/electrical power where applicable;
degrees Celsius for temperature;
hourly simulation by default;
annual financial periods;
Europe/Zurich timezone.
Unit handling must be explicit.

Do not perform calculations involving ambiguous units.

9. Data provenance
Externally supplied values must retain provenance.

Where applicable store:

source;
publication/access date;
unit;
location/scenario applicability;
transformation performed.
Data supplied for the reference-house case must also be evaluated for the swimming-pool model where appropriate.

IMPORTANT:

If a referenced source cannot legitimately be applied to a swimming pool, DO NOT silently reuse it.

Instead:

identify the incompatibility;
propose an equivalent source or transformation;
explain the reasoning;
request user approval;
apply it only after approval.
Never fabricate physical, financial, workload, energy, or source data.

10. Optimization
The simulator must support optimization.

Mandatory
Calculate an overall/global optimum using parameters across all applicable parameter groups.

Initial optimization objective:

Minimize annualized total cost while satisfying:

required thermal demand;
workload/deadline constraints;
technical constraints.
The architecture must allow other objectives later, including:

maximum profit;
lowest CO2 emissions;
shortest payback period;
maximum computing-heat utilization;
multi-objective optimization;
Pareto frontier.
Optional where meaningful
Calculate an optimum within an individual parameter group.

Do not force individual-group optimization where it is mathematically meaningless.

Sensitivity analysis per parameter/group is desirable.

11. Expected simulation outputs
The detailed list must be refined during implementation planning.

The architecture should accommodate at least:

Thermal:

heat demand;
computer heat produced;
useful heat consumed;
excess/dumped heat;
backup heat required;
thermal-storage behavior.
Compute:

installed compute capacity;
available compute capacity;
utilized compute capacity;
delivered compute work;
utilization;
workload completion/deadline information.
Energy:

electrical consumption;
electricity costs.
Financial:

hardware costs;
installation costs;
service costs;
operating costs;
compute income;
annual cost;
profit/loss;
possible future NPV/payback calculations.
Optimization:

selected parameter combination;
objective value;
constraints;
sensitivity;
trade-offs.
12. UI
Use NiceGUI as the initial UI technology.

Use Plotly for interactive visualization unless the implementation plan identifies a strong reason to change it.

The UI must eventually allow users to:

select a scenario;
configure quantities;
configure parameter groups;
edit parameter values;
enable optimization parameters;
start simulations;
compare simulation runs;
inspect charts;
inspect financial results;
inspect optimization results;
inspect data provenance.
Do NOT put domain calculations directly into NiceGUI event handlers.

13. Architecture
Prefer a modular-monolith architecture initially.

Separate at least:

domain models;
simulation engine;
optimization;
workload/computing model;
financial calculations;
configuration;
data ingestion/provenance;
application/use-case services;
NiceGUI presentation.
The simulation engine must not depend on NiceGUI.

The optimization engine must operate on domain/application interfaces rather than UI controls.

Avoid unnecessary infrastructure.

Do not introduce:

cloud services;
Kubernetes;
external databases;
microservices;
message brokers;
separate JavaScript frontend
unless an approved architectural decision justifies them.

14. Testing
Calculations must be independently testable without running NiceGUI.

Use automated tests.

Prioritize tests for:

unit conversion;
heat-balance calculations;
aggregation from unit to fleet;
financial calculations;
workload calculations;
optimization constraints;
boundary values;
parameter validation;
deterministic simulation behavior.
Numerically important calculations should have known-input / known-output tests.

15. Input data formats
Input formats are intentionally NOT predetermined.

The implementation agent must evaluate requirements and propose appropriate formats.

Possible formats include CSV, YAML, JSON, or other justified formats.

Do not choose a format simply because it is convenient.

Present the proposed format and reasoning in the implementation plan and wait for approval.

16. AI implementation rules
The project is intended to be implemented with an AI coding agent.

The following workflow is mandatory.

ASK INSTEAD OF GUESS
If information materially affects:

physical calculations;
architecture;
financial calculations;
optimization;
units;
external data;
business rules;
workload behavior;
acceptance criteria
and it is not defined, ASK.

Never silently invent a requirement.

PLAN BEFORE IMPLEMENTATION
For every significant milestone:

inspect PROJECT_BRIEF.md;
inspect existing documentation;
inspect existing code and tests;
identify ambiguities;
ask necessary questions;
prepare an implementation plan;
identify files to create/change;
identify dependencies to introduce;
define tests;
define acceptance criteria;
present the plan to the user;
STOP.
Do not implement until the user explicitly approves the plan.

IMPLEMENT AFTER APPROVAL
After approval:

implement only the approved scope;
prefer small vertical slices;
add/update tests;
run tests;
run quality checks;
report changed files;
report test results;
report assumptions;
report unresolved questions;
request approval before materially expanding scope.
17. Initial implementation milestone
The first milestone is:

M0 - Project foundation and requirements baseline.

DO NOT immediately implement the simulator.

First prepare an M0 implementation plan covering:

recommended Python version;
dependency management;
project structure;
modular architecture;
configuration approach;
input-data formats;
parameter/group representation;
units strategy;
provenance model;
house abstraction;
swimming-pool abstraction;
rack abstraction;
TFLOPS/workload model;
financial model boundaries;
simulation time model;
scaling strategy;
optimization-library alternatives;
testing strategy;
NiceGUI integration;
Plotly integration;
development commands;
Git workflow.
For every new third-party dependency explain:

why it is needed;
which requirement it satisfies;
alternatives considered.
Present M0 to the user and STOP.

Wait for explicit approval before creating production code.