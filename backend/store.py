"""Small durable JSON record store. One application replica/worker in this release."""
from __future__ import annotations
import os
from pathlib import Path
from uuid import uuid4
from sqlalchemy import create_engine, MetaData, Table, Column, String, JSON, select, delete
from sqlalchemy.pool import StaticPool
from .models import now


class Store:
    def __init__(self, url: str | None = None):
        url = url or os.getenv("DATABASE_URL", "sqlite:///data/stonks.db")
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        options = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False, "timeout": 30}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
            else:
                Path(url.split("///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, **options)
        meta = MetaData()
        self.table = Table("records", meta,
            Column("id", String(100), primary_key=True),
            Column("kind", String(40), index=True, nullable=False),
            Column("created_at", String(50), index=True, nullable=False),
            Column("payload", JSON, nullable=False))
        meta.create_all(self.engine)

    def get(self, id: str) -> dict | None:
        with self.engine.connect() as c:
            row = c.execute(select(self.table.c.payload).where(self.table.c.id == id)).first()
            return row[0] if row else None

    def list(self, kind: str, limit: int = 100) -> list[dict]:
        with self.engine.connect() as c:
            rows = c.execute(select(self.table.c.payload).where(self.table.c.kind == kind)
                .order_by(self.table.c.created_at.desc()).limit(limit))
            return [r[0] for r in rows]

    def write(self, kind: str, data: dict, id: str | None = None) -> dict:
        return self.write_many([(kind, data, id)])[0]

    def write_many(self, entries: list[tuple[str, dict, str | None]]) -> list[dict]:
        result = []
        with self.engine.begin() as c:
            for kind, data, id in entries:
                id = id or str(uuid4())
                old = c.execute(select(self.table.c.created_at).where(self.table.c.id == id)).first()
                payload = {**data, "id": id, "created_at": old[0] if old else now()}
                if old:
                    c.execute(self.table.update().where(self.table.c.id == id).values(payload=payload))
                else:
                    c.execute(self.table.insert().values(id=id, kind=kind, created_at=payload["created_at"], payload=payload))
                result.append(payload)
        return result
