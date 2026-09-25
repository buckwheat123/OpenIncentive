"""End-to-end test against the running dev server (http://127.0.0.1:8000).

Run order:  .venv/Scripts/python seed.py   then start server   then  .venv/Scripts/python tests/test_e2e.py

Covers the v4 unified quarterly big-table import (one sheet, two-pass, validation +
identical-ignore), template download with recent-quarter prefill & BG scoping, the
separate letter-data import screen, platform-admin proxy of a BG admin, calculation,
adjustments, seals, export, letters, i18n and role-scoped views.
"""

import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models import Actual, BonusPlan, BonusResult, CalcRun, DataOpLog, Letter, LetterTemplate, User  # noqa: E402

BASE = "http://127.0.0.1:8000"

BIG_HEADER = ("period,employee_id,name,email,bg,department,job_title,manager_id,role,"
              "plan_name,kpi_name,weight_pct,quota,curve_name,actual")

# Unified quarterly sheet for a brand-new period (2027-Q1). One row per KPI; the first
# row of each person carries the employee-info columns. Includes intentional error rows.
QUARTER_CSV = "\n".join([
    BIG_HEADER,
    # E001 — info identical to seed (no user update)
    "2027-Q1,E001,张伟,zhang.wei@example.com,Retail,Sales East,销售代表,M003,EMPLOYEE,Sales Incentive,Revenue,60,1200000,Standard Curve,1150000",
    "2027-Q1,E001,张伟,,,,,,,Sales Incentive,Customer Satisfaction,40,90,Quality Curve,92",
    # E002 — Revenue first appears with actual 980000 ...
    "2027-Q1,E002,李娜,li.na@example.com,Retail,Sales South,销售代表,M003,EMPLOYEE,Sales Incentive,Revenue,60,1100000,Standard Curve,980000",
    "2027-Q1,E002,李娜,,,,,,,Sales Incentive,Customer Satisfaction,40,90,Quality Curve,88",
    # ... then again with 990000. Feature #7: the LATER row wins and supersedes the
    # earlier one (not a "duplicate" error); it carries the employee-info columns
    # (department Sales South) so the info update still applies via the surviving row.
    "2027-Q1,E002,李娜,li.na@example.com,Retail,Sales South,销售代表,M003,EMPLOYEE,Sales Incentive,Revenue,60,1100000,Standard Curve,990000",
    # ---- genuine error rows ----
    "2027-Q1,E999,王五,,,,,,,Sales Incentive,Revenue,60,1000000,Standard Curve,900000",   # unknown user
    "2027-Q1,E001,张伟,,,,,,,Sales Incentive,NewKpi,,100,CurveX,50",                        # missing weight_pct
    "2027-Q1,E002,李娜,,,,,,,Sales Incentive,ExtraKpi,50,100,CurveX,50",                    # curve not found
]) + "\n"

# Letter-data sheet (same columns minus `actual`) for a fresh person/period.
LETTER_HEADER = BIG_HEADER.rsplit(",actual", 1)[0]
LETTER_CSV = "\n".join([
    LETTER_HEADER,
    "2027-Q2,E003,赵磊,zhao.lei@example.com,Retail,Sales North,高级销售代表,M001,EMPLOYEE,Sales Incentive,Revenue,60,900000,Standard Curve",
    "2027-Q2,E003,赵磊,,,,,,,Sales Incentive,Customer Satisfaction,40,90,Quality Curve",
]) + "\n"

# BG-scope probe: E001 (Retail, in scope) + E004 (Commercial, in scope via BGA1's 2nd BG)
# + E900 (HR, out of scope for BGA1 even though BGA1 manages two BGs).
BG_SCOPE_CSV = "\n".join([
    BIG_HEADER,
    "2027-Q3,E001,张伟,zhang.wei@example.com,Retail,Sales East,销售代表,M003,EMPLOYEE,Sales Incentive,Revenue,60,1300000,Standard Curve,1000000",
    "2027-Q3,E004,陈静,chen.jing@example.com,Commercial,Commercial Sales,商务专员,M002,EMPLOYEE,Sales Incentive,Revenue,60,1100000,Standard Curve,900000",
    "2027-Q3,E900,周敏,zhou.min@example.com,HR,People,HRBP,M900,EMPLOYEE,Sales Incentive,Revenue,60,800000,Standard Curve,700000",
]) + "\n"

# Year-format letter-data sheet (feature #10 / Batch E2a): one row per KPI with four
# YTD target columns. E003 fills only Q1 and Q3 of 2028 → the importer expands this into
# two per-quarter plans (2028-Q1, 2028-Q3) and skips the blank Q2/Q4.
YEAR_HEADER = ("year,employee_id,name,email,bg,department,job_title,manager_id,role,"
               "plan_name,kpi_name,weight_pct,curve_name,ytd_q1,ytd_q2,ytd_q3,ytd_q4")
YEAR_LETTER_CSV = "\n".join([
    YEAR_HEADER,
    "2028,E003,赵磊,zhao.lei@example.com,Retail,Sales North,高级销售代表,M001,EMPLOYEE,"
    "Sales Incentive,Revenue,60,Standard Curve,1000000,,1400000,",
    "2028,E003,赵磊,,,,,,,Sales Incentive,Customer Satisfaction,40,Quality Curve,90,,95,",
]) + "\n"

# Conflict probe (Batch E2b): E001's 2026 Sales Incentive/Revenue plan already exists
# with quarterly targets 2600000 (Q2) / 3900000 (Q3), weights 60/40. (2026-Q1 is sealed
# by test [9], so we use the unsealed Q2/Q3.) Weights stay 60/40 so the plan name is not
# re-suffixed by F5 and the quota conflict is detected against the real "Sales Incentive".
#   * 2026-Q2 → quotas disagree (999999 / 5) → BOTH rows conflict-blocked (calc is authority)
#   * 2026-Q3 → quotas match exactly (3900000 / 90) → identical, silently ignored
#   * 2029-Q1 → a brand-new quarter with no calc data → imports cleanly as the one new
#               version, proving non-conflicting letter data still lands. Each employee/
#               period/plan group totals 100%, so F1 never rejects E001 here.
CONFLICT_YEAR_CSV = "\n".join([
    YEAR_HEADER,
    "2026,E001,张伟,zhang.wei@example.com,Retail,Sales East,销售代表,M003,EMPLOYEE,"
    "Sales Incentive,Revenue,60,Standard Curve,,999999,3900000,",
    "2026,E001,张伟,,,,,,,Sales Incentive,Customer Satisfaction,40,Quality Curve,,5,90,",
    "2029,E001,张伟,zhang.wei@example.com,Retail,Sales East,销售代表,M003,EMPLOYEE,"
    "Sales Incentive,Revenue,60,Standard Curve,800000,,,",
    "2029,E001,张伟,,,,,,,Sales Incentive,Customer Satisfaction,40,Quality Curve,85,,,",
]) + "\n"


# F1 weight-rejection probe (letter/year format): E002's Sales Incentive only reaches
# 60% (no CS) -> the WHOLE employee is rejected; E004's plan totals 100% -> imports fine.
WEIGHT_REJECT_CSV = "\n".join([
    YEAR_HEADER,
    "2028,E002,李娜,li.na@example.com,Retail,Sales South,销售代表,M003,EMPLOYEE,"
    "Sales Incentive,Revenue,60,Standard Curve,1000000,,,",
    "2028,E004,陈静,chen.jing@example.com,Commercial,Commercial Sales,商务专员,M002,EMPLOYEE,"
    "Sales Incentive,Revenue,60,Standard Curve,1100000,,,",
    "2028,E004,陈静,,,,,,,Sales Incentive,Customer Satisfaction,40,Quality Curve,90,,,",
]) + "\n"

# F5 plan-uniqueness probe (big-table format, fresh period 2030-Q1): the same KPI/Curve/
# weight combination must map to exactly one plan name within a period (cross-BG). E001
# registers "Alpha Plan"; E002 declares the identical combo as "Beta Plan" (-> renamed to
# Alpha Plan); E003 reuses "Alpha Plan" for a different combo (-> auto-suffixed Alpha Plan_v1).
F5_CSV = "\n".join([
    BIG_HEADER,
    "2030-Q1,E001,张伟,zhang.wei@example.com,Retail,Sales East,销售代表,M003,EMPLOYEE,Alpha Plan,Revenue,60,1000000,Standard Curve,900000",
    "2030-Q1,E001,张伟,,,,,,,Alpha Plan,Customer Satisfaction,40,90,Quality Curve,92",
    "2030-Q1,E002,李娜,li.na@example.com,Retail,Sales South,销售代表,M003,EMPLOYEE,Beta Plan,Revenue,60,1000000,Standard Curve,950000",
    "2030-Q1,E002,李娜,,,,,,,Beta Plan,Customer Satisfaction,40,90,Quality Curve,88",
    "2030-Q1,E003,赵磊,zhao.lei@example.com,Retail,Sales North,高级销售代表,M001,EMPLOYEE,Alpha Plan,Customer Satisfaction,100,90,Quality Curve,90",
]) + "\n"


def login(client: httpx.Client, uid: str, pw: str):
    r = client.post(f"{BASE}/login", data={"login_id": uid, "password": pw}, follow_redirects=True)
    assert r.status_code == 200, f"login failed for {uid}: {r.status_code}"


def upload(client: httpx.Client, url: str, text: str, field: str = "file", name: str = "sheet.csv"):
    return client.post(url, files={field: (name, text.encode("utf-8"), "text/csv")})


def main():
    db = SessionLocal()
    with httpx.Client(follow_redirects=True, timeout=30) as c:
        login(c, "ADMIN1", "admin123")
        assert "管理后台" in c.get(f"{BASE}/admin").text
        import_page = c.get(f"{BASE}/admin/import").text
        assert "季度大表导入" in import_page and "空白模板" in import_page
        print("[1] admin login, dashboard & import page OK")

        # ---- unified big-table import: pass-1 validation ----
        r = upload(c, f"{BASE}/admin/import/preview", QUARTER_CSV)
        assert "预览校验结果" in r.text, r.text[:400]
        assert "可导入" in r.text                       # valid rows
        assert "员工不存在" in r.text                    # E999
        assert "Curve 不存在" in r.text                  # CurveX
        assert "已被后续行覆盖" in r.text                 # earlier E002 Revenue superseded (#7)
        assert "缺失必填项" in r.text                     # missing weight_pct
        assert "可导入 4 行" in r.text and "忽略 1 行" in r.text and "报错 3 行" in r.text, r.text[:600]
        print("[2] big-table preview validation (ok/unknown/curve/supersede/missing) OK")

        # ---- pass-2 execute: creates plans + actuals, updates one employee's info ----
        r = c.post(f"{BASE}/admin/import/execute", data={"csv_text": QUARTER_CSV})
        assert "导入完成" in r.text and "计划新版本 2 个" in r.text, r.text[:600]
        assert "员工信息更新 1 人" in r.text, r.text[:600]
        db.expire_all()
        e001 = db.query(User).filter_by(employee_id="E001").first()
        e002 = db.query(User).filter_by(employee_id="E002").first()
        assert e002.department == "Sales South" and e002.updated_at is not None
        plan = db.query(BonusPlan).filter_by(period="2027-Q1", employee_id=e001.id,
                                             plan_name="Sales Incentive", is_current=True).first()
        assert plan and len(plan.kpis) == 2
        rev = db.query(Actual).filter_by(period="2027-Q1", employee_id=e001.id,
                                         kpi_name="Revenue", is_current=True).first()
        assert rev and abs(rev.actual - 1150000) < 1e-6
        # #7: the later E002 Revenue row (990000) won and was the one persisted.
        rev2 = db.query(Actual).filter_by(period="2027-Q1", employee_id=e002.id,
                                          kpi_name="Revenue", is_current=True).first()
        assert rev2 and abs(rev2.actual - 990000) < 1e-6
        print("[3] big-table execute (new plan version, later-row-wins actual, info update) OK")

        # ---- identical re-upload is IGNORED, not an error, no new version ----
        r = upload(c, f"{BASE}/admin/import/preview", QUARTER_CSV)
        assert "忽略（与系统数据一致）" in r.text, r.text[:600]
        assert "已被后续行覆盖" in r.text, r.text[:600]
        assert "忽略 5 行" in r.text, r.text[:600]
        print("[4] identical re-upload ignored OK")

        # ---- error-list CSV download ----
        r = c.post(f"{BASE}/admin/import/errors.csv", data={"csv_text": QUARTER_CSV})
        assert r.status_code == 200 and "status" in r.text
        assert "E999" in r.text and "CurveX" in r.text
        assert "1150000" not in r.text          # valid rows are excluded from the error list
        print("[5] error-list CSV download OK")

        # ---- template download: blank vs prefilled from a recent quarter ----
        blank = c.get(f"{BASE}/admin/import/template.csv").text
        assert "employee_id" in blank and "actual" in blank
        assert len([ln for ln in blank.splitlines() if ln.strip()]) == 1   # header only
        prefilled = c.get(f"{BASE}/admin/import/template.csv?period=2027-Q1").text
        assert "E001" in prefilled and "1150000" in prefilled
        print("[6] template download (blank + recent-quarter prefill) OK")

        # ---- one-click calculation for the imported quarter (F3: two-pass CSV removed) ----
        r = c.post(f"{BASE}/admin/runs", data={"period": "2027-Q1", "note": "e2e"})
        assert "已触发计算" in r.text and "计算 2 人" in r.text, r.text[:600]
        db.expire_all()
        run_2027 = db.query(CalcRun).filter_by(period="2027-Q1").order_by(CalcRun.id.desc()).first()
        assert run_2027 and db.query(BonusResult).filter_by(
            run_id=run_2027.id, employee_id=e001.id, plan_name="Sales Incentive").first()
        print("[7] one-click calculation OK")

        # ---- additive special adjustment (single) ----
        r = c.post(f"{BASE}/admin/adjust", data={
            "employee_id": e001.id, "period": "2027-Q1", "adjustment_pct": "10", "reason": "E2E 测试特批"})
        assert "已记录特殊调整" in r.text and "E2E 测试特批" in r.text
        print("[8] additive special adjustment OK")

        # ---- one-click seal multiple BGs blocks adjustments (#2) ----
        r = c.post(f"{BASE}/admin/locks", data={"period": "2026-Q1", "bgs": ["Retail", "Commercial"]})
        assert "已封存" in r.text and "本次新封存 2 个 BG" in r.text, r.text[:400]
        r = c.post(f"{BASE}/admin/locks", data={"period": "2026-Q1", "bgs": ["Retail", "Commercial"]})
        assert "本次新封存 0 个 BG" in r.text and "2 个此前已封存" in r.text, r.text[:400]
        r = c.post(f"{BASE}/admin/adjust", data={
            "employee_id": e001.id, "period": "2026-Q1", "adjustment_pct": "50", "reason": "应被拒绝"})
        assert "已封存" in r.text
        print("[9] one-click multi-BG seal blocks adjustments OK")

        # ---- F2: re-running a sealed quarter must not blank already-calculated people ----
        # All 2026 sales BGs (Retail/Commercial) are sealed -> a fresh 2026-Q1 run skips
        # everyone and computes 0, yet E001's earlier result must still show as 已计算.
        r = c.post(f"{BASE}/admin/runs", data={"period": "2026-Q1", "note": "F2 recalc sealed"})
        assert "计算 0 人" in r.text, r.text[:400]
        db.expire_all()
        bg_view = c.get(f"{BASE}/bg?period=2026-Q1").text
        assert "已计算" in bg_view and "E001" in bg_view   # result_for scans ALL runs, not just newest
        print("[9b] F2 sealed-quarter still shows previously-calculated OK")

        # ---- batch adjustments via CSV (two-pass) ----
        adj_csv = ("period,employee_id,name,adjustment_pct,reason\n"
                   "2027-Q1,E002,李娜,5,批量测试特批\n"
                   "2026-Q1,E001,张伟,-3,应被跳过：已封存")
        r = upload(c, f"{BASE}/admin/adjust/preview", adj_csv)
        assert "可计算" in r.text and "已封存" in r.text, r.text[:800]
        r = c.post(f"{BASE}/admin/adjust/execute", data={"csv_text": adj_csv})
        assert "成功 1 条" in r.text and "跳过/失败 1 条" in r.text, r.text[:400]
        assert "批量测试特批" in r.text
        print("[10] batch adjustments via CSV OK")

        # ---- period-filtered template downloads (F6 prefill export + adjust/delete) ----
        f6_tpl = c.get(f"{BASE}/admin/import/template.csv?period=2027-Q1").text.lstrip("\ufeff")
        assert "E001" in f6_tpl and "2027-Q1" in f6_tpl and "2026-Q1" not in f6_tpl
        adj_tpl = c.get(f"{BASE}/admin/adjust/template.csv?period=2027-Q1").text
        assert "E001" in adj_tpl and "2026-Q1" not in adj_tpl
        del_tpl = c.get(f"{BASE}/admin/data/delete-template.csv?entity=actual&period=2027-Q1").text
        assert "1150000" in del_tpl and "E001" in del_tpl
        print("[11] F6 prefilled big-table export + adjust/delete templates (period-filtered) OK")

        # ---- export page + year/BG filtered export (two sheets) ----
        export_page = c.get(f"{BASE}/admin/export").text
        assert "导出全部结果" in export_page and "全部年份" in export_page and "全部 BG" in export_page
        assert "总支付率" in export_page and "各 KPI 明细" in export_page   # two-sheet UI
        # sheet 1: total rate per person/plan
        r = c.get(f"{BASE}/admin/export.csv?year=2026&bg=Retail")
        assert r.status_code == 200 and "plan_name" in r.text and "weighted_rate_pct" in r.text
        assert "bonus_amount" not in r.text
        assert "comment" in r.text and "weight_total_pct" in r.text   # weighted-only + comment column
        assert "unweighted_rate_pct" not in r.text                    # unweighted rate removed
        assert "kpi_name" not in r.text                               # sheet 1 is NOT per-KPI
        assert "E001" in r.text and "E004" not in r.text    # Commercial excluded by BG filter
        # sheet 2: per-KPI detail
        rk = c.get(f"{BASE}/admin/export_kpi.csv?year=2026&bg=Retail")
        assert rk.status_code == 200
        assert "kpi_name" in rk.text and "attainment_pct" in rk.text and "rate_pct" in rk.text
        assert "curve_name" in rk.text and "weight_pct" in rk.text
        assert "weighted_rate_pct" not in rk.text.splitlines()[0]     # no total-rate columns in header
        assert "E001" in rk.text and "E004" not in rk.text            # same BG filter
        print("[12] export page + two-sheet (total rate + per-KPI) export OK")

        # ---- F5 plan-uniqueness: same combo -> one name (rename); same name/diff combo -> suffix ----
        r = upload(c, f"{BASE}/admin/import/preview", F5_CSV)
        assert "计划名将从「Beta Plan」改为「Alpha Plan」" in r.text, r.text[:800]   # E002 renamed
        assert "Alpha Plan_v1" in r.text, r.text[:800]                        # E003 auto-suffixed
        r = c.post(f"{BASE}/admin/import/execute", data={"csv_text": F5_CSV})
        assert "导入完成" in r.text, r.text[:600]
        db.expire_all()
        e001 = db.query(User).filter_by(employee_id="E001").first()
        e002 = db.query(User).filter_by(employee_id="E002").first()
        e003 = db.query(User).filter_by(employee_id="E003").first()
        p1 = db.query(BonusPlan).filter_by(period="2030-Q1", employee_id=e001.id,
                                           plan_name="Alpha Plan", is_current=True).first()
        p2 = db.query(BonusPlan).filter_by(period="2030-Q1", employee_id=e002.id,
                                           plan_name="Alpha Plan", is_current=True).first()
        p3 = db.query(BonusPlan).filter_by(period="2030-Q1", employee_id=e003.id,
                                           plan_name="Alpha Plan_v1", is_current=True).first()
        assert p1 and p2 and p3                                 # E002 landed under Alpha Plan
        assert db.query(BonusPlan).filter_by(plan_name="Beta Plan").first() is None   # never stored
        print("[12b] F5 plan-uniqueness (rename identical combo, suffix clashing name) OK")

        # ---- letter-data import screen (separate, no actual column) ----
        data_page = c.get(f"{BASE}/letters/data").text
        assert "通知信数据导入" in data_page
        lt = c.get(f"{BASE}/letters/data/template.csv").text
        assert "employee_id" in lt and "actual" not in lt.splitlines()[0]   # no actual column
        r = upload(c, f"{BASE}/letters/data/preview", LETTER_CSV)
        assert "预览校验结果" in r.text and "可导入" in r.text, r.text[:600]
        r = c.post(f"{BASE}/letters/data/execute", data={"csv_text": LETTER_CSV})
        assert "导入完成" in r.text and "计划新版本 1 个" in r.text, r.text[:600]
        db.expire_all()
        e003 = db.query(User).filter_by(employee_id="E003").first()
        lp = db.query(BonusPlan).filter_by(period="2027-Q2", employee_id=e003.id,
                                           plan_name="Sales Incentive", is_current=True).first()
        assert lp and len(lp.kpis) == 2
        no_actual = db.query(Actual).filter_by(period="2027-Q2", employee_id=e003.id).first()
        assert no_actual is None                            # letter data carries no actuals
        print("[13] letter-data import (separate screen, no actual) OK")

        # ---- year-format letter-data import (feature #10 / Batch E2a) ----
        yt = c.get(f"{BASE}/letters/data/template.csv").text.lstrip("\ufeff")
        assert "ytd_q1" in yt and "ytd_q4" in yt and yt.splitlines()[0].startswith("year")
        ypre = c.get(f"{BASE}/letters/data/template.csv?year=2026").text   # real prefill
        assert "E001" in ypre and "ytd_q" in ypre            # 2026 plans laid out by year
        yr = upload(c, f"{BASE}/letters/data/preview", YEAR_LETTER_CSV)
        assert "预览校验结果" in yr.text and "可导入" in yr.text, yr.text[:600]
        # one year row expands into two quarterly rows (2028-Q1 + 2028-Q3)
        assert yr.text.count("2028-Q1") >= 1 and yr.text.count("2028-Q3") >= 1
        assert "2028-Q2" not in yr.text and "2028-Q4" not in yr.text   # blank quarters skipped
        yr_ex = c.post(f"{BASE}/letters/data/execute", data={"csv_text": YEAR_LETTER_CSV})
        assert "计划新版本 2 个" in yr_ex.text, yr_ex.text[:600]
        db.expire_all()
        e003 = db.query(User).filter_by(employee_id="E003").first()
        q1 = db.query(BonusPlan).filter_by(period="2028-Q1", employee_id=e003.id,
                                           plan_name="Sales Incentive", is_current=True).first()
        q3 = db.query(BonusPlan).filter_by(period="2028-Q3", employee_id=e003.id,
                                           plan_name="Sales Incentive", is_current=True).first()
        assert q1 and q1.kpis[0].quota == 1000000
        assert q3 and q3.kpis[0].quota == 1400000
        assert db.query(BonusPlan).filter_by(period="2028-Q2", employee_id=e003.id).first() is None
        print("[13b] year-format letter-data import (YTD cols → quarterly plans) OK")

        # ---- conflict detection: letter vs existing quarterly calc (Batch E2b) ----
        e001 = db.query(User).filter_by(employee_id="E001").first()
        q2_before = db.query(BonusPlan).filter_by(period="2026-Q2", employee_id=e001.id,
                                                  plan_name="Sales Incentive", is_current=True).first()
        assert next(k for k in q2_before.kpis if k.kpi_name == "Revenue").quota == 2600000
        cf = upload(c, f"{BASE}/letters/data/preview", CONFLICT_YEAR_CSV)
        assert "与季度计算数据冲突" in cf.text, cf.text[:600]      # Q2 blocked
        assert "冲突清单" in cf.text                              # dedicated download button shown
        cfr = c.post(f"{BASE}/letters/data/conflicts.csv", data={"csv_text": CONFLICT_YEAR_CSV})
        assert cfr.status_code == 200 and "existing_q2" in cfr.text
        assert "2600000" in cfr.text and "999999" in cfr.text     # sheet value vs letter value
        cf_ex = c.post(f"{BASE}/letters/data/execute", data={"csv_text": CONFLICT_YEAR_CSV})
        assert "计划新版本 1 个" in cf_ex.text, cf_ex.text[:600]   # only non-conflicting Q3 lands
        db.expire_all()
        q2_after = db.query(BonusPlan).filter_by(period="2026-Q2", employee_id=e001.id,
                                                 plan_name="Sales Incentive", is_current=True).first()
        assert next(k for k in q2_after.kpis if k.kpi_name == "Revenue").quota == 2600000  # untouched
        assert q2_after.version == q2_before.version              # no new Q2 version created
        print("[13c] letter-vs-calc conflict blocked + conflict CSV exported OK")

        # ---- F1 letter weight rule: a plan not totaling 100% rejects the WHOLE employee ----
        r = upload(c, f"{BASE}/letters/data/preview", WEIGHT_REJECT_CSV)
        assert "权重合计不是 100%" in r.text, r.text[:800]      # E002 (60% only) flagged
        assert "可导入" in r.text                              # E004 (60+40=100) still importable
        r = c.post(f"{BASE}/letters/data/execute", data={"csv_text": WEIGHT_REJECT_CSV})
        assert "计划新版本 1 个" in r.text, r.text[:600]        # only E004 lands
        db.expire_all()
        e002 = db.query(User).filter_by(employee_id="E002").first()
        e004 = db.query(User).filter_by(employee_id="E004").first()
        assert db.query(BonusPlan).filter_by(period="2028-Q1", employee_id=e002.id).first() is None  # rejected
        ok4 = db.query(BonusPlan).filter_by(period="2028-Q1", employee_id=e004.id,
                                            plan_name="Sales Incentive", is_current=True).first()
        assert ok4 and len(ok4.kpis) == 2
        print("[13d] F1 letter weight!=100% rejects the whole employee (others import) OK")

        # ---- BG admin #4: multi-BG scope (BGA1 manages Retail + Commercial) ----
        login(c, "BGA1", "BGA1")
        bg_tpl = c.get(f"{BASE}/admin/import/template.csv?period=2026-Q3").text
        assert "E001" in bg_tpl and "E004" in bg_tpl       # both managed BGs included
        assert "E900" not in bg_tpl                        # HR is out of scope for BGA1
        r = upload(c, f"{BASE}/admin/import/preview", BG_SCOPE_CSV)
        assert "可导入" in r.text and "超出本 BG 权限" in r.text, r.text[:600]
        bg_page = c.get(f"{BASE}/bg").text
        assert "奖金总览" in bg_page and "E001" in bg_page and "E004" in bg_page
        assert "季度总支付率" in bg_page
        assert "商业 / 零售" in bg_page                    # bg_title shows both managed BGs
        assert "E900" not in bg_page                        # HR employee not in BGA1's /bg
        r = c.get(f"{BASE}/bg/export.csv")
        assert "E001" in r.text and "E004" in r.text and "E900" not in r.text
        rk = c.get(f"{BASE}/bg/export_kpi.csv")
        assert "kpi_name" in rk.text and "E001" in rk.text and "E004" in rk.text \
               and "E900" not in rk.text
        print("[14] BG admin multi-BG scope (template/view/export include both, HR out) OK")

        # ---- BG admin #4: many admins co-manage Retail (BGA2 only sees Retail) ----
        login(c, "BGA2", "BGA2")
        bg2_page = c.get(f"{BASE}/bg").text
        assert "E001" in bg2_page and "E004" not in bg2_page   # only Retail
        assert "零售" in bg2_page and "商业" not in bg2_page   # bg_title = Retail only
        bg2_tpl = c.get(f"{BASE}/admin/import/template.csv?period=2026-Q3").text
        assert "E001" in bg2_tpl and "E004" not in bg2_tpl
        r = upload(c, f"{BASE}/admin/import/preview", BG_SCOPE_CSV)
        # E004 (Commercial) is now out-of-scope for BGA2 as well
        assert "超出本 BG 权限" in r.text
        print("[14b] BG co-admin (BGA2) scope limited to Retail OK")

        # ---- platform admin proxies a BG admin ----
        login(c, "ADMIN1", "admin123")
        bga1 = db.query(User).filter_by(employee_id="BGA1").first()
        r = c.post(f"{BASE}/admin/proxy/{bga1.id}")
        assert "代操作" in r.text and "退出代操作" in r.text, r.text[:400]
        assert "Linda Chen" in r.text                        # landed on BGA1's /bg with banner
        denied = c.get(f"{BASE}/admin", follow_redirects=False)
        assert denied.status_code == 303                     # BG admin cannot reach /admin
        r = c.get(f"{BASE}/proxy/stop")
        assert "管理后台" in r.text and "已退出代操作" in r.text, r.text[:400]
        db.expire_all()
        proxy_logs = db.query(DataOpLog).filter_by(op_type="PROXY").count()
        assert proxy_logs >= 2                               # start + stop recorded
        print("[15] platform-admin proxy (banner, scoped denial, stop, audit) OK")

        # ---- letter: curve slope table, admin-preview cannot ack, anonymous acks ----
        login(c, "ADMIN1", "admin123")
        e002 = db.query(User).filter_by(employee_id="E002").first()
        tpl = db.query(LetterTemplate).filter_by(bg="Retail").first()
        r = c.post(f"{BASE}/letters/send", data={
            "template_id": tpl.id, "period": "2026-Q2", "message": "E2E 测试留言", "recipients": [str(e002.id)]})
        assert "已发出 1 封" in r.text, r.text[:400]
        db.expire_all()
        letter = db.query(Letter).filter_by(recipient_id=e002.id).order_by(Letter.id.desc()).first()
        assert letter and letter.send_mode == "outbox"
        assert "区间斜率" in letter.body_html and "达成率区间" in letter.body_html
        preview = c.get(f"{BASE}/letter/{letter.token}")
        assert "管理员身份预览" in preview.text
        assert letter.read_at is None
        with httpx.Client(follow_redirects=True, timeout=30) as anon:
            page = anon.get(f"{BASE}/letter/{letter.token}")
            assert "确认已阅" in page.text and "E2E 测试留言" in page.text
            assert "区间斜率" in page.text
            assert page.text.count('type="submit"') == 1     # exactly one ack button
            anon.post(f"{BASE}/letter/{letter.token}/read")
        db.expire_all()
        assert db.query(Letter).filter_by(id=letter.id).first().read_at is not None
        print("[16] letter with curve slope table + single ack + recipient-only read OK")

        # ---- #10 letters overhaul: Plan_Table vs Performance_Table split,
        #      expanded placeholders, Global ADMIN templates ----
        assert "实绩" not in letter.body_html.split("达成情况")[0] \
               if "达成情况" in letter.body_html else True   # Plan_Table part is pure structure
        assert "加权贡献" in letter.body_html and "原始支付率" in letter.body_html
        assert "E2E 测试留言" in letter.body_html and "经理" in letter.body_html
        # placeholder rendering: manager name should appear via {{MANAGER}}
        db.expire_all()
        mgr = e002.manager
        assert mgr and mgr.name in letter.body_html
        # ---- F4: templates shared across admins; others' templates read-only but copyable ----
        login(c, "BGA1", "BGA1")
        tpl_page = c.get(f"{BASE}/letters/templates").text
        assert "集团统一奖金通知（Global）" in tpl_page      # BG admin sees ADMIN's Global template
        assert "创建者" in tpl_page                          # owner column present
        db.expire_all()
        global_tpl = db.query(LetterTemplate).filter_by(bg="Global").first()
        bga1 = db.query(User).filter_by(employee_id="BGA1").first()
        assert global_tpl.name in c.get(f"{BASE}/letters/compose").text   # shared in compose dropdown
        edit_as_bga1 = c.get(f"{BASE}/letters/templates/{global_tpl.id}/edit").text
        assert "只读" in edit_as_bga1 and "复制并编辑" in edit_as_bga1     # read-only + copy action
        denied = c.post(f"{BASE}/letters/templates/save", data={
            "tid": global_tpl.id, "name": "hijack", "subject": "x", "body_html": "<p>x</p>"},
            follow_redirects=False)
        assert denied.status_code == 303 and "/letters/templates" in denied.headers.get("location", "")
        db.expire_all()
        assert db.get(LetterTemplate, global_tpl.id).name != "hijack"     # original untouched
        cp = c.post(f"{BASE}/letters/templates/{global_tpl.id}/copy", follow_redirects=True)
        assert "已复制模板" in cp.text
        db.expire_all()
        mycopy = db.query(LetterTemplate).filter(LetterTemplate.created_by == bga1.id,
                                                 LetterTemplate.name.like("%副本%")).order_by(
                                                 LetterTemplate.id.desc()).first()
        assert mycopy and mycopy.bg == "Retail"                          # copy owned by BGA1, in their BG
        copy_id = mycopy.id                                              # capture before delete/expire
        assert "只读" not in c.get(f"{BASE}/letters/templates/{copy_id}/edit").text  # editable
        c.post(f"{BASE}/letters/templates/{copy_id}/delete")            # creator may delete own copy
        db.expire_all()
        assert db.get(LetterTemplate, copy_id) is None
        dd = c.post(f"{BASE}/letters/templates/{global_tpl.id}/delete", follow_redirects=False)  # not ADMIN's
        assert dd.status_code == 303
        db.expire_all()
        assert db.get(LetterTemplate, global_tpl.id) is not None
        print("[16b] F4 shared templates: read-only for others, copy + delete-own OK")

        # ---- F4: platform ADMIN can delete ANY template (including a BG admin's) ----
        login(c, "ADMIN1", "admin123")
        db.expire_all()
        bga_tpl = db.query(LetterTemplate).filter_by(name="季度奖金通知").first()   # seed, created_by BGA1
        assert bga_tpl
        bga_id = bga_tpl.id                                           # capture before delete/expire
        c.post(f"{BASE}/letters/templates/{bga_id}/delete")
        db.expire_all()
        assert db.get(LetterTemplate, bga_id) is None
        print("[16c] F4 platform ADMIN deletes a BG admin's template OK")

        # ---- template save-as-new (copy from the still-live Global template) ----
        r = c.post(f"{BASE}/letters/templates/save", data={
            "tid": global_tpl.id, "name": "季度奖金通知 v2", "subject": "测试主题",
            "body_html": "<p>你好 {{NAME}}</p>", "save_as_new": "true"})
        assert "已保存" in r.text
        assert db.query(LetterTemplate).filter_by(name="季度奖金通知 v2").first()
        print("[17] template save-as-new OK")

        # ---- language management: labels page, CSV upsert ----
        login(c, "ADMIN1", "admin123")
        labels_page = c.get(f"{BASE}/admin/labels").text
        assert "语言管理" in labels_page and "华东销售部" in labels_page
        labels_csv = "original,zh,en\nTestTerm,测试词,TestTerm"
        r = upload(c, f"{BASE}/admin/labels/import", labels_csv)
        assert "已更新 1 条翻译" in r.text and "测试词" in r.text
        print("[18] language management (labels page + CSV upsert) OK")

        # ---- UI language switch (default zh, en selectable) ----
        en_page = c.get(f"{BASE}/lang/en", follow_redirects=True).text
        assert "Sign out" in en_page or "Admin Console" in en_page
        zh_page = c.get(f"{BASE}/lang/zh", follow_redirects=True).text
        assert "管理后台" in zh_page and "退出" in zh_page
        print("[19] UI language switch zh/en OK")

        # ---- multi-level manager team: levels, filter, scoping ----
        login(c, "M001", "M001")
        team = c.get(f"{BASE}/team").text
        assert "我的团队" in team
        assert "E003" in team          # direct report (N-1)
        assert "M003" in team          # sub-manager (N-1)
        assert "E001" in team          # N-2 through M003
        assert "N-2" in team           # level labels present
        assert "E004" not in team      # other BG excluded
        filtered = c.get(f"{BASE}/team?level=N-2")
        assert "E001" in filtered.text and "E003" not in filtered.text
        print("[20] multi-level manager team + level filter OK")

        # ---- employee self view: 4-quarter horizontal + rates + access control ----
        login(c, "E001", "E001")
        me = c.get(f"{BASE}/me")
        assert "张伟" in me.text
        assert "加权支付率" in me.text and "季度总支付率" in me.text
        assert "未加权" not in me.text          # system no longer surfaces unweighted rate
        assert "Q4" in me.text               # four quarters shown horizontally
        assert "华东销售部" in me.text        # department shown (translated)
        assert "销售代表" in me.text          # job title shown
        r = c.get(f"{BASE}/admin", follow_redirects=False)
        assert r.status_code == 303
        r = c.get(f"{BASE}/person/{e002.id}", follow_redirects=False)
        assert r.status_code == 303          # peer access denied
        print("[21] employee self view (4-quarter, rates, employee info) & access control OK")

        # ---- batch user import (ADMIN only): create / identical-ignore / validation ----
        login(c, "BGA1", "BGA1")
        assert c.get(f"{BASE}/admin/users/import/template.csv", follow_redirects=False).status_code == 303
        login(c, "ADMIN1", "admin123")
        users_tpl = c.get(f"{BASE}/admin/users/import/template.csv").text
        assert "employee_id" in users_tpl and "password" in users_tpl
        users_csv = (
            "employee_id,name,email,role,bg,department,job_title,manager_id,password\n"
            "E005,孙悦,sun.yue@example.com,EMPLOYEE,Retail,Sales East,销售代表,M003,\n"
            "E007,吴桐,wu.tong@example.com,EMPLOYEE,Retail,Sales East,销售代表,M010,\n"    # forward-ref to M010 (defined next)
            "M010,赵敏,zhao.min@example.com,MANAGER,Retail,Sales East,销售经理,M001,\n"     # brand-new manager in same sheet
            "E008,郑华,zheng.hua@example.com,EMPLOYEE,Retail,Sales East,销售代表,M999,\n"    # missing manager -> admin proxy
            "E001,张伟,zhang.wei@example.com,EMPLOYEE,Retail,Sales East,销售代表,M003,\n"    # identical -> ignored
            "E005,孙悦,sun.yue@example.com,EMPLOYEE,Retail,Sales East,销售代表,M003,\n"      # duplicate -> error
        )
        r = upload(c, f"{BASE}/admin/users/import/preview", users_csv)
        assert "预览校验结果" in r.text
        assert "新建" in r.text and "忽略（已存在且信息一致）" in r.text, r.text[:600]
        assert "上级不存在" not in r.text                    # #1: missing manager is no longer an error
        assert "表内重复" in r.text                           # duplicate E005 is still an error
        assert "新建 4 人" in r.text and "报错 1 行" in r.text, r.text[:600]
        r = c.post(f"{BASE}/admin/users/import/execute", data={"csv_text": users_csv})
        assert "导入完成" in r.text and "新建 4 人" in r.text, r.text[:600]
        db.expire_all()
        e005 = db.query(User).filter_by(employee_id="E005").first()
        e007 = db.query(User).filter_by(employee_id="E007").first()
        m010 = db.query(User).filter_by(employee_id="M010").first()
        e008 = db.query(User).filter_by(employee_id="E008").first()
        admin = db.query(User).filter_by(role="ADMIN").first()
        assert e005 and m010 and m010.role == "MANAGER"
        assert e007 and e007.manager_id == m010.id          # #1: same-sheet manager linked
        assert e008 and e008.manager_id == admin.id         # #1: unknown manager -> ADMIN proxy
        users_page = c.get(f"{BASE}/admin/users").text
        assert "E005" in users_page and "孙悦" in users_page
        r = c.post(f"{BASE}/admin/users/import/errors.csv", data={"csv_text": users_csv})
        assert "status" in r.text and "表内重复" in r.text
        assert "M999" not in r.text                          # E008 is valid now, not an error row
        assert "zhang.wei@example.com" not in r.text         # identical/ignored row excluded from errors
        print("[22] batch user import (create/ignore/validation, new-manager + admin-proxy) OK")

        # ---- ADMIN batch disable / re-enable users (#5) ----
        uids = [e005.id, e007.id, e008.id]
        r = c.post(f"{BASE}/admin/users/batch-toggle", data={"uids": uids, "action": "disable"})
        assert "批量操作完成" in r.text and "停用 3 人" in r.text, r.text[:400]
        db.expire_all()
        assert all(not db.get(User, uid).is_active for uid in uids)
        r = c.post(f"{BASE}/admin/users/batch-toggle",
                   data={"uids": uids + [admin.id], "action": "enable"})
        assert "启用 3 人" in r.text and "跳过 1 人" in r.text, r.text[:400]
        db.expire_all()
        assert all(db.get(User, uid).is_active for uid in uids)
        assert db.get(User, admin.id).is_active              # acting admin never toggled
        print("[22b] ADMIN batch disable/enable users (self skipped) OK")

        # ---- #4 user-info versioning: prior attribute set is archived (is_active=False) ----
        from app.models import UserVersion
        from app.deps import user_versions
        db.expire_all()
        e003 = db.query(User).filter_by(employee_id="E003").first()
        before_dept = e003.department
        versions_before = user_versions(db, e003)
        bump_csv = "\n".join([
            "employee_id,name,email,role,bg,department,job_title,manager_id,password",
            f"E003,{e003.name},{e003.email},EMPLOYEE,Retail,Sales West,,,",
        ]) + "\n"
        r = c.post(f"{BASE}/admin/users/import/execute", data={"csv_text": bump_csv})
        assert "导入完成" in r.text and "更新 1 人" in r.text, r.text[:400]
        db.expire_all()
        e003 = db.query(User).filter_by(employee_id="E003").first()
        assert e003.department == "Sales West"
        versions_after = user_versions(db, e003)
        assert len(versions_after) == len(versions_before) + 1
        latest_v = versions_after[0]
        assert latest_v.is_active is False
        assert latest_v.department == before_dept         # the superseded snapshot
        assert latest_v.user_id == e003.id
        # /person view exposes archived versions for admins
        person_page = c.get(f"{BASE}/person/{e003.id}").text
        assert "信息变更历史" in person_page and "Sales West" in person_page
        print("[22c] user-info versioning archives superseded record on update OK")

        # ---- #4 managed-BGs re-sync via admin console ----
        bga2 = db.query(User).filter_by(employee_id="BGA2").first()
        r = c.post(f"{BASE}/admin/users/{bga2.id}/managed_bgs",
                   data={"bg": "Retail/HR"})
        assert "已更新" in r.text and "BGA2" in r.text, r.text[:400]
        db.expire_all()
        bga2 = db.query(User).filter_by(employee_id="BGA2").first()
        assert bga2.bg_scope == {"Retail", "HR"}
        assert bga2.bg == "Retail"                       # primary stays first ordered BG
        # restore seed state so downstream tests / demo see the intended pairing
        r = c.post(f"{BASE}/admin/users/{bga2.id}/managed_bgs", data={"bg": "Retail"})
        db.expire_all()
        bga2 = db.query(User).filter_by(employee_id="BGA2").first()
        assert bga2.bg_scope == {"Retail"}
        print("[23] managed-BGs re-sync (BG_ADMIN may cover several BGs) OK")

    db.close()
    print("E2E ALL PASSED")


if __name__ == "__main__":
    main()
