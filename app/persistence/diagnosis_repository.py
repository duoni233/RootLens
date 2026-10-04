"""SQLite-backed diagnosis history; no pipeline or Agent dependencies."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, Index, String, Text, create_engine, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from persistence.diagnosis_run import DiagnosisRun


class DiagnosisHistoryError(RuntimeError):
    pass


class UnsupportedSchemaVersion(DiagnosisHistoryError):
    pass


class _Base(DeclarativeBase):
    pass


class _RunRow(_Base):
    __tablename__ = "diagnosis_runs"
    __table_args__ = (
        Index("ix_diagnosis_runs_service_created", "service_name", "created_at"),
        Index("ix_diagnosis_runs_status_created", "diagnosis_status", "created_at"),
    )

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    schema_version: Mapped[str] = mapped_column(String(8), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(32))
    request_id: Mapped[str | None] = mapped_column(String(64))
    conversation_id: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    completed_at: Mapped[str] = mapped_column(String(32), nullable=False)
    original_message: Mapped[str] = mapped_column(Text, nullable=False)
    service_name: Mapped[str | None] = mapped_column(String(255))
    environment: Mapped[str | None] = mapped_column(String(64))
    intent: Mapped[str] = mapped_column(String(64), nullable=False)
    primary_agent: Mapped[str | None] = mapped_column(String(64))
    supporting_agents_json: Mapped[str] = mapped_column(Text, nullable=False)
    response_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis_status: Mapped[str] = mapped_column(String(32), nullable=False)
    trace_status: Mapped[str | None] = mapped_column(String(32))
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, index=True)
    clarification_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    diagnosis_json: Mapped[str | None] = mapped_column(Text)
    trace_json: Mapped[str | None] = mapped_column(Text)
    evidence_refs_json: Mapped[str] = mapped_column(Text, nullable=False)
    knowledge_refs_json: Mapped[str] = mapped_column(Text, nullable=False)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _snapshot(raw: str | None, name: str) -> dict | None:
    if raw is None:
        return None
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get("schema_version") != "1":
        raise UnsupportedSchemaVersion(f"unsupported {name} schema version")
    return data


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _to_row(run: DiagnosisRun) -> _RunRow:
    return _RunRow(
        run_id=run.run_id, schema_version=run.schema_version,
        trace_id=run.trace_id, request_id=run.request_id,
        conversation_id=run.conversation_id,
        created_at=_utc(run.created_at), completed_at=_utc(run.completed_at),
        original_message=run.original_message, service_name=run.service_name,
        environment=run.environment, intent=run.intent,
        primary_agent=run.primary_agent,
        supporting_agents_json=_json(run.supporting_agents),
        response_markdown=run.response_markdown,
        diagnosis_status=run.diagnosis_status.value, trace_status=run.trace_status,
        degraded=run.degraded, clarification_required=run.clarification_required,
        diagnosis_json=(_json(run.diagnosis.model_dump(mode="json"))
                        if run.diagnosis is not None else None),
        trace_json=(_json(run.trace.model_dump(mode="json"))
                    if run.trace is not None else None),
        evidence_refs_json=_json([ref.model_dump(mode="json") for ref in run.evidence_refs]),
        knowledge_refs_json=_json([ref.model_dump(mode="json") for ref in run.knowledge_refs]),
    )


def _from_row(row: _RunRow) -> DiagnosisRun:
    if row.schema_version != "1":
        raise UnsupportedSchemaVersion("unsupported diagnosis run schema version")
    return DiagnosisRun.model_validate({
        "schema_version": row.schema_version, "run_id": row.run_id,
        "trace_id": row.trace_id, "request_id": row.request_id,
        "conversation_id": row.conversation_id,
        "created_at": datetime.fromisoformat(row.created_at),
        "completed_at": datetime.fromisoformat(row.completed_at),
        "original_message": row.original_message,
        "service_name": row.service_name, "environment": row.environment,
        "intent": row.intent, "primary_agent": row.primary_agent,
        "supporting_agents": json.loads(row.supporting_agents_json),
        "response_markdown": row.response_markdown,
        "diagnosis_status": row.diagnosis_status,
        "trace_status": row.trace_status, "degraded": row.degraded,
        "clarification_required": row.clarification_required,
        "diagnosis": _snapshot(row.diagnosis_json, "IncidentDiagnosis"),
        "trace": _snapshot(row.trace_json, "DiagnosisTrace"),
        "evidence_refs": json.loads(row.evidence_refs_json),
        "knowledge_refs": json.loads(row.knowledge_refs_json),
    })


class DiagnosisRepository:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url, future=True)
        self._sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        if self.engine.url.get_backend_name() == "sqlite":
            database = self.engine.url.database
            if database and database != ":memory:":
                Path(database).parent.mkdir(parents=True, exist_ok=True)
        _Base.metadata.create_all(self.engine)

    def save_run(self, run: DiagnosisRun) -> None:
        try:
            with self._sessions.begin() as session:
                session.add(_to_row(run))
        except IntegrityError as ex:
            raise DiagnosisHistoryError(f"duplicate run_id: {run.run_id}") from ex
        except SQLAlchemyError as ex:
            raise DiagnosisHistoryError("could not save diagnosis run") from ex

    def get_run(self, run_id: str) -> DiagnosisRun | None:
        try:
            with self._sessions() as session:
                row = session.get(_RunRow, run_id)
                return _from_row(row) if row is not None else None
        except SQLAlchemyError as ex:
            raise DiagnosisHistoryError("could not read diagnosis run") from ex

    def list_runs(self, *, limit: int = 20, offset: int = 0,
                  service_name: str | None = None,
                  diagnosis_status: str | None = None,
                  degraded: bool | None = None) -> list[DiagnosisRun]:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError("limit must be 1..100 and offset must be nonnegative")
        stmt = select(_RunRow)
        if service_name is not None:
            stmt = stmt.where(_RunRow.service_name == service_name)
        if diagnosis_status is not None:
            stmt = stmt.where(_RunRow.diagnosis_status == diagnosis_status)
        if degraded is not None:
            stmt = stmt.where(_RunRow.degraded == degraded)
        stmt = stmt.order_by(_RunRow.created_at.desc(), _RunRow.run_id.desc())
        try:
            with self._sessions() as session:
                rows = session.scalars(stmt.limit(limit).offset(offset)).all()
                return [_from_row(row) for row in rows]
        except SQLAlchemyError as ex:
            raise DiagnosisHistoryError("could not list diagnosis runs") from ex

    def close(self) -> None:
        self.engine.dispose()
