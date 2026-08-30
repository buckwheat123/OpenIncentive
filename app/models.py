from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="EMPLOYEE")  # ADMIN/BG_ADMIN/MANAGER/EMPLOYEE
    bg: Mapped[str | None] = mapped_column(String(100), index=True)
    department: Mapped[str | None] = mapped_column(String(100))   # 部门名
    job_title: Mapped[str | None] = mapped_column(String(100))    # 职称
    manager_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    manager: Mapped["User | None"] = relationship(remote_side="User.id")


class Curve(Base):
    __tablename__ = "curves"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    points_json: Mapped[str] = mapped_column(Text)  # [[attainment_pct, payout_pct], ...]
    cap_pct: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    @property
    def points(self) -> list[list[float]]:
        import json

        return json.loads(self.points_json)

    @property
    def points_text(self) -> str:
        return ",".join(f"{x:g}:{y:g}" for x, y in self.points)

    @property
    def segments(self) -> list[dict]:
        """Interval table: from/to attainment, from/to payout, slope (Δpayout/Δattainment)."""
        pts = self.points
        out = []
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            slope = (y2 - y1) / (x2 - x1) if (x2 - x1) else 0.0
            out.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "slope": slope})
        return out


class BonusPlan(Base):
    """One plan per (period, employee, plan_name). Versioned: re-import creates a new
    version row and deactivates the old one (old versions are locked/immutable)."""

    __tablename__ = "bonus_plans"
    __table_args__ = (UniqueConstraint("period", "employee_id", "plan_name", "version",
                                       name="uq_plan_period_emp_name_ver"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(20), index=True)  # e.g. 2026-Q1
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan_name: Mapped[str] = mapped_column(String(100), default="DEFAULT", index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    employee: Mapped[User] = relationship()
    kpis: Mapped[list["PlanKpi"]] = relationship(cascade="all, delete-orphan")


class PlanKpi(Base):
    __tablename__ = "plan_kpis"
    __table_args__ = (UniqueConstraint("plan_id", "kpi_name", name="uq_plan_kpi"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("bonus_plans.id"), index=True)
    kpi_name: Mapped[str] = mapped_column(String(100))
    weight_pct: Mapped[float] = mapped_column(Float)
    quota: Mapped[float] = mapped_column(Float)
    curve_id: Mapped[int] = mapped_column(ForeignKey("curves.id"))

    curve: Mapped[Curve] = relationship()


class Actual(Base):
    """Versioned YTD actuals. Re-import creates a new version; latest is_current wins."""

    __tablename__ = "actuals"
    __table_args__ = (UniqueConstraint("period", "employee_id", "kpi_name", "version",
                                       name="uq_actual_ver"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    kpi_name: Mapped[str] = mapped_column(String(100))
    actual: Mapped[float] = mapped_column(Float)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CalcRun(Base):
    __tablename__ = "calc_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    creator: Mapped[User | None] = relationship()
    results: Mapped[list["BonusResult"]] = relationship(cascade="all, delete-orphan")


class BonusResult(Base):
    """Rates only (no bonus base stored). final = weighted + adjustment delta."""

    __tablename__ = "bonus_results"
    __table_args__ = (UniqueConstraint("run_id", "employee_id", "plan_name", name="uq_result"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("calc_runs.id"), index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    plan_name: Mapped[str] = mapped_column(String(100), default="DEFAULT")
    detail_json: Mapped[str] = mapped_column(Text)  # per-KPI breakdown
    unweighted_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)  # simple mean of KPI rates
    weighted_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)  # weight-averaged rate
    adjustment_pct: Mapped[float] = mapped_column(Float, default=0.0)  # special adjustment delta
    final_rate_pct: Mapped[float] = mapped_column(Float, default=0.0)  # weighted + adjustment
    adjusted: Mapped[bool] = mapped_column(Boolean, default=False)

    employee: Mapped[User] = relationship()


class Adjustment(Base):
    """Special payout-rate adjustment as a delta (± percentage points), added to the
    system weighted rate. Append-only audit record; latest wins."""

    __tablename__ = "adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    adjustment_pct: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    employee: Mapped[User] = relationship(foreign_keys=[employee_id])
    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])


class Lock(Base):
    """Sealed (period, bg): records are read-only afterwards. Irreversible."""

    __tablename__ = "locks"
    __table_args__ = (UniqueConstraint("period", "bg", name="uq_lock"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    bg: Mapped[str] = mapped_column(String(100))
    locked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    locked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    locker: Mapped["User | None"] = relationship()


class DataOpLog(Base):
    """Audit trail for data operations. Deletions MUST leave a reason here."""

    __tablename__ = "data_op_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    op_type: Mapped[str] = mapped_column(String(20), default="DELETE")  # DELETE / IMPORT / CALC / ADJUST
    entity: Mapped[str] = mapped_column(String(20))  # actual / plan / employee / label
    entity_ref: Mapped[str] = mapped_column(String(300))  # human-readable key
    reason: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    creator: Mapped[User | None] = relationship()


class Label(Base):
    """Translation dictionary for database field values (KPI names, BG, plan names,
    curve names, departments, job titles...). Keyed by the ORIGINAL value stored in DB;
    defaults to the original when a translation is missing. Values already in Chinese
    are used as-is for the Chinese UI."""

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    original: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    zh: Mapped[str] = mapped_column(String(200), default="")
    en: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LetterTemplate(Base):
    __tablename__ = "letter_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    bg: Mapped[str] = mapped_column(String(100), index=True)
    subject: Mapped[str] = mapped_column(String(200))
    body_html: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Letter(Base):
    __tablename__ = "letters"

    id: Mapped[int] = mapped_column(primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("letter_templates.id"))
    template_name: Mapped[str] = mapped_column(String(100), default="")
    recipient_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    period: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str] = mapped_column(String(200))
    body_html: Mapped[str] = mapped_column(Text)
    sent_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime)
    send_mode: Mapped[str] = mapped_column(String(10), default="outbox")  # smtp/outbox

    template: Mapped[LetterTemplate | None] = relationship()
    recipient: Mapped[User] = relationship(foreign_keys=[recipient_id])
    sender: Mapped[User | None] = relationship(foreign_keys=[sent_by])
