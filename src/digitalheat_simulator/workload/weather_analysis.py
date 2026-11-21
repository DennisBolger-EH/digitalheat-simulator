"""Reproducible block-bootstrap regression over the supplied weather data."""

import csv
import hashlib
import io
import math
import random
from dataclasses import dataclass
from pathlib import Path

from digitalheat_simulator.data.reference_house import load_weather

ALGORITHM_VERSION = "weather-block-regression-1"


@dataclass(frozen=True)
class WeatherAnalysis:
    sha256: str
    temperatures: tuple[float, ...]
    blocks: tuple[tuple[int, float, float, float, float], ...]
    block_size: int

    @classmethod
    def load(cls, path: Path, block_size: int) -> "WeatherAnalysis":
        if type(block_size) is not int or block_size < 1:
            raise ValueError("block size must be a positive integer")
        samples, digest, _ = load_weather(path)
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError("weather data changed during loading")
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        for _ in range(4):
            next(reader)
        pairs = tuple(
            (float(row[2]), sample.temperature_c)
            for row, sample in zip(reader, samples, strict=True)
        )
        if block_size > len(pairs):
            raise ValueError("block size exceeds observation count")
        blocks = []
        for offset in range(0, len(pairs), block_size):
            part = pairs[offset : offset + block_size]
            blocks.append(
                (
                    len(part),
                    math.fsum(x for x, _ in part),
                    math.fsum(y for _, y in part),
                    math.fsum(x * x for x, _ in part),
                    math.fsum(x * y for x, y in part),
                )
            )
        return cls(
            digest, tuple(sample.temperature_c for sample in samples), tuple(blocks), block_size
        )

    def replicate(self, seed: int, index: int) -> tuple[float, float]:
        """Resample contiguous blocks, retaining partial final blocks and pairs."""
        generator = random.Random(f"{ALGORITHM_VERSION}:{seed}:{index}")
        sampled = [self.blocks[generator.randrange(len(self.blocks))] for _ in self.blocks]
        n = sum(block[0] for block in sampled)
        sx, sy, sxx, sxy = (math.fsum(block[i] for block in sampled) for i in range(1, 5))
        denominator = n * sxx - sx * sx
        if denominator <= 0:
            raise ValueError("bootstrap sample has no irradiance variation")
        slope = (n * sxy - sx * sy) / denominator
        intercept = (sy - slope * sx) / n
        return intercept, slope

    def summary(self) -> dict[str, float | int]:
        return {
            "count": len(self.temperatures),
            "minimum_c": min(self.temperatures),
            "maximum_c": max(self.temperatures),
            "mean_c": math.fsum(self.temperatures) / len(self.temperatures),
        }
