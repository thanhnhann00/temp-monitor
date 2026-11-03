"""SQLite storage: temperature history, alert log and cooling-mode events."""
from __future__ import annotations

import csv
import io
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from thermo.buffers import downsample
from thermo.model import Reading, finite

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (ts REAL NOT NULL, sensor_id TEXT NOT NULL, value REAL NOT NULL);
CREATE INDEX IF NOT EXISTS samples_sensor_ts ON samples(sensor_id, ts);
CREATE INDEX IF NOT EXISTS samples_ts ON samples(ts);
CREATE TABLE IF NOT EXISTS alert_log (id INTEGER PRIMARY KEY, sensor_id TEXT, started REAL, ended REAL, peak REAL);
CREATE TABLE IF NOT EXISTS cooling_events (ts REAL NOT NULL, mode TEXT NOT NULL, source TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path | str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            if path != ":memory:":
                self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, params=()) -> sqlite3.Cursor:
        with self._lock, self._db:
            return self._db.execute(sql, params)

    def _all(self, sql: str, params=()) -> list[tuple]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    # --- temperature history -------------------------------------------------
    def add_temps(self, ts: float, readings: list[Reading]) -> int:
        rows = [(ts, r.id, v) for r in readings if r.kind == "temperature" and (v := finite(r.value)) is not None]
        if rows:
            with self._lock, self._db:
                self._db.executemany("INSERT INTO samples VALUES (?, ?, ?)", rows)
        return len(rows)

    def prune(self, now: float, keep_s: int = 86_400) -> int:
        return self._exec("DELETE FROM samples WHERE ts < ?", (now - keep_s,)).rowcount

    def series(self, sensor_ids: list[str], since: float, max_points: int = 500) -> dict[str, list[tuple[float, float]]]:
        return {sid: downsample(self._all(
            "SELECT ts, value FROM samples WHERE sensor_id = ? AND ts >= ? ORDER BY ts", (sid, since)), max_points)
            for sid in sensor_ids}

    def hourly(self, sensor_id: str, hours: int, now: float) -> list[dict]:
        first_hour = (int(now) // 3600 - hours + 1) * 3600
        rows = self._all(
            "SELECT CAST(ts / 3600 AS INTEGER) * 3600 AS h, AVG(value) FROM samples "
            "WHERE sensor_id = ? AND ts >= ? GROUP BY h ORDER BY h", (sensor_id, first_hour))
        return [{"hour_ts": float(h), "avg": avg} for h, avg in rows]

    def export_csv(self, since: float) -> str:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        w.writerow(["timestamp", "sensor_id", "value_c"])
        for ts, sid, value in self._all("SELECT ts, sensor_id, value FROM samples WHERE ts >= ? ORDER BY ts", (since,)):
            w.writerow([datetime.fromtimestamp(ts).isoformat(timespec="seconds"), sid, round(value, 2)])
        return buf.getvalue()

    def sample_count(self) -> int:
        return self._all("SELECT COUNT(*) FROM samples")[0][0]

    # --- alerts --------------------------------------------------------------
    def alert_start(self, sensor_id: str, ts: float, value: float) -> int:
        return self._exec("INSERT INTO alert_log (sensor_id, started, peak) VALUES (?, ?, ?)",
                          (sensor_id, ts, value)).lastrowid

    def alert_update(self, alert_id: int, value: float) -> None:
        self._exec("UPDATE alert_log SET peak = MAX(peak, ?) WHERE id = ?", (value, alert_id))

    def alert_end(self, alert_id: int, ts: float) -> None:
        self._exec("UPDATE alert_log SET ended = ? WHERE id = ?", (ts, alert_id))

    def close_open_alerts(self, ts: float) -> int:
        return self._exec("UPDATE alert_log SET ended = ? WHERE ended IS NULL", (ts,)).rowcount

    def alerts(self, limit: int = 10) -> list[dict]:
        rows = self._all("SELECT id, sensor_id, started, ended, peak FROM alert_log ORDER BY started DESC, id DESC "
                         "LIMIT ?", (limit,))
        return [dict(zip(("id", "sensor_id", "started", "ended", "peak"), r)) for r in rows]

    # --- cooling -------------------------------------------------------------
    def log_cooling(self, ts: float, mode: str, source: str) -> None:
        self._exec("INSERT INTO cooling_events VALUES (?, ?, ?)", (ts, mode, source))

    def cooling_events(self, since: float) -> list[dict]:
        rows = self._all("SELECT ts, mode, source FROM cooling_events WHERE ts >= ? ORDER BY ts", (since,))
        return [{"ts": ts, "mode": m, "source": s} for ts, m, s in rows]
