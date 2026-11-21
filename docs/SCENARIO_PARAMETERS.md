# Scenario data preparation

Use **Dashboard → Scenario Files → Download Template** to get an importable
starting file. Reference House is an approved reference baseline; Synthetic
Complete Demo contains explicitly synthetic demonstration values. The
template starts from the reference baseline, leaves unknown real values empty,
and includes four separately labeled synthetic-demo rows that are inactive in
reference mode. It is not a complete real economic scenario.

Open the UTF-8 CSV in a text editor, Excel, LibreOffice Calc or similar.
When importing into a spreadsheet, choose comma delimiter, double-quote
quoting, UTF-8, and a dot decimal separator; export as UTF-8 comma-separated
CSV without changing the header, row order/IDs, types or units. Some locales
default to semicolons or decimal commas: explicitly select comma/dot. Keep IDs
and provenance fields as text; do not let date or numeric formatting alter
them. The `pool_profile` setting is a single quoted multiline cell when used:
8,760 newline-separated values; editing this long cell is easier in a text
editor or Dashboard. There is no serialized JSON. Spreadsheet applications
were not available in the verification environment, so their import/export
dialogs were not exercised.

Edit `value` and set `source` to the actual origin for each populated input.
When replacing a reference value, change its reference source and clear or
update `source_unit`, dates, applicability and transformation as appropriate.
For unknown optional values leave the value and metadata blank. Do not remove
rows. When known to be zero, enter `0` with a source; blank means unavailable,
not zero. The optional `description` column is available for populated
parameter rows. CSV imports do not authenticate source claims.

**Reading the inventory:** R means required for a valid scenario; O means
optional unless a stated calculation requires it. All numeric input values
must be finite and nonnegative. Integers must be whole and at most
9,007,199,254,740,991. Unless otherwise stated there is no fixed upper bound.
Every supplied value needs a nonempty source; unchanged reference and demo
values already carry it. “Yes” in the optimization column means a range can
be chosen when the relevant site and value are present and enabled. A range
must be finite, ordered, have a positive step and fit the candidate budget.
Reference classifications below describe the **template**, not a claim that
the assumptions apply to your site.

## Scenario

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `houses` | Houses; number of identical reference-house sites | integer; count | R; houses + pools >= 1 | 1; approved reference assumption | Yes |
| `pools` | Swimming pools; number of identical pool sites | integer; count | R; profile and source required if > 0 | 0; user input | Yes, when pool exists |
| `racks` | Racks per house; always-on racks per house | integer; count | R | 1; approved reference assumption | Yes |
| `pool_racks` | Racks per pool; always-on racks per pool | integer; count | R | 0; user input | Yes, when pool exists |
| `storage` | Storage capacity per house | number; kWh | R | 35; approved reference assumption | Yes |
| `initial` | Initial storage per house; must not exceed `storage` | number; kWh | R | 0; approved reference assumption | No |

House demand is the existing reconstructed 2025 weather/reference-house
profile, not an editable input in this UI. It is not an authoritative measured
profile for every house. Its energy is simulated locally for each house.

## Rack / Compute

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `electrical` | Electrical power per rack while on | number; kW | R | 1; approved reference assumption | Yes |
| `thermal` | Gross thermal power per rack while on | number; kW | R | 1; approved reference assumption | Yes |
| `efficiency` | Heat recovery efficiency; inclusive 0–1 | number; dimensionless | R | 0.8; approved reference assumption | Yes |
| `capacity` | Compute capacity per rack, not delivered work | number; TFLOP/s | O | unavailable | No |

The same rack power and efficiency apply to house and pool racks. Capacity
alone does not create workload, compute utilization or delivered TFLOP.

## Thermal consumers

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `pool_storage` | Storage capacity per pool | number; kWh | R, including when pools = 0 | 0; user input | Yes, when pool exists |
| `pool_initial` | Initial storage per pool; <= `pool_storage` | number; kWh | R, including when pools = 0 | 0; user input | No |
| `pool_profile` | Pool thermal demand per interval per pool; one value per line, aligned with the 2025 reference intervals | setting string; kWh | Required if pools > 0; exactly 8,760 finite nonnegative numbers | unavailable | No |
| `pool_source` | Source and applicability of the pool profile | setting string; no unit | Required if pools > 0 | unavailable | No |

`pool_profile` and `pool_source` are `kind=setting` rows in the template, not
parameter rows; keep their type `string` and unit cell empty. Never use house
demand or prices for a pool without establishing applicability.

## Energy

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `electricity_price:house` | House electricity tariff | number; CHF/kWh | O; needed for house electricity cost | 0.3325; sourced 2026 IWB Basel H4 screenshot | Yes |
| `heat_value:house` | Value of useful house heat | number; CHF/kWh | O; needed for useful-heat value and heat-dependent economics | 0.133; calculated from reference tariff / 2.5 | Yes |
| `backup_price:house` | House backup heat price | number; CHF/kWh | O; needed for backup cost and total economics | 0.133; calculated from reference tariff / 2.5 | Yes |
| `electricity_price:pool` | Pool electricity tariff | number; CHF/kWh | O; needed for pool electricity cost | unavailable | Yes, when pool exists |
| `heat_value:pool` | Pool useful-heat value | number; CHF/kWh | O; needed for pool heat-dependent economics | unavailable | Yes, when pool exists |
| `backup_price:pool` | Pool backup heat price | number; CHF/kWh | O; needed for pool backup cost and total economics | unavailable | Yes, when pool exists |

Reference tariff applicability must be checked for a real location and period.
Changing it does **not** automatically recompute the two heat prices.

## Hardware costs

Supply one or more applicable cost components; components are added. If there
really is no cost, enter a sourced zero in an applicable field. These are
optional for thermal simulation but at least one explicit hardware component
is needed for available CAPEX and annualized economics. All are `number`,
nonnegative, reference value **unavailable**, source required if populated,
and optimizable when populated.

| ID | Display name / meaning | Unit |
|---|---|---|
| `hardware_costs:fixed` | Hardware fixed; one scenario-wide amount | CHF |
| `hardware_costs:per_rack` | Hardware per rack; multiplied by rack count | CHF/rack |
| `hardware_costs:per_site` | Hardware per site; multiplied by all sites | CHF/site |
| `hardware_costs:per_house` | Hardware per house; multiplied by houses | CHF/house |
| `hardware_costs:per_pool` | Hardware per pool; multiplied by pools | CHF/pool |

## Installation costs

These are additive, optional for thermal simulation, but at least one
explicit component is needed for available CAPEX. All are `number`,
nonnegative, reference value **unavailable**, source required if populated,
and optimizable when populated. Use a sourced zero if the cost is known zero.

| ID | Display name / meaning | Unit |
|---|---|---|
| `installation_costs:fixed` | Installation fixed; scenario-wide | CHF |
| `installation_costs:per_rack` | Installation per rack | CHF/rack |
| `installation_costs:per_site` | Installation per site | CHF/site |
| `installation_costs:per_house` | Installation per house | CHF/house |
| `installation_costs:per_pool` | Installation per pool | CHF/pool |

## Service / OPEX

Within each of service and other OPEX, supplied components are additive;
both categories need at least one explicit value for complete annual
economics. All are `number`, nonnegative, reference value **unavailable**,
optional for thermal simulation, require a source when populated, and are
optimizable when populated. Use a sourced zero if a category is known to cost
nothing.

| ID | Display name / meaning | Unit |
|---|---|---|
| `running_service_costs:fixed` | Service fixed per year | CHF/year |
| `running_service_costs:per_rack` | Service per rack per year | CHF/rack/year |
| `running_service_costs:per_site` | Service per site per year | CHF/site/year |
| `running_service_costs:per_house` | Service per house per year | CHF/house/year |
| `running_service_costs:per_pool` | Service per pool per year | CHF/pool/year |
| `other_opex:fixed` | Other OPEX fixed per year | CHF/year |
| `other_opex:per_rack` | Other OPEX per rack per year | CHF/rack/year |
| `other_opex:per_site` | Other OPEX per site per year | CHF/site/year |
| `other_opex:per_house` | Other OPEX per house per year | CHF/house/year |
| `other_opex:per_pool` | Other OPEX per pool per year | CHF/pool/year |

## Finance

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `lifetime_years` | Hardware lifetime for annualization; must be > 0 for economics | number; year | O for thermal; needed for annualized CAPEX | unavailable | Yes |
| `discount_rate` | Annual discount rate as a ratio, e.g. 0.04 means 4%; >= 0 | number; dimensionless | O for thermal; needed for annualized CAPEX | unavailable | Yes |

## Compute income

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `sold_server_hours` | Contracted sold server-hours, not inferred from rack-on time; <= physical rack hours | number; server-hour | O for thermal; needed for income and break-even | unavailable | Yes |
| `price_per_server_hour` | Compute sale price per sold server-hour | number; CHF/server-hour | O for thermal; needed for income | unavailable | Yes |

Zero sold hours leaves break-even unavailable. Neither value establishes actual
jobs, utilization, delivered work or effective compute throughput.

## Optimization

| ID | Display name / meaning | Type; unit | Required | Template value; classification | Optimizable |
|---|---|---|---|---|---|
| `objective` | Objective: `economic` or `thermal` | setting string; none | R | `economic`; user input | Not applicable |
| `budget` | Candidate budget; whole number 1–625 | setting integer; none | R | 25; user input | Not applicable |
| `mode` | `reference` for the house/pool workspace; `synthetic` for the separate old demonstration | setting string; none | R | `reference`; user input | Not applicable |

Optimization **range** rows use M6 group/ID rather than Dashboard IDs. The
template contains an inactive example for `quantities` /
`rack_count:house:rack`: integer count, `enabled=true`, `optimizable=false`,
with empty bounds. For example, enter minimum 1, maximum 2 and step 1 and
set `optimizable=true` to search it; these would be illustrative search
bounds, not measured data. The referenced site and parameter must be
applicable. Other ranges are easiest to configure in
the Optimization view and export. The search checkbox, minimum, maximum and
step are stored in the shared scenario. Range rows override parameter-row
optimization metadata. Active ranges require all three bounds; the current
value must remain within declared bounds.

## Separate synthetic optimization demo

These four `parameter` rows are required in all version-1 files to preserve
the separate synthetic demo's state, but do not alter the reference-house
scenario. Their source is **synthetic demonstration; not a market value**;
all are optional to adjust and optimizable in synthetic mode.

| Group / ID | Display name / meaning | Type; unit | Template value | Demo range (min–max; step) |
|---|---|---|---|---|
| `synthetic/quantities` / `synthetic:quantities:rack_count:house:rack` | Synthetic racks per house | integer; count | 1 | 1–5; 1 |
| `synthetic/storage` / `synthetic:storage:capacity_kwh:house` | Synthetic storage capacity | number; kWh | 0 | 0–4; 1 |
| `synthetic/hardware_costs` / `synthetic:hardware_costs:per_rack` | Synthetic hardware per rack | number; CHF/rack | 100 | 100–500; 100 |
| `synthetic/compute_income` / `synthetic:compute_income:price_per_server_hour` | Synthetic compute sale price | number; CHF/server-hour | 0 | 0–4; 1 |

## Data still needed for a complete real scenario

- **Rack hardware CAPEX and installation costs:** needed for CAPEX,
  annualized total cost, full-cost break-even and economic optimization.
- **Annual service and other OPEX:** needed for annualized total cost,
  full-cost break-even and economic optimization; provide both categories,
  including sourced zero if appropriate.
- **Hardware lifetime and discount rate:** needed for annualized CAPEX,
  annualized total cost, full-cost break-even and economic optimization.
- **Actual compute sale price and sold server-hours:** needed for compute
  income and relevant full economics; sold hours are also needed for
  break-even. Establish contractual hours independently of physical rack
  hours. The Dashboard economic objective also requires these inputs.
- **Real rack compute capacity:** needed to show installed TFLOP/s. Actual
  utilization and work additionally need scheduled jobs and throughput
  assumptions; capacity alone is insufficient.
- **Site-appropriate electricity tariff, useful-heat value and backup heat
  price:** needed for electricity/backup costs, heat value and economic
  comparisons. Verify the reference-house values for the actual site.
- **Pool profile and its source:** needed for any enabled pool thermal
  simulation. Pool electricity tariff, useful-heat value and backup price are
  separately needed for pool economics and economic optimization.
- **Actual workload arrivals, demand, deadlines and effective throughput /
  calibration:** needed for realistic scheduling, utilization and delivered
  work. The Dashboard cannot yet configure these inputs; the registered M4
  weather workload is a controlled demonstration, not a real arrivals model.
- **Applicable house demand/weather and actual rack power/recovery
  measurements:** needed for a defensible real-site physical estimate. The
  present Dashboard uses the 2025 reconstructed reference house and configured
  rack assumptions; it does not accept a replacement house profile.
