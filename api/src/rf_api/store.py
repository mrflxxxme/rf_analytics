"""Активный snapshot витрин: `marts/current` → каталог с manifest.json и *.parquet.

Симлинк `current` переключается атомарно (deploy/publish-snapshot.sh); API замечает смену
на следующем запросе и открывает новый snapshot. DuckDB — в памяти, только view над Parquet.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import duckdb

MEMORY_LIMIT = os.environ.get("RF_API_DUCKDB_MEMORY", "256MB")
THREADS = int(os.environ.get("RF_API_DUCKDB_THREADS", "2"))


class NoSnapshot(RuntimeError):
    pass


@dataclass
class Snapshot:
    path: Path
    manifest: dict[str, object]
    marts: set[str]
    con: duckdb.DuckDBPyConnection

    @property
    def id(self) -> str:
        return str(self.manifest["snapshot"])


def open_snapshot(path: Path, wanted: set[str]) -> Snapshot:
    mf = path / "manifest.json"
    if not mf.is_file():
        raise NoSnapshot(f"нет {mf}")
    manifest = json.loads(mf.read_text("utf-8"))
    con = duckdb.connect(":memory:", config={"memory_limit": MEMORY_LIMIT, "threads": THREADS})
    present = set()
    for mart in sorted(wanted):
        p = path / f"{mart}.parquet"
        if p.is_file():
            # Имя витрины — идентификатор из config/metrics.yaml (проверен семантическим слоем).
            con.execute(f"CREATE VIEW {mart} AS SELECT * FROM read_parquet('{p.as_posix()}')")
            present.add(mart)
    con.execute("SET lock_configuration = true")
    return Snapshot(path=path, manifest=manifest, marts=present, con=con)


class Store:
    def __init__(self, marts_dir: str | Path, wanted: set[str]) -> None:
        self.current = Path(marts_dir) / "current"
        self.wanted = wanted
        self._lock = threading.Lock()
        self._snap: Snapshot | None = None

    def get(self) -> Snapshot:
        try:
            target = self.current.resolve(strict=True)
        except (FileNotFoundError, OSError) as e:
            raise NoSnapshot(f"нет {self.current}") from e
        snap = self._snap
        if snap is not None and snap.path == target:
            return snap
        with self._lock:
            if self._snap is None or self._snap.path != target:
                # Старое соединение не закрываем: им могут пользоваться текущие запросы; уйдёт со сборщиком.
                self._snap = open_snapshot(target, self.wanted)
            return self._snap
