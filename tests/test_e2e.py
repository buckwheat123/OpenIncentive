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
from app.models import Actual, BonusPlan, DataOpLog, Letter, LetterTemplate, User  # noqa: E402

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
    # E002 — department changed to Sales South (triggers an employee-info update)
    "2027-Q1,E002,李娜,li.na@example.com,Retail,Sales South,销售代表,M003,EMPLOYEE,Sales Incentive,Revenue,60,1100000,Standard Curve,980000",
    "2027-Q1,E002,李娜,,,,,,,Sales Incentive,Customer Satisfaction,40,90,Quality Curve,88",
    # ---- error rows ----
    "2027-Q1,E999,王五,,,,,,,Sales Incentive,Revenue,60,1000000,Standard Curve,900000",   # unknown user
    "2027-Q1,E002,李娜,,,,,,,Sales Incentive,Revenue,60,1100000,Standard Curve,990000",      # duplicate in sheet
    "2027-Q1,E001,张伟,,,,,,,Sales Incentive,NewKpi,,100,CurveX,50",                          # missing weight_pct
    "2027-Q1,E002,李娜,,,,,,,Sales Incentive,ExtraKpi,50,100,CurveX,50",                      # curve not found
]) + "\n"

# Letter-data sheet (same columns minus `actual`) for a fresh person/period.
LETTER_HEADER = BIG_HEADER.rsplit(",actual", 1)[0]
LETTER_CSV = "\n".join([
    LETTER_HEADER,
    "2027-Q2,E003,赵磊,zhao.lei@example.com,Retail,Sales North,高级销售代表,M001,EMPLOYEE,Sales Incentive,Revenue,60,900000,Standard Curve",
    "2027-Q2,E003,赵磊,,,,,,,Sales Incentive,Customer Satisfaction,40,90,Quality Curve",
]) + "\n"

# BG-scope probe: a Retail row (in scope) + a Commercial row (out of scope for BGA1).
BG_SCOPE_CSV = "\n".join([
    BIG_HEADER,
    "2027-Q3,E001,张伟,zhang.wei@example.com,Retail,Sales East,销售代表,M003,EMPLOYEE,Sales Incentive,Revenue,60,1300000,Standard Curve,1000000",
    "2027-Q3,E004,陈静,chen.jing@example.com,Commercial,Commercial Sales,商务专员,M002,EMPLOYEE,Sales Incentive,Revenue,60,1100000,Standard Curve,900000",
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
        assert "表内重复" in r.text                       # duplicate E002 Revenue
        assert "缺失必填项" in r.text                     # missing weight_pct
        assert "可导入 4 行" in r.text and "报错 4 行" in r.text, r.text[:600]
        print("[2] big-table preview validation (ok/unknown/curve/dup/missing) OK")

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
        print("[3] big-table execute (new plan version, actuals, employee-info update) OK")

        # ---- identical re-upload is IGNORED, not an error, no new version ----
        r = upload(c, f"{BASE}/admin/import/preview", QUARTER_CSV)
        assert "忽略（与系统数据一致）" in r.text, r.text[:600]
        assert "忽略 4 行" in r.text, r.text[:600]
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

        # ---- two-pass calculation for the imported quarter ----
        calc_csv = ("period,employee_id,name,plan_name,action\n"
                    "2027-Q1,E001,张伟,Sales Incentive,计算\n"
                    "2027-Q1,E002,李娜,Sales Incentive,计算")
        r = upload(c, f"{BASE}/admin/calc/preview", calc_csv)
        assert "校验结果" in r.text and "可计算" in r.text, r.text[:600]
        r = c.post(f"{BASE}/admin/calc/execute", data={"csv_text": calc_csv, "note": "e2e"})
        assert "已完成计算" in r.text and "2 人" in r.text, r.text[:600]
        print("[7] two-pass calculation OK")

        # ---- additive special adjustment (single) ----
        r = c.post(f"{BASE}/admin/adjust", data={
            "employee_id": e001.id, "period": "2027-Q1", "adjustment_pct": "10", "reason": "E2E 测试特批"})
        assert "已记录特殊调整" in r.text and "E2E 测试特批" in r.text
        print("[8] additive special adjustment OK")

        # ---- seal blocks adjustments ----
        r = c.post(f"{BASE}/admin/locks", data={"period": "2026-Q1", "bg": "Retail"})
        assert "已封存" in r.text
        r = c.post(f"{BASE}/admin/adjust", data={
            "employee_id": e001.id, "period": "2026-Q1", "adjustment_pct": "50", "reason": "应被拒绝"})
        assert "已封存" in r.text
        print("[9] seal blocks adjustments OK")

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

        # ---- period-filtered template downloads on calc/adjust/delete pages ----
        calc_tpl = c.get(f"{BASE}/admin/calc/template.csv?period=2027-Q1").text
        assert "E001" in calc_tpl and "2026-Q1" not in calc_tpl
        adj_tpl = c.get(f"{BASE}/admin/adjust/template.csv?period=2027-Q1").text
        assert "E001" in adj_tpl and "2026-Q1" not in adj_tpl
        del_tpl = c.get(f"{BASE}/admin/data/delete-template.csv?entity=actual&period=2027-Q1").text
        assert "1150000" in del_tpl and "E001" in del_tpl
        print("[11] period-filtered calc/adjust/delete templates OK")

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

        # ---- BG admin: scoped template + out-of-BG rows rejected ----
        login(c, "BGA1", "BGA1")
        bg_tpl = c.get(f"{BASE}/admin/import/template.csv?period=2026-Q3").text
        assert "E001" in bg_tpl and "E004" not in bg_tpl     # Commercial excluded
        r = upload(c, f"{BASE}/admin/import/preview", BG_SCOPE_CSV)
        assert "可导入" in r.text and "超出本 BG 权限" in r.text, r.text[:600]
        bg_page = c.get(f"{BASE}/bg").text
        assert "奖金总览" in bg_page and "E001" in bg_page and "季度总支付率" in bg_page
        r = c.get(f"{BASE}/bg/export.csv")
        assert "E001" in r.text and "E004" not in r.text
        rk = c.get(f"{BASE}/bg/export_kpi.csv")
        assert "kpi_name" in rk.text and "E001" in rk.text and "E004" not in rk.text
        print("[14] BG admin scope (template filter + out-of-BG rejection + BG view) OK")

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

        # ---- template save-as-new ----
        r = c.post(f"{BASE}/letters/templates/save", data={
            "tid": tpl.id, "name": "季度奖金通知 v2", "subject": "测试主题",
            "body_html": "<p>你好 {{NAME}}</p>", "save_as_new": "true"})
        assert "已保存" in r.text
        assert db.query(LetterTemplate).filter_by(name="季度奖金通知 v2").first()
        print("[17] template save-as-new OK")

        # ---- language management: labels page, CSV upsert ----
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
            "E001,张伟,zhang.wei@example.com,EMPLOYEE,Retail,Sales East,销售代表,M003,\n"   # identical -> ignored
            "E007,吴桐,wu.tong@example.com,EMPLOYEE,Retail,Sales East,销售代表,M999,\n"      # bad manager -> error
            "E005,孙悦,sun.yue@example.com,EMPLOYEE,Retail,Sales East,销售代表,M003,\n"       # duplicate -> error
        )
        r = upload(c, f"{BASE}/admin/users/import/preview", users_csv)
        assert "预览校验结果" in r.text
        assert "新建" in r.text and "忽略（已存在且信息一致）" in r.text, r.text[:600]
        assert "上级不存在" in r.text and "表内重复" in r.text, r.text[:600]
        assert "新建 1 人" in r.text and "报错 2 行" in r.text, r.text[:600]
        r = c.post(f"{BASE}/admin/users/import/execute", data={"csv_text": users_csv})
        assert "导入完成" in r.text and "新建 1 人" in r.text, r.text[:600]
        db.expire_all()
        assert db.query(User).filter_by(employee_id="E005").first() is not None
        users_page = c.get(f"{BASE}/admin/users").text
        assert "E005" in users_page and "孙悦" in users_page
        r = c.post(f"{BASE}/admin/users/import/errors.csv", data={"csv_text": users_csv})
        assert "status" in r.text and "E007" in r.text and "M999" in r.text
        assert "zhang.wei@example.com" not in r.text      # identical/ignored row excluded from errors
        print("[22] batch user import (ADMIN-only, create/ignore/validation) OK")

    db.close()
    print("E2E ALL PASSED")


if __name__ == "__main__":
    main()
