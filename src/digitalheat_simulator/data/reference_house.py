"""Approved 2025 Basel weather-to-demand reconstruction."""

import csv
import hashlib
import io
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from digitalheat_simulator.domain.parameters import Provenance
from digitalheat_simulator.domain.scenario import DemandPoint, Interval, ThermalDemandSeries
from digitalheat_simulator.domain.thermal import ThermalInterval

ZONE = ZoneInfo("Europe/Zurich")
OFFSET = timezone(timedelta(hours=1))
HOUR = timedelta(hours=1)


@dataclass(frozen=True)
class WeatherSample:
    start: datetime
    temperature_c: float


@dataclass(frozen=True)
class ReferenceDemand:
    intervals: tuple[ThermalInterval, ...]
    heating_days: tuple[date, ...]
    weather_sha256: str
    weather_metadata: tuple[tuple[str, str], ...]
    transformation: str

    def as_demand_series(self) -> ThermalDemandSeries:
        return ThermalDemandSeries(
            identifier="reconstructed-reference-house",
            points=tuple(
                DemandPoint(
                    Interval(item.start, item.end),
                    item.space_demand_kwh + item.hot_water_demand_kwh,
                )
                for item in self.intervals
            ),
            provenance=Provenance(
                source=f"Open-Meteo supplied weather CSV SHA-256 {self.weather_sha256}",
                unit="kWh",
                applicability="2025 Basel reconstructed reference house",
                transformation=self.transformation,
            ),
        )


def load_weather(path: Path) -> tuple[tuple[WeatherSample, ...], str, tuple[tuple[str, str], ...]]:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    try:
        header = next(reader)
        values = next(reader)
        blank = next(reader)
        fields = next(reader)
    except StopIteration as exc:
        raise ValueError("weather CSV is missing metadata or header") from exc
    expected_metadata = [
        "latitude",
        "longitude",
        "elevation",
        "utc_offset_seconds",
        "timezone",
        "timezone_abbreviation",
    ]
    expected_fields = ["time", "temperature_2m (°C)", "direct_normal_irradiance (W/m²)"]
    if (
        header != expected_metadata
        or len(values) != len(header)
        or blank
        or fields != expected_fields
    ):
        raise ValueError("unexpected weather CSV metadata or data columns")
    metadata = dict(zip(header, values, strict=True))
    if any(not value.strip() for value in values):
        raise ValueError("weather CSV metadata must not be empty")
    if metadata["utc_offset_seconds"] != "3600" or metadata["timezone"] != "Europe/Berlin":
        raise ValueError("weather CSV does not match the approved fixed-offset baseline")
    samples = []
    previous = None
    for row in reader:
        line = reader.line_num
        if len(row) != 3 or any(not item.strip() for item in row):
            raise ValueError(f"weather CSV line {line}: expected three nonempty fields")
        try:
            naive = datetime.strptime(row[0], "%Y-%m-%dT%H:%M")
            temperature = float(row[1])
            irradiance = float(row[2])
        except ValueError as exc:
            raise ValueError(
                f"weather CSV line {line}: invalid timestamp or numeric value"
            ) from exc
        if naive.strftime("%Y-%m-%dT%H:%M") != row[0]:
            raise ValueError(f"weather CSV line {line}: timestamp must use YYYY-MM-DDTHH:MM")
        if not math.isfinite(temperature) or not math.isfinite(irradiance):
            raise ValueError(f"weather CSV line {line}: values must be finite")
        instant = naive.replace(tzinfo=OFFSET).astimezone(UTC)
        if previous is not None and instant - previous != HOUR:
            raise ValueError(f"weather CSV line {line}: expected a consecutive hourly timestamp")
        samples.append(WeatherSample(instant, temperature))
        previous = instant
    if not samples:
        raise ValueError("weather CSV contains no observations")
    return tuple(samples), digest, tuple(zip(header, values, strict=True))


def reconstruct_2025(path: Path, rack_operation: tuple[bool, ...]) -> ReferenceDemand:
    samples, digest, metadata = load_weather(path)
    expected_start = datetime(2025, 1, 1, tzinfo=ZONE).astimezone(UTC)
    expected_end = datetime(2026, 1, 1, tzinfo=ZONE).astimezone(UTC)
    if samples[0].start != expected_start or samples[-1].start + HOUR != expected_end:
        raise ValueError("weather CSV must cover the entire Zurich 2025 calendar year")
    if len(rack_operation) != len(samples) or any(type(on) is not bool for on in rack_operation):
        raise ValueError("rack operation must supply one boolean per weather sample")
    by_day: dict[date, list[WeatherSample]] = defaultdict(list)
    for sample in samples:
        by_day[sample.start.astimezone(ZONE).date()].append(sample)
    heating_days = tuple(
        day
        for day, day_samples in by_day.items()
        if math.fsum(sample.temperature_c for sample in day_samples) / len(day_samples) < 12
    )
    heating_set = set(heating_days)
    intervals = []
    for sample, rack_on in zip(samples, rack_operation, strict=True):
        local_day = sample.start.astimezone(ZONE).date()
        space_power_kw = (
            max(0.0, 10.0 * (20.0 - sample.temperature_c) / 25.6)
            if local_day in heating_set
            else 0.0
        )
        intervals.append(
            ThermalInterval(
                start=sample.start,
                end=sample.start + HOUR,
                space_demand_kwh=space_power_kw * (HOUR / timedelta(hours=1)),
                hot_water_demand_kwh=12.0 / len(by_day[local_day]),
                rack_on=rack_on,
            )
        )
    return ReferenceDemand(
        intervals=tuple(intervals),
        heating_days=heating_days,
        weather_sha256=digest,
        weather_metadata=metadata,
        transformation=(
            "M1 reconstructed baseline: fixed UTC+01:00 labels; sample held for the following "
            "hour; Zurich local-day sample mean <12 C; case formula with 25.6 K; "
            "12 kWh hot water uniformly per local day. Not the official ready-made profile."
        ),
    )
