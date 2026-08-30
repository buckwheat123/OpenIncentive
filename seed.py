"""Seed demo data. Rebuilds the database with a multi-level hierarchy, four quarters of
YTD data, plan_name-keyed plans, versioned imports, an additive adjustment, field
translations (labels), and a sample letter."""

import json
import os
import secrets
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.db import DB_PATH, SessionLocal, init_db  # noqa: E402
from app.models import (Actual, BonusPlan, Curve, Label, Letter, LetterTemplate,  # noqa: E402
                        PlanKpi, User)
from app.security import hash_password  # noqa: E402
from app.calc import apply_adjustment, run_calculation  # noqa: E402
from app.i18n import Translator, invalidate_label_cache  # noqa: E402
from app.mailer import send_mail  # noqa: E402
from app.routers.letters import render_letter_body  # noqa: E402

# employee_id, name, email, bg, department, job_title, role, manager_ext, password
USERS = [
    ("ADMIN1", "平台管理员", "admin@example.com", None, None, None, "ADMIN", None, "admin123"),
    ("BGA1", "Linda Chen", "linda.chen@example.com", "Retail", "Retail Management", "BG Director", "BG_ADMIN", None, "BGA1"),
    ("SM1", "郑国安", "zheng.guonan@example.com", "Retail", "Sales Management", "销售副总裁", "MANAGER", None, "SM1"),
    ("M001", "王强", "wang.qiang@example.com", "Retail", "Sales Management", "销售总监", "MANAGER", "SM1", "M001"),
    ("M003", "孙浩", "sun.hao@example.com", "Retail", "Sales East", "区域经理", "MANAGER", "M001", "M003"),
    ("E001", "张伟", "zhang.wei@example.com", "Retail", "Sales East", "销售代表", "EMPLOYEE", "M003", "E001"),
    ("E002", "李娜", "li.na@example.com", "Retail", "Sales East", "销售代表", "EMPLOYEE", "M003", "E002"),
    ("E003", "赵磊", "zhao.lei@example.com", "Retail", "Sales North", "高级销售代表", "EMPLOYEE", "M001", "E003"),
    ("M002", "刘洋", "liu.yang@example.com", "Commercial", "Commercial Sales", "商务经理", "MANAGER", None, "M002"),
    ("E004", "陈静", "chen.jing@example.com", "Commercial", "Commercial Sales", "商务专员", "EMPLOYEE", "M002", "E004"),
]

CURVES = [
    ("Standard Curve", "营收达成支付曲线：50% 门槛以下不支付", [[0, 0], [50, 0], [80, 50], [100, 100], [120, 150], [150, 200]], 200),
    ("Quality Curve", "客户满意度支付曲线", [[0, 0], [80, 40], [90, 80], [100, 100], [110, 120]], 130),
]

# original -> (zh, en)；已含中文的值在中文界面直接使用
LABELS = [
    ("Retail", "零售", "Retail"),
    ("Commercial", "商业", "Commercial"),
    ("Sales Management", "销售管理部", "Sales Management"),
    ("Sales East", "华东销售部", "Sales East"),
    ("Sales North", "华北销售部", "Sales North"),
    ("Commercial Sales", "商业销售部", "Commercial Sales"),
    ("Retail Management", "零售管理部", "Retail Management"),
    ("BG Director", "BG 负责人", "BG Director"),
    ("Revenue", "销售收入", "Revenue"),
    ("Customer Satisfaction", "客户满意度", "Customer Satisfaction"),
    ("Standard Curve", "标准曲线", "Standard Curve"),
    ("Quality Curve", "质量曲线", "Quality Curve"),
    ("Sales Incentive", "销售激励计划", "Sales Incentive"),
    ("Quality Bonus", "质量专项激励", "Quality Bonus"),
    ("Sales Rep", "销售代表", "Sales Rep"),
]

QUARTERS = ["Q1", "Q2", "Q3", "Q4"]
CALC_QUARTERS = ["Q1", "Q2", "Q3"]  # Q4 left uncalculated to demo blank-with-target

# 每名销售员工的 YTD 营收 quota 基数与逐季达成率、CS 实绩
SALES = {
    "E001": {"base": 1300000, "attain": {"Q1": 104, "Q2": 102, "Q3": 99}, "cs": {"Q1": 92, "Q2": 94, "Q3": 90}},
    "E002": {"base": 1000000, "attain": {"Q1": 90, "Q2": 95, "Q3": 101}, "cs": {"Q1": 88, "Q2": 90, "Q3": 93}},
    "E003": {"base": 900000, "attain": {"Q1": 110, "Q2": 96, "Q3": 88}, "cs": {"Q1": 95, "Q2": 91, "Q3": 86}},
    "E004": {"base": 1100000, "attain": {"Q1": 98, "Q2": 103, "Q3": 106}, "cs": {"Q1": 91, "Q2": 93, "Q3": 95}},
}
CS_QUOTA = 90

TEMPLATE_BODY = """<p>{{NAME}}，你好：</p>
<p>{{MESSAGE}}</p>
<p>以下是你 {{PERIOD}} 的奖金计划与结果：</p>
{{PLAN_TABLE}}
<p>所用支付 Curve（达成率 → 支付率，含区间斜率）：</p>
{{CURVE_SUMMARY}}
<p>如有疑问，请与你的经理或 BG 管理员联系。</p>"""


def _add_plan(db, period, emp, plan_name, kpis, version=1):
    plan = BonusPlan(period=period, employee_id=emp.id, plan_name=plan_name,
                     version=version, is_current=True,
                     imported_at=datetime.now(timezone.utc))
    db.add(plan)
    db.flush()
    for kpi_name, weight, quota, curve in kpis:
        db.add(PlanKpi(plan_id=plan.id, kpi_name=kpi_name, weight_pct=weight,
                       quota=quota, curve_id=curve.id))
    return plan


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    db = SessionLocal()

    users = {}
    for emp_id, name, email, bg, dept, title, role, mgr, password in USERS:
        user = User(employee_id=emp_id, name=name, email=email, bg=bg,
                    department=dept, job_title=title, role=role,
                    password_hash=hash_password(password))
        db.add(user)
        users[emp_id] = user
    db.flush()
    for row in USERS:
        emp_id, mgr = row[0], row[7]
        if mgr:
            users[emp_id].manager_id = users[mgr].id
    db.commit()

    curves = {}
    for name, desc, points, cap in CURVES:
        curve = Curve(name=name, description=desc, points_json=json.dumps(points), cap_pct=cap,
                      created_by=users["ADMIN1"].id)
        db.add(curve)
        curves[name] = curve
    db.commit()

    for original, zh, en in LABELS:
        db.add(Label(original=original, zh=zh, en=en))
    db.commit()
    invalidate_label_cache()

    # ---- plans: Sales Incentive for all, Q1..Q4 (Q4 stays uncalculated) ----
    for emp_id, cfg in SALES.items():
        emp = users[emp_id]
        for qi, q in enumerate(QUARTERS, start=1):
            period = f"2026-{q}"
            ytd_quota = cfg["base"] * qi
            _add_plan(db, period, emp, "Sales Incentive", [
                ("Revenue", 60, ytd_quota, curves["Standard Curve"]),
                ("Customer Satisfaction", 40, CS_QUOTA, curves["Quality Curve"]),
            ])
    # E001 额外一个 Quality Bonus 计划，演示同一人多计划
    for qi, q in enumerate(["Q1", "Q2", "Q3"], start=1):
        _add_plan(db, f"2026-{q}", users["E001"], "Quality Bonus", [
            ("Customer Satisfaction", 100, CS_QUOTA, curves["Quality Curve"]),
        ])
    db.commit()

    # ---- YTD actuals for Q1..Q3 ----
    for emp_id, cfg in SALES.items():
        emp = users[emp_id]
        for qi, q in enumerate(CALC_QUARTERS, start=1):
            period = f"2026-{q}"
            ytd_quota = cfg["base"] * qi
            revenue_actual = round(ytd_quota * cfg["attain"][q] / 100.0, 2)
            db.add(Actual(period=period, employee_id=emp.id, kpi_name="Revenue",
                          actual=revenue_actual, version=1, is_current=True))
            db.add(Actual(period=period, employee_id=emp.id, kpi_name="Customer Satisfaction",
                          actual=cfg["cs"][q], version=1, is_current=True))
    db.commit()

    # ---- run calculation for Q1..Q3 ----
    for q in CALC_QUARTERS:
        run, stats = run_calculation(db, f"2026-{q}", users["ADMIN1"], note="种子数据计算")
        print(f"计算 2026-{q}: {stats}")

    # ---- additive special adjustment: E003 2026-Q3 +10 个百分点 ----
    apply_adjustment(db, users["E003"].id, "2026-Q3", 10.0, "BG 特批：重大项目支持贡献", users["ADMIN1"])
    print("已为 E003 2026-Q3 添加特殊调整 +10 个百分点（加权 + 调整 = 最终）")

    # ---- sample letter ----
    template = LetterTemplate(name="季度奖金通知", bg="Retail", subject="2026-Q3 奖金结果通知",
                              body_html=TEMPLATE_BODY, created_by=users["BGA1"].id)
    db.add(template)
    db.commit()
    token = secrets.token_urlsafe(16)
    body = render_letter_body(db, template, users["E001"], "2026-Q3", "感谢本季度的出色表现！",
                              token, Translator("zh"))
    mode = send_mail(users["E001"].email, template.subject, body)
    db.add(Letter(token=token, template_id=template.id, template_name=template.name,
                  recipient_id=users["E001"].id, period="2026-Q3", subject=template.subject,
                  body_html=body, sent_by=users["BGA1"].id, send_mode=mode))
    db.commit()
    print(f"已向 E001 发送示例通知信（{mode}）")

    print("\n种子数据完成。登录账号：")
    print("  平台管理员  ADMIN1 / admin123")
    print("  BG 管理员   BGA1  / BGA1     （Retail）")
    print("  高层经理    SM1   / SM1      （Retail，团队含 N-1~N-3）")
    print("  经理        M001  / M001     （Retail，团队含 N-1/N-2）")
    print("  一线经理    M003  / M003     （Retail，直属 E001/E002）")
    print("  员工        E001  / E001     （含 Sales Incentive + Quality Bonus 双计划）")
    db.close()


if __name__ == "__main__":
    main()
