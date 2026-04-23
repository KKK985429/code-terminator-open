from __future__ import annotations

import math
import os
import time

from locust import LoadTestShape


class DayNightShape(LoadTestShape):
    TIME_SCALE = int(os.getenv("TIME_SCALE", "60"))

    def tick(self):
        compressed_day_seconds = 86400 / self.TIME_SCALE
        hour = (time.time() % compressed_day_seconds) / (3600 / self.TIME_SCALE)

        base = 20
        morning_peak = 50 * math.exp(-((hour - 9) ** 2) / 1.5)
        lunch_peak = 25 * math.exp(-((hour - 12) ** 2) / 2.0)
        evening_peak = 70 * math.exp(-((hour - 18) ** 2) / 2.0)
        night_valley = -15 * math.exp(-((hour - 3) ** 2) / 3.0)

        users = max(5, int(base + morning_peak + lunch_peak + evening_peak + night_valley))
        spawn_rate = max(2, users // 8)
        return users, spawn_rate
