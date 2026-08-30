"""End-to-end test against the running dev server (http://127.0.0.1:8000).

Run order:  .venv/Scripts/python seed.py   then start server   then  .venv/Scripts/python tests/test_e2e.py
"""

import pathlib
import sys

import httpx

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models import Letter, LetterTemplate, User  # noqa: E402

BASE = "http://127.0.0.1:8000"


def login(client: httpx.Client, uid: str, pw: str):
    r = client.post(f"{BASE}/login", data={"login_id": uid, "password": pw}, follow_redirects=True)
    assert r.status_code == 200, f"login failed for {uid}: {r.status_code}"


def main():
    db = SessionLocal()
    with httpx.Client(follow_redirects=True, timeout=30) as c:
        login(c, "ADMIN1", "admin123")
        assert "管理后台" in c.get(f"{BASE}/admin").text
        print("[1] admin login & dashboard OK")

        # ---- versioned CSV import (new format incl. department/job_title, plan_name) ----
        files = {
            "employees": ("employees.csv", open(ROOT / "sample_data/employees.csv", "rb"), "text/csv"),
            "plans": ("plans.csv", open(ROOT / "sample_data/plans.csv", "rb"), "text/csv"),
            "actuals": ("actuals.csv", open(ROOT / "sample_data/actuals.csv", "rb"), "text/csv"),
        }
        r = c.post(f"{BASE}/admin/import", files=files)
        assert "employees:" in r.text and "plans:" in r.text and "actuals:" in r.text, r.text[:400]
        users_page = c.get(f"{BASE}/admin/users").text
        assert "E005" in users_page
        assert "华东销售部" in users_page      # translated department (Label table)
        assert "销售代表" in users_page        # Chinese job title used as-is
        assert "信息更新时间" in users_page
        print("[2] versioned CSV import + employee info (department/job_title/updated_at) OK")

        # ---- two-pass calculation via CSV ----
        calc_csv = "period,employee_id,name,plan_name,action\n2026-Q4,E005,周芳,Sales Incentive,计算\n2026-Q4,E006,吴迪,Sales Incentive,计算"
        r = c.post(f"{BASE}/admin/calc/preview",
                   files={"file": ("calc.csv", calc_csv.encode("utf-8"), "text/csv")})
        assert "校验结果" in r.text and "可计算" in r.text, r.text[:600]
        r = c.post(f"{BASE}/admin/calc/execute", data={"csv_text": calc_csv, "note": "e2e"})
        assert "已完成计算" in r.text and "2 人" in r.text, r.text[:600]
        print("[3] two-pass calculation OK")

        # ---- additive special adjustment (single) ----
        e006 = db.query(User).filter_by(employee_id="E006").first()
        r = c.post(f"{BASE}/admin/adjust", data={
            "employee_id": e006.id, "period": "2026-Q4", "adjustment_pct": "10", "reason": "E2E 测试特批"})
        assert "已记录特殊调整" in r.text and "E2E 测试特批" in r.text
        print("[4] additive special adjustment OK")

        # ---- seal blocks adjustments ----
        r = c.post(f"{BASE}/admin/locks", data={"period": "2026-Q1", "bg": "Retail"})
        assert "已封存" in r.text
        e001 = db.query(User).filter_by(employee_id="E001").first()
        r = c.post(f"{BASE}/admin/adjust", data={
            "employee_id": e001.id, "period": "2026-Q1", "adjustment_pct": "50", "reason": "应被拒绝"})
        assert "已封存" in r.text
        print("[5] seal blocks adjustments OK")

        # ---- batch adjustments via CSV (two-pass) ----
        adj_csv = ("period,employee_id,name,adjustment_pct,reason\n"
                   "2026-Q4,E005,周芳,5,批量测试特批\n"
                   "2026-Q1,E001,张伟,-3,应被跳过：已封存")
        r = c.post(f"{BASE}/admin/adjust/preview",
                   files={"file": ("adj.csv", adj_csv.encode("utf-8"), "text/csv")})
        assert "可计算" in r.text and "已封存" in r.text, r.text[:800]
        r = c.post(f"{BASE}/admin/adjust/execute", data={"csv_text": adj_csv})
        assert "成功 1 条" in r.text and "跳过/失败 1 条" in r.text, r.text[:400]
        assert "批量测试特批" in r.text
        print("[6] batch adjustments via CSV OK")

        # ---- export page + year/BG filtered export ----
        export_page = c.get(f"{BASE}/admin/export").text
        assert "导出全部结果" in export_page and "全部年份" in export_page and "全部 BG" in export_page
        r = c.get(f"{BASE}/admin/export.csv?year=2026&bg=Retail")
        assert r.status_code == 200 and "plan_name" in r.text and "weighted_rate_pct" in r.text
        assert "bonus_amount" not in r.text
        assert "E001" in r.text and "E004" not in r.text  # Commercial excluded by BG filter
        print("[7] export page + year/BG filtered export OK")

        # ---- BG view & scoped export ----
        login(c, "BGA1", "BGA1")
        bg_page = c.get(f"{BASE}/bg").text
        assert "奖金总览" in bg_page and "E001" in bg_page and "季度总支付率" in bg_page
        assert "部门" in bg_page and "职称" in bg_page
        r = c.get(f"{BASE}/bg/export.csv")
        assert "E001" in r.text and "E004" not in r.text
        print("[8] BG view & scoped export OK")

        # ---- letter: curve slope table, admin-preview cannot ack, anonymous acks ----
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
            assert page.text.count('type="submit"') == 1  # exactly one ack button
            anon.post(f"{BASE}/letter/{letter.token}/read")
        db.expire_all()
        assert db.query(Letter).filter_by(id=letter.id).first().read_at is not None
        print("[9] letter with curve slope table + single ack + recipient-only read OK")

        # ---- template save-as-new ----
        r = c.post(f"{BASE}/letters/templates/save", data={
            "tid": tpl.id, "name": "季度奖金通知 v2", "subject": "测试主题",
            "body_html": "<p>你好 {{NAME}}</p>", "save_as_new": "true"})
        assert "已保存" in r.text
        assert db.query(LetterTemplate).filter_by(name="季度奖金通知 v2").first()
        print("[10] template save-as-new OK")

        # ---- language management: labels page, CSV upsert ----
        login(c, "ADMIN1", "admin123")
        labels_page = c.get(f"{BASE}/admin/labels").text
        assert "语言管理" in labels_page and "华东销售部" in labels_page
        labels_csv = "original,zh,en\nTestTerm,测试词,TestTerm"
        r = c.post(f"{BASE}/admin/labels/import",
                   files={"file": ("labels.csv", labels_csv.encode("utf-8"), "text/csv")})
        assert "已更新 1 条翻译" in r.text and "测试词" in r.text
        print("[11] language management (labels page + CSV upsert) OK")

        # ---- UI language switch (default zh, en selectable) ----
        en_page = c.get(f"{BASE}/lang/en", follow_redirects=True).text
        assert "Sign out" in en_page or "Admin Console" in en_page
        zh_page = c.get(f"{BASE}/lang/zh", follow_redirects=True).text
        assert "管理后台" in zh_page and "退出" in zh_page
        print("[12] UI language switch zh/en OK")

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
        print("[13] multi-level manager team + level filter OK")

        # ---- employee self view: 4-quarter horizontal + rates ----
        login(c, "E001", "E001")
        me = c.get(f"{BASE}/me")
        assert "张伟" in me.text
        assert "未加权支付率" in me.text and "加权支付率" in me.text and "季度总支付率" in me.text
        assert "Q4" in me.text               # four quarters shown horizontally
        assert "华东销售部" in me.text        # department shown (translated)
        assert "销售代表" in me.text          # job title shown
        r = c.get(f"{BASE}/admin", follow_redirects=False)
        assert r.status_code == 303
        r = c.get(f"{BASE}/person/{e002.id}", follow_redirects=False)
        assert r.status_code == 303          # peer access denied
        print("[14] employee self view (4-quarter, rates, employee info) & access control OK")

    db.close()
    print("E2E ALL PASSED")


if __name__ == "__main__":
    main()
