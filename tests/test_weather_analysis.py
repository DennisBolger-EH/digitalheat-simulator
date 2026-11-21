from pathlib import Path

import pytest

from digitalheat_simulator.workload.weather_analysis import WeatherAnalysis

WEATHER = Path("case_materials") / "open-meteo-47.56N7.55E283m.csv"


def test_weather_analysis_is_seeded_and_reproducible():
    if not WEATHER.exists():
        pytest.skip("user-supplied weather CSV is not present")
    analysis = WeatherAnalysis.load(WEATHER, 24)
    assert analysis.sha256 == "cc99c5a387940e604bb8f7ffcb564397880f33586d54b8cc2764fb9b6b223693"
    assert analysis.summary()["count"] == 8760
    assert analysis.replicate(42, 0) == analysis.replicate(42, 0)
    assert analysis.replicate(42, 0) != analysis.replicate(42, 1)


def test_weather_analysis_rejects_bad_block_size():
    if not WEATHER.exists():
        pytest.skip("user-supplied weather CSV is not present")
    with pytest.raises(ValueError, match="block size"):
        WeatherAnalysis.load(WEATHER, 0)
