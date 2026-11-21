import csv
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from digitalheat_simulator.data.reference_house import ZONE, load_weather, reconstruct_2025
from digitalheat_simulator.domain.thermal import Rack
from digitalheat_simulator.simulation.thermal import simulate

WEATHER = Path("case_materials") / "open-meteo-47.56N7.55E283m.csv"


def write_weather(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(
            [
                "latitude",
                "longitude",
                "elevation",
                "utc_offset_seconds",
                "timezone",
                "timezone_abbreviation",
            ]
        )
        writer.writerow(["47.557117", "7.549342", "283.0", "3600", "Europe/Berlin", "GMT+1"])
        writer.writerow([])
        writer.writerow(["time", "temperature_2m (°C)", "direct_normal_irradiance (W/m²)"])
        writer.writerows(rows)


def test_full_reference_year_and_dst(tmp_path):
    path = tmp_path / "weather.csv"
    start = datetime(2025, 1, 1)
    rows = []
    for i in range(8760):
        timestamp = start + timedelta(hours=i)
        if timestamp.date() == date(2025, 1, 1):
            temperature = 12
        elif timestamp.date() == date(2025, 1, 2):
            temperature = 25 if timestamp.hour == 0 else -10
        else:
            temperature = 0
        rows.append((timestamp.strftime("%Y-%m-%dT%H:%M"), temperature, 0))
    write_weather(path, rows)
    demand = reconstruct_2025(path, (True,) * 8760)
    assert len(demand.intervals) == 8760
    assert date(2025, 1, 1) not in demand.heating_days
    assert demand.intervals[0].space_demand_kwh == 0
    assert date(2025, 1, 2) in demand.heating_days
    assert demand.intervals[24].space_demand_kwh == 0
    assert demand.intervals[25].space_demand_kwh == pytest.approx(10 * 30 / 25.6)
    days = defaultdict(list)
    for item in demand.intervals:
        days[item.start.astimezone(ZONE).date()].append(item)
    assert len(days[date(2025, 3, 30)]) == 23
    assert len(days[date(2025, 10, 26)]) == 25
    for values in days.values():
        assert math.fsum(item.hot_water_demand_kwh for item in values) == pytest.approx(
            12, abs=1e-9
        )
    assert days[date(2025, 3, 30)][0].hot_water_demand_kwh == pytest.approx(12 / 23)
    assert days[date(2025, 10, 26)][0].hot_water_demand_kwh == pytest.approx(12 / 25)
    autumn = days[date(2025, 10, 26)]
    repeated = [
        item.start.astimezone(ZONE) for item in autumn if item.start.astimezone(ZONE).hour == 2
    ]
    assert len(repeated) == 2
    assert repeated[0].utcoffset() != repeated[1].utcoffset()
    assert reconstruct_2025(path, (True,) * 8760) == demand
    with pytest.raises(ValueError, match="rack operation"):
        reconstruct_2025(path, (True,))


@pytest.mark.parametrize(
    "rows",
    [
        [("2025-01-01T00:00", "", "0")],
        [("2025-01-01T00:00", "nan", "0")],
        [("2025-01-01T00:00", "1", "inf")],
        [("bad", "1", "0")],
        [("2025-1-1T00:00", "1", "0")],
        [("2025-01-01T00:00", "1", "0"), ("2025-01-01T00:00", "1", "0")],
        [("2025-01-01T00:00", "1", "0"), ("2025-01-01T02:00", "1", "0")],
        [("2025-01-01T01:00", "1", "0"), ("2025-01-01T00:00", "1", "0")],
        [("2025-01-01T00:00", "1")],
    ],
)
def test_bad_weather_rows_fail_with_line_context(tmp_path, rows):
    path = tmp_path / "bad.csv"
    write_weather(path, rows)
    with pytest.raises(ValueError, match="line"):
        load_weather(path)


def test_weather_metadata_and_full_year_are_required(tmp_path):
    path = tmp_path / "short.csv"
    write_weather(path, [("2025-01-01T00:00", 1, 0)])
    with pytest.raises(ValueError, match="entire Zurich"):
        reconstruct_2025(path, (True,))
    text = path.read_text(encoding="utf-8").replace("3600,Europe/Berlin", "7200,Europe/Berlin")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="fixed-offset"):
        load_weather(path)


def test_supplied_weather_baseline():
    if not WEATHER.exists():
        pytest.skip("user-supplied weather CSV is not present")
    demand = reconstruct_2025(WEATHER, (True,) * 8760)
    assert (
        demand.weather_sha256 == "cc99c5a387940e604bb8f7ffcb564397880f33586d54b8cc2764fb9b6b223693"
    )
    assert len(demand.heating_days) == 206
    assert math.fsum(item.space_demand_kwh for item in demand.intervals) == pytest.approx(
        26851.015625
    )
    assert math.fsum(item.hot_water_demand_kwh for item in demand.intervals) == pytest.approx(4380)
    run = simulate(demand.intervals, Rack(1, 1, 0.8), 35, 0)
    assert len(run.results) == 8760
    assert run.results[0].interval.start == datetime(2024, 12, 31, 23, tzinfo=UTC)
    for result in run.results:
        result.validate_balances()
        assert result.demand_kwh == pytest.approx(
            result.direct_supply_kwh + result.storage_discharge_kwh + result.backup_heat_kwh,
            rel=1e-12,
            abs=1e-9,
        )
        assert result.recoverable_heat_kwh == pytest.approx(
            result.direct_supply_kwh + result.storage_charge_kwh + result.dumped_heat_kwh,
            rel=1e-12,
            abs=1e-9,
        )
        assert result.storage_closing_kwh == pytest.approx(
            result.storage_opening_kwh + result.storage_charge_kwh - result.storage_discharge_kwh,
            rel=1e-12,
            abs=1e-9,
        )
