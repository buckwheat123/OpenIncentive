"""Engine tests: curve interpolation, password hashing, end-to-end calculation on in-memory DB."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.curves import interpolate, parse_points, payout_rate  # noqa: E402
from app.security import hash_password, verify_password  # noqa: E402


def test_curves():
    pts = parse_points("0:0, 80:50, 100:100, 150:200")
    assert pts == [[0, 0], [80, 50], [100, 100], [150, 200]]
    assert interpolate(pts, 0) == 0
    assert interpolate(pts, 40) == 25.0
    assert interpolate(pts, 90) == 75.0
    assert interpolate(pts, 100) == 100
    assert interpolate(pts, 300) == 200  # clamped, no extrapolation
    assert payout_rate(pts, 150, cap_pct=120) == 120  # cap applied
    try:
        parse_points("100:100")
        raise AssertionError("should require >=2 points")
    except ValueError:
        pass


def test_password():
    hashed = hash_password("s3cret")
    assert verify_password("s3cret", hashed)
    assert not verify_password("wrong", hashed)


def test_calculation_e2e():
    import json

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.db import Base
    from app.calc import apply_adjustment, run_calculation
    from app.models import Actual, BonusPlan, BonusResult, Curve, PlanKpi, User

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    admin = User(employee_id="A1", name="Admin", email="a@x.com", role="ADMIN",
                 password_hash=hash_password("x"))
    emp = User(employee_id="E1", name="Emp", email="e@x.com", bg="Retail",
               password_hash=hash_password("x"))
    db.add_all([admin, emp])
    db.flush()
    curve = Curve(name="Std", points_json=json.dumps([[0, 0], [100, 100], [200, 200]]), cap_pct=None)
    db.add(curve)
    db.flush()
    plan = BonusPlan(period="2026-Q1", employee_id=emp.id, plan_name="Sales Incentive")
    db.add(plan)
    db.flush()
    db.add(PlanKpi(plan_id=plan.id, kpi_name="Sales", weight_pct=60, quota=100, curve_id=curve.id))
    db.add(PlanKpi(plan_id=plan.id, kpi_name="NPS", weight_pct=40, quota=50, curve_id=curve.id))
    db.add(Actual(period="2026-Q1", employee_id=emp.id, kpi_name="Sales", actual=150, is_current=True))  # 150%
    db.add(Actual(period="2026-Q1", employee_id=emp.id, kpi_name="NPS", actual=25, is_current=True))    # 50%
    db.commit()

    # interval slopes used by the letter curve table
    segs = curve.segments
    assert segs[0]["x1"] == 0 and segs[0]["x2"] == 100 and abs(segs[0]["slope"] - 1.0) < 1e-9
    assert abs(segs[1]["slope"] - 1.0) < 1e-9

    run, stats = run_calculation(db, "2026-Q1", admin)
    assert stats["computed"] == 1
    result = db.scalars(select(BonusResult).where(BonusResult.run_id == run.id)).first()
    assert result.plan_name == "Sales Incentive"
    # weighted: 0.6*150 + 0.4*50 = 110%
    assert result.weighted_rate_pct == 110.0
    # unweighted: (150 + 50) / 2 = 100%
    assert result.unweighted_rate_pct == 100.0
    assert result.final_rate_pct == 110.0
    assert not result.adjusted

    # additive special adjustment: +15 percentage points -> 110 + 15 = 125
    apply_adjustment(db, emp.id, "2026-Q1", 15.0, "special", admin)
    db.refresh(result)
    assert result.adjustment_pct == 15.0
    assert result.final_rate_pct == 125.0
    assert result.adjusted

    # sealed scope blocks further adjustments
    from app.models import Lock

    db.add(Lock(period="2026-Q1", bg="Retail", locked_by=admin.id))
    db.commit()
    try:
        apply_adjustment(db, emp.id, "2026-Q1", 20.0, "should fail", admin)
        raise AssertionError("sealed scope must reject adjustments")
    except ValueError:
        pass


if __name__ == "__main__":
    test_curves()
    test_password()
    test_calculation_e2e()
    print("ALL TESTS PASSED")
