"""Internationalization: 中文 (default) / English.

Two translation layers:

1. Static UI strings — ``STRINGS`` dictionary, used in templates as ``t('key')``.
2. Database field values (BG, KPI names, curve names, plan names, departments,
   job titles ...) — ``Label`` table lookup, used in templates as ``tl(value)``.
   Default = the original DB value. Values already containing Chinese characters
   are used as-is when the UI language is Chinese（系统内部已中文化的字段直接应用中文）.
"""

from fastapi import Request

LANGS = ("zh", "en")
DEFAULT_LANG = "zh"
LANG_COOKIE = "lang"


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


# key -> (zh, en)
STRINGS: dict[str, tuple[str, str]] = {
    # ---------- global ----------
    "app_title": ("奖金计算平台", "Bonus Platform"),
    "logout": ("退出", "Sign out"),
    "admin_console": ("管理后台", "Admin Console"),
    "bg_view": ("BG 视图", "BG View"),
    "letters": ("通知信", "Letters"),
    "team": ("团队", "Team"),
    "my_bonus": ("我的奖金", "My Bonus"),
    "detail": ("详情", "Detail"),
    "save": ("保存", "Save"),
    "cancel": ("取消", "Cancel"),
    "upload": ("上传", "Upload"),
    "download": ("下载", "Download"),
    "export": ("导出", "Export"),
    "create": ("创建", "Create"),
    "edit": ("编辑", "Edit"),
    "delete": ("删除", "Delete"),
    "confirm": ("确认", "Confirm"),
    "time": ("时间", "Time"),
    "note": ("备注", "Note"),
    "operator": ("操作人", "Operator"),
    "status": ("状态", "Status"),
    "yes": ("是", "Yes"),
    "all": ("全部", "All"),
    "period": ("期间", "Period"),
    "year": ("年度", "Year"),
    "bg": ("BG", "BG"),
    "employee_id": ("工号", "Employee ID"),
    "name": ("姓名", "Name"),
    "email": ("邮箱", "Email"),
    "role": ("角色", "Role"),
    "manager": ("经理", "Manager"),
    "department": ("部门", "Department"),
    "job_title": ("职称", "Job Title"),
    "reports_to": ("汇报给", "Reports to"),
    "info_updated_at": ("信息更新时间", "Info Updated At"),
    "actions": ("操作", "Actions"),
    "optional": ("可选", "optional"),

    # ---------- login ----------
    "login": ("登录", "Sign in"),
    "login_id_label": ("工号或邮箱", "Employee ID or Email"),
    "password": ("密码", "Password"),
    "login_error": ("账号或密码错误", "Invalid credentials"),

    # ---------- person / me ----------
    "bonus_detail": ("奖金详情", "Bonus Detail"),
    "four_quarter_note": ("四个季度横向展示；未计算的季度留空但显示目标。",
                          "Four quarters side by side; uncalculated quarters stay blank but still show targets."),
    "metric": ("指标", "Metric"),
    "target": ("目标", "Target"),
    "attainment": ("达成率", "Attainment"),
    "payout_rate": ("支付率", "Payout Rate"),
    "unweighted_rate": ("未加权支付率", "Unweighted Rate"),
    "weighted_rate": ("加权支付率", "Weighted Rate"),
    "special_adjust": ("特殊调整", "Special Adjustment"),
    "quarter_total_rate": ("季度总支付率", "Quarterly Total Rate"),
    "actual_col": ("实绩", "Actual"),
    "weight_col": ("权重", "Weight"),
    "letter_ack_line": ("请打开以下链接查看并确认已阅：", "Open the link below to view and confirm reading: "),
    "no_plans_year": ("该年度暂无奖金计划。", "No bonus plans for this year."),
    "no_data": ("暂无数据", "No data"),

    # ---------- team ----------
    "my_team": ("我的团队", "My Team"),
    "team_depth_note": ("含向下最多 5 层", "up to 5 levels down"),
    "level_filter": ("层级筛选", "Level Filter"),
    "sort": ("排序", "Sort"),
    "by_level": ("按层级", "By level"),
    "by_id": ("按工号", "By employee ID"),
    "by_rate": ("按总支付率", "By total rate"),
    "clear_filter": ("清除筛选", "Clear filter"),
    "member_count": ("共 {n} 人", "{n} members"),
    "avg_rate": ("已计算成员平均季度总支付率", "Average quarterly total rate of calculated members"),
    "level": ("层级", "Level"),
    "calculated": ("已计算", "Calculated"),
    "not_calculated": ("未计算", "Not calculated"),
    "no_reports": ("暂无下属。", "No direct or indirect reports."),

    # ---------- BG ----------
    "bonus_overview": ("奖金总览", "Bonus Overview"),
    "download_bg_history": ("下载 BG 完整历史 (CSV)", "Download full BG history (CSV)"),
    "send_letter": ("发送奖金通知信", "Send bonus letter"),
    "letter_log": ("通知信记录", "Letter log"),
    "no_members": ("该 BG 暂无成员。", "This BG has no members yet."),

    # ---------- admin dashboard ----------
    "csv_import": ("CSV 导入（员工/计划/实绩）", "CSV Import (employees/plans/actuals)"),
    "trigger_calc": ("触发计算（两步式 CSV）", "Run Calculation (two-pass CSV)"),
    "data_delete": ("数据删除（CSV 留痕）", "Data Deletion (CSV + audit)"),
    "curve_mgmt": ("Curve 管理", "Curve Management"),
    "special_adjustments": ("特殊支付率调整", "Special Payout Adjustments"),
    "user_mgmt": ("用户管理", "User Management"),
    "export_results": ("导出结果（按年份 + BG）", "Export Results (by year + BG)"),
    "language_mgmt": ("语言管理（字段翻译）", "Language Management (field translations)"),
    "trigger_bonus_calc": ("触发奖金计算", "Trigger Bonus Calculation"),
    "period_placeholder": ("如 2026-Q1", "e.g. 2026-Q1"),
    "trigger": ("触发计算", "Run"),
    "calc_runs": ("计算批次", "Calculation Runs"),
    "no_runs": ("尚无计算批次。", "No calculation runs yet."),
    "sealing": ("封存（封存后相关记录不再接受改动，不可撤销）",
                 "Seal (records become read-only afterwards; irreversible)"),
    "confirm_seal": ("封存后该期间该 BG 的记录将不可修改，确认？",
                     "Once sealed, records of this period/BG can no longer be modified. Continue?"),
    "sealed_by": ("封存人", "Sealed by"),
    "no_seals": ("尚无封存记录。", "No seals yet."),
    "seal": ("封存", "Seal"),

    # ---------- users ----------
    "create_user": ("新建用户（不填密码则以工号为初始密码）",
                    "Create user (leave password blank to use employee ID)"),
    "initial_password": ("初始密码", "Initial password"),
    "active": ("启用", "Active"),
    "inactive": ("停用", "Inactive"),
    "disable": ("停用", "Disable"),
    "enable": ("启用", "Enable"),

    # ---------- curves ----------
    "curve_list": ("Curve 列表", "Curves"),
    "new_curve": ("新建 Curve", "New Curve"),
    "edit_curve": ("编辑 Curve", "Edit Curve"),
    "curve_name": ("名称", "Name"),
    "points": ("插值点（达成率%:支付率%）", "Points (attainment%:payout%)"),
    "points_hint": ("逗号分隔，如 0:0,80:50,100:100,150:200", "comma separated, e.g. 0:0,80:50,100:100,150:200"),
    "cap": ("封顶（%）", "Cap (%)"),
    "cap_pct_label": ("封顶支付率 %（可空）", "Cap payout rate % (blank for none)"),
    "description": ("说明", "Description"),
    "interval_slope": ("区间斜率", "Interval Slope"),
    "attainment_range": ("达成率区间", "Attainment Range"),
    "payout_range": ("支付率", "Payout"),
    "no_cap": ("不封顶", "No cap"),
    "no_curves": ("尚无 Curve。", "No curves yet."),
    "updated_at": ("更新时间", "Updated at"),

    # ---------- import ----------
    "import_title": ("CSV 导入（版本化：重复导入生成新版本，旧版本锁定留档）",
                     "CSV Import (versioned: re-import creates a new version, old versions are locked)"),
    "import_one_to_three": ("一次可上传一至三个文件；已封存的（期间 + BG）数据行会被自动跳过。",
                            "Upload one to three files; rows within sealed (period + BG) scopes are skipped automatically."),
    "import_note": ("导入自动记录时间；按工号匹配，无工号时按姓名匹配；实绩为 YTD 累计值，不做跨季加总。",
                    "Imports are auto-timestamped; matched by employee ID, falling back to name; actuals are YTD values and are never summed across quarters."),
    "employees_file": ("员工信息 employees.csv", "Employees (employees.csv)"),
    "plans_file": ("奖金计划 plans.csv", "Plans (plans.csv)"),
    "actuals_file": ("实绩 actuals.csv", "Actuals (actuals.csv)"),
    "import_submit": ("导入", "Import"),
    "format_docs": ("格式说明", "Format reference"),
    "fmt_employees": ("employee_id,name,email,bg,department,job_title,manager_id,role,password（department/job_title/manager_id/role/password 可空，密码缺省为工号）",
                      "employee_id,name,email,bg,department,job_title,manager_id,role,password (all but the first three optional; password defaults to employee ID)"),
    "fmt_plans": ("period,employee_id,name,plan_name,kpi_name,weight_pct,quota,curve_name（同一 期间+员工+plan_name 的多个 KPI 行构成一个计划；plan_name 即该计划的唯一标识）",
                  "period,employee_id,name,plan_name,kpi_name,weight_pct,quota,curve_name (rows sharing period+employee+plan_name form one plan; plan_name is the plan's identity)"),
    "fmt_actuals": ("period,employee_id,name,kpi_name,actual（实绩为 YTD 累计值，系统不做季度加总）",
                    "period,employee_id,name,kpi_name,actual (actuals are YTD; the system never sums quarters)"),
    "fmt_note": ("导入自动生成时间戳与版本号；有工号按工号匹配，无工号按姓名匹配；重复导入生成新版本，系统始终调用最新数据，旧版本锁定。示例见 sample_data/ 目录。",
                 "Imports get automatic timestamps and version numbers; matched by employee ID, or by name when absent; re-imports create new versions while old ones stay locked. See sample_data/ for examples."),

    # ---------- data deletion ----------
    "delete_title": ("数据删除（下载模板 → 标记 action=删除 并填写原因 → 上传）",
                     "Data Deletion (download template → mark action=删除 and fill reason → upload)"),
    "delete_note": ("软删除并写入审计日志；原因为必填，缺失的行会被拒绝。",
                    "Soft delete with audit log; reason is mandatory — rows without one are rejected."),
    "actual_template": ("实绩删除模板", "Actuals delete template"),
    "plan_template": ("计划删除模板", "Plans delete template"),
    "deletion_logs": ("删除留痕记录", "Deletion audit log"),
    "reason": ("原因", "Reason"),
    "entity_ref": ("对象", "Record"),
    "no_logs": ("尚无删除记录。", "No deletions logged."),
    "target_entity": ("目标数据类型", "Target entity"),
    "actual": ("实绩", "Actual"),
    "plan": ("计划", "Plan"),

    # ---------- calculation ----------
    "calc_title": ("触发计算（两步式：先预览校验，再确认执行）",
                   "Run Calculation (two-pass: preview & validate, then confirm)"),
    "calc_note": ("下载模板 → 在 action 列填「计算」→ 上传预览 → 确认后执行。",
                  "Download template → write 计算 in the action column → upload to preview → confirm to execute."),
    "calc_cols_note": ("模板列：period,employee_id,name,plan_name,action。示例：2026-Q3,E001,张伟,销售激励,计算",
                       "Template columns: period,employee_id,name,plan_name,action. Example: 2026-Q3,E001,Zhang Wei,Sales Incentive,计算"),
    "calc_template": ("下载计算模板", "Download calc template"),
    "upload_preview": ("上传并预览", "Upload & Preview"),
    "preview_result": ("预览校验结果（第二遍将重新读取并执行）",
                       "Preview & validation (the second pass re-reads and executes)"),
    "preview_note": ("请核对以下清单。只有状态为「可计算/Ready」的行会在第二步被执行。",
                     "Review the list below; only rows marked Ready are executed in the second pass."),
    "confirm_execute": ("确认执行", "Confirm & Execute"),
    "confirm_calc_exec": ("确认对「可计算」的行执行奖金计算？", "Run the calculation for all Ready rows?"),
    "confirm_adjust_exec": ("确认对「可应用」的行批量记录特殊调整？", "Apply all Ready adjustments?"),
    "no_action_rows": ("未解析到任何需要计算的行（action 应为「计算」）",
                       "No rows to calculate (action should be 计算)"),
    "row_ok": ("可计算", "Ready"),
    "row_no_period": ("缺少期间", "Missing period"),
    "row_no_employee": ("员工不存在", "Employee not found"),
    "row_no_plan": ("无计划", "No plan"),
    "row_sealed": ("已封存", "Sealed"),
    "row_bad_delta": ("调整值无效", "Invalid delta"),
    "row_no_reason": ("缺少原因", "Missing reason"),

    # ---------- adjustments ----------
    "adjust_title": ("特殊支付率调整（在系统加权支付率基础上加/减百分点，单独留痕）",
                     "Special Payout Adjustments (± percentage points on top of weighted rate, audited)"),
    "adjust_note": ("最终支付率 = 系统加权支付率 + 特殊调整。例如系统算出 110%，填 +10 → 最终 120%；填 -5 → 最终 105%。",
                    "Final rate = weighted rate + adjustment. E.g. weighted 110%, +10 → 120%; -5 → 105%."),
    "adjust_delta": ("调整（百分点，可负）", "Delta (pp, may be negative)"),
    "reason_required": ("原因（必填）", "Reason (required)"),
    "record_adjust": ("记录调整", "Record"),
    "batch_upload": ("批量上传（CSV）", "Batch upload (CSV)"),
    "batch_note": ("CSV 列：period,employee_id,name,adjustment_pct,reason；同样先预览后执行，封存范围自动跳过。",
                   "CSV columns: period,employee_id,name,adjustment_pct,reason; preview first, sealed scopes skipped."),
    "adjust_template": ("下载批量调整模板", "Download batch template"),
    "adjust_logs": ("调整记录（审计留痕）", "Adjustment audit log"),
    "no_adjusts": ("尚无调整记录。", "No adjustments yet."),

    # ---------- export ----------
    "export_title": ("导出全部结果（选择年份与 BG）", "Export Results (choose year and BG)"),
    "export_note": ("导出为最新计算批次的费率结果（不含奖金基数/金额），按所选年份与 BG 过滤。",
                    "Exports the latest run's rate results (no bonus base/amounts), filtered by the selected year and BG."),
    "all_years": ("全部年份", "All years"),
    "all_bgs": ("全部 BG", "All BGs"),
    "download_csv": ("下载 CSV", "Download CSV"),

    # ---------- labels / language ----------
    "labels_title": ("语言管理：数据库字段值翻译（默认取数据库原始值）",
                     "Translations for database field values (defaults to the original DB value)"),
    "labels_note": ("适用于 BG、KPI 名、Curve 名、计划名、部门、职称等。已是中文的值在中文界面直接使用；可上传 CSV（original,zh,en）批量更新。",
                    "Applies to BG, KPI names, curve names, plan names, departments and job titles. Values already in Chinese are used as-is in the Chinese UI. Upload CSV (original,zh,en) to update in bulk."),
    "original": ("原始值", "Original"),
    "chinese": ("中文", "Chinese"),
    "english": ("英文", "English"),
    "labels_template": ("下载翻译模板（自动收集库中字段值）", "Download template (auto-collected values)"),
    "labels_import": ("上传翻译 CSV", "Upload translations CSV"),
    "ui_language": ("界面语言", "UI language"),

    # ---------- letters ----------
    "compose_letter": ("撰写通知信", "Compose Letter"),
    "confirm_send": ("确认发送通知信？", "Send these letters?"),
    "template": ("模板", "Template"),
    "new_template": ("新建模板", "New template"),
    "mode_smtp": ("邮件", "Email"),
    "mode_outbox": ("本地发件箱", "Local outbox"),
    "templates_link": ("模板管理", "Manage templates"),
    "recipients": ("接收人", "Recipients"),
    "select_all": ("全选", "Select all"),
    "filter_placeholder": ("筛选：姓名 / 工号 / BG", "Filter: name / ID / BG"),
    "selected_count": ("已选 {n} 人", "{n} selected"),
    "shift_hint": ("提示：按住 Shift 点击可范围多选", "Tip: Shift+click to select a range"),
    "message": ("留言", "Message"),
    "send": ("发送", "Send"),
    "letter_subject": ("主题", "Subject"),
    "letter_body": ("正文（HTML，支持占位符 {{NAME}} {{PERIOD}} {{MESSAGE}} {{PLAN_TABLE}} {{CURVE_SUMMARY}}）",
                    "Body (HTML; placeholders {{NAME}} {{PERIOD}} {{MESSAGE}} {{PLAN_TABLE}} {{CURVE_SUMMARY}})"),
    "save_as_new": ("另存为新模板", "Save as new template"),
    "template_name": ("模板名称", "Template name"),
    "no_templates": ("暂无模板，请先新建。", "No templates yet — create one first."),
    "sent_letters": ("已发送通知信", "Sent letters"),
    "recipient": ("接收人", "Recipient"),
    "sent_at": ("发送时间", "Sent at"),
    "read_at": ("已阅时间", "Read at"),
    "unread": ("未读", "Unread"),
    "send_mode": ("发送方式", "Channel"),
    "no_letters": ("暂无通知信。", "No letters sent."),
    "confirm_read": ("确认已阅", "Confirm read"),
    "already_confirmed": ("已确认阅读", "Reading confirmed"),
    "admin_preview_note": ("您正在以管理员身份预览，仅收件人本人可确认已阅。",
                           "You are previewing as an administrator; only the recipient can confirm reading."),
    "letter_not_found": ("信件不存在或链接无效。", "Letter not found or invalid link."),
    "view_letter": ("奖金通知信", "Bonus Letter"),

    # ---------- misc ----------
    "no_permission": ("无权访问", "Access denied"),
    "back": ("返回", "Back"),
    "no_results": ("该批次没有结果（可能全部被封存跳过）。", "This run has no results (all may have been skipped as sealed)."),
    "err_no_plans": ("期间 {period} 没有可用的奖金计划，请先导入",
                     "No active bonus plans for period {period}; import plans first"),
    "err_sealed": ("该记录已封存，不能再调整", "This record is sealed and can no longer be adjusted"),
    "err_curve_missing": ("Curve '{name}' 不存在", "Curve '{name}' not found"),

    # ---------- CSV result messages ----------
    "msg_emp_import": ("新增 {c} 人，更新 {u} 人，建立汇报关系 {l} 条",
                       "Added {c}, updated {u}, linked {l} reporting lines"),
    "msg_plans_imported": ("导入计划 KPI 行 {n} 条（已生成新版本）",
                           "Imported {n} plan KPI rows (new version created)"),
    "msg_actuals_imported": ("导入实绩 {n} 条（已生成新版本）",
                             "Imported {n} actual rows (new version created)"),
    "msg_sealed_skipped": ("，跳过已封存 {n} 条", "; skipped {n} sealed rows"),
    "msg_errors": ("；错误: {e}", "; errors: {e}"),
    "msg_deleted": ("已删除 {n} 条（均留痕）", "Deleted {n} (all logged)"),
    "msg_missing": ("，未找到 {n} 条", "; {n} not found"),
    "msg_locked_skipped": ("，封存跳过 {n} 条", "; {n} skipped (sealed)"),
    "msg_no_reason": ("，缺原因拒绝 {n} 条", "; {n} rejected (missing reason)"),
    "msg_labels_saved": ("已更新 {n} 条翻译", "Updated {n} translations"),
    "msg_adjust_recorded": ("已记录特殊调整（{period}，{delta} 个百分点），最新结果已同步",
                            "Adjustment recorded ({period}, {delta} pp); latest results refreshed"),
    "msg_adjust_batch": ("批量调整完成：成功 {ok} 条，跳过/失败 {skip} 条",
                         "Batch adjustments done: {ok} applied, {skip} skipped/failed"),
    "msg_calc_done": ("已完成计算 {n} 人", "Calculated {n} people"),
    "msg_calc_skipped": ("，封存跳过 {n} 人", "; {n} skipped (sealed)"),
    "msg_run_created": ("已触发计算 #{rid}（{period}），计算 {n} 人",
                        "Run #{rid} ({period}) finished, {n} computed"),
    "msg_sealed_done": ("已封存 {period} / {bg}，相关记录不再接受改动",
                        "Sealed {period} / {bg}; those records are now read-only"),
    "msg_sealed_exists": ("{period} / {bg} 已封存", "{period} / {bg} is already sealed"),
    "msg_user_created": ("已创建用户 {uid}（初始密码：{pw}）", "User {uid} created (initial password: {pw})"),
    "msg_user_exists": ("工号或邮箱已存在：{uid}", "Employee ID or email already exists: {uid}"),
    "msg_user_toggled": ("已更新用户状态", "User status updated"),
    "msg_curve_saved": ("Curve '{name}' 已保存", "Curve '{name}' saved"),
    "msg_curve_exists": ("Curve 名称已存在：{name}", "Curve name already exists: {name}"),
    "msg_adjust_reason_required": ("特殊调整必须填写原因", "A reason is required for special adjustments"),
    "msg_no_file": ("未上传文件", "No file uploaded"),
    "msg_import_failed": ("导入失败 {e}", "Import failed: {e}"),
    "msg_sent": ("已发出 {n} 封通知信。{mode}", "Sent {n} letters. {mode}"),
    "msg_smtp_on": ("邮件已发送", "Emails delivered"),
    "msg_smtp_off": ("未配置 SMTP，信件已存入本地发件箱 data/outbox",
                     "SMTP not configured; letters saved to local outbox data/outbox"),
    "msg_need_recipient": ("请至少选择一位接收人", "Select at least one recipient"),
    "msg_template_missing": ("模板不存在", "Template not found"),
    "msg_template_saved": ("模板 '{name}' 已保存", "Template '{name}' saved"),
    "msg_ack_done": ("已确认阅读", "Reading confirmed"),
    "msg_ack_denied": ("仅收件人本人可确认已阅", "Only the recipient can confirm reading"),
    "msg_pw_default": ("工号", "employee ID"),
    "msg_pw_custom": ("自定义", "custom"),
}


def get_lang(request: Request) -> str:
    lang = request.cookies.get(LANG_COOKIE, DEFAULT_LANG)
    return lang if lang in LANGS else DEFAULT_LANG


class Translator:
    def __init__(self, lang: str = DEFAULT_LANG):
        self.lang = lang if lang in LANGS else DEFAULT_LANG

    def t(self, key: str, **kwargs) -> str:
        zh, en = STRINGS.get(key, (key, key))
        text = zh if self.lang == "zh" else en
        if kwargs:
            try:
                text = text.format(**kwargs)
            except (KeyError, IndexError):
                pass
        return text

    def tl(self, value) -> str:
        return translate_label(value, self.lang)


# ---------------- database field value translation (Label table) ----------------

_label_cache: dict[str, tuple[str, str]] | None = None


def invalidate_label_cache() -> None:
    global _label_cache
    _label_cache = None


def _labels() -> dict[str, tuple[str, str]]:
    global _label_cache
    if _label_cache is None:
        from sqlalchemy import select

        from .db import SessionLocal
        from .models import Label

        db = SessionLocal()
        try:
            rows = db.scalars(select(Label)).all()
            _label_cache = {r.original: (r.zh or "", r.en or "") for r in rows}
        finally:
            db.close()
    return _label_cache


def translate_label(value, lang: str) -> str:
    """Translate a DB field value. Defaults to the original value."""
    if value is None or value == "":
        return "" if value is None else str(value)
    s = str(value)
    if lang == "zh" and _has_cjk(s):
        return s  # 已中文化的字段直接应用中文
    zh, en = _labels().get(s, ("", ""))
    out = zh if lang == "zh" else en
    return out or s
