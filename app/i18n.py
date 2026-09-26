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
    "letters": ("通知信及计划信息导入", "Letters & Plan Data Import"),
    "letters_short": ("通知信", "Letters"),
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
    "reports_to": ("直线经理：", "Direct manager: "),
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
    "target": ("YTD Quota / Target", "YTD Quota / Target"),
    "sealed_col": ("是否已封存", "Sealed"),
    "attainment": ("达成率", "Attainment"),
    "payout_rate": ("支付率", "Payout Rate"),
    "weighted_rate": ("YTD加权支付率", "YTD Weighted Rate"),
    "weight_total": ("权重合计", "Weight Total"),
    "weight_not_100_comment": ("本次计算权重不是100%", "Weights did not total 100% for this calculation"),
    "special_adjust": ("特殊调整", "Special Adjustment"),
    "quarter_total_rate": ("YTD加权支付率（经特殊调整后）", "YTD Weighted Rate (after special adjustment)"),
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
    "download_bg_kpi_history": ("下载 BG 各 KPI 明细 (CSV)", "Download BG per-KPI detail (CSV)"),
    "send_letter": ("发送奖金通知信", "Send bonus letter"),
    "letter_log": ("通知信记录", "Letter log"),
    "no_members": ("该 BG 暂无成员。", "This BG has no members yet."),

    # ---------- admin dashboard ----------
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
    "proxy": ("代操作", "Proxy"),
    "proxy_confirm": ("确认以该 BG 管理员身份代操作？期间的所有操作将以其身份记录。",
                      "Act as this BG admin? All operations will be recorded under their identity."),
    "proxy_banner": ("您正在以 {name}（BG 管理员）身份代操作", "You are acting as {name} (BG admin)"),
    "proxy_stop": ("退出代操作", "Stop proxying"),
    "msg_proxy_started": ("已进入代操作：{name}（BG 管理员）", "Now acting as {name} (BG admin)"),
    "msg_proxy_stopped": ("已退出代操作，恢复管理员身份", "Proxy ended; admin identity restored"),
    "msg_proxy_bad_target": ("只能代操作启用中的 BG 管理员", "Only active BG admins can be proxied"),
    "users_batch_import": ("批量导入用户（新建 / 更新 / 一致忽略）",
                           "Batch Import Users (create / update / ignore identical)"),
    "users_import_note": ("仅平台管理员可用。工号不存在则新建（不填密码即以工号为初始密码），工号已存在则更新有变化的字段，与系统完全一致的行自动忽略、不报错。先上传预览校验，确认后执行。",
                          "Platform admins only. A new employee ID is created (password defaults to the ID when blank); an existing ID has its changed fields updated; rows fully identical to the system are ignored without error. Upload to preview & validate, then confirm."),
    "fmt_users": ("表头：employee_id,name,email,role,bg,department,job_title,manager_id,password（role 取 ADMIN/BG_ADMIN/MANAGER/EMPLOYEE，缺省 EMPLOYEE；manager_id 填上级工号且上级须已存在；password 可空）",
                  "Header: employee_id,name,email,role,bg,department,job_title,manager_id,password (role is ADMIN/BG_ADMIN/MANAGER/EMPLOYEE, default EMPLOYEE; manager_id is the manager's employee ID and must already exist; password optional)"),
    "row_user_create": ("新建", "Create"),
    "row_user_update": ("更新信息", "Update"),
    "row_user_identical": ("忽略（已存在且信息一致）", "Ignored (exists, identical)"),
    "row_user_dup": ("表内重复（工号或邮箱）", "Duplicate in sheet (employee ID or email)"),
    "row_invalid_role": ("角色无效：{role}", "Invalid role: {role}"),
    "row_no_manager": ("上级不存在：{id}", "Manager not found: {id}"),
    "row_email_taken": ("邮箱已被其他工号占用：{email}", "Email already used by another employee ID: {email}"),
    "user_summary_counts": ("新建 {c} 人 · 更新 {u} 人 · 忽略 {i} 行 · 报错 {e} 行",
                            "Create {c} · update {u} · ignored {i} · errors {e}"),
    "confirm_users_exec": ("确认导入所有「新建 / 更新」行？忽略与报错行不会写入。",
                           "Import all Create/Update rows? Ignored and errored rows will not be written."),
    "msg_users_import": ("导入完成：新建 {c} 人、更新 {u} 人；忽略 {i} 行、报错 {e} 行",
                         "Import done: {c} created, {u} updated; {i} ignored, {e} errored"),

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
    "csv_import": ("主表格导入", "Master Sheet Import"),
    "import_title": ("季度数据大表导入（版本化：重复导入生成新版本，旧版本锁定留档）",
                     "Quarterly Data Import (versioned: re-import creates a new version, old versions are locked)"),
    "import_big_note": ("每季度一张大表：员工信息 + 奖金计划（KPI/权重/目标/Curve）+ YTD 实绩一次传入。先上传预览校验，确认后执行导入。",
                        "One sheet per quarter carries employee info + plan (KPI/weight/quota/curve) + YTD actuals. Upload to preview & validate, then confirm to import."),
    "fmt_big": ("表头：period,employee_id,name,email,bg,department,job_title,manager_id,role,plan_name,kpi_name,weight_pct,quota,curve_name,actual（每行一个 KPI；同一 期间+人员+计划 的 KPI 行构成一个计划）",
                "Header: period,employee_id,name,email,bg,department,job_title,manager_id,role,plan_name,kpi_name,weight_pct,quota,curve_name,actual (one row per KPI; rows sharing period+person+plan form one plan)"),
    "fmt_letter_data": ("表头（年度格式）：year,employee_id,name,email,bg,department,job_title,manager_id,role,plan_name,kpi_name,weight_pct,curve_name,ytd_q1,ytd_q2,ytd_q3,ytd_q4（每行一个 KPI，四个 YTD 目标列分别对应 Q1~Q4；系统按年度展开成各季度计划，空白季度跳过）",
                        "Header (year format): year,employee_id,name,email,bg,department,job_title,manager_id,role,plan_name,kpi_name,weight_pct,curve_name,ytd_q1,ytd_q2,ytd_q3,ytd_q4 (one row per KPI; the four YTD target columns map to Q1-Q4. The system expands each year row into per-quarter plans; blank quarters are skipped)"),
    "user_exists_hint": ("表中人员必须已存在于系统；新员工请先由平台管理员在「用户管理」创建，否则该行报错「员工不存在」。",
                         "People in the sheet must already exist; new hires must first be created by a platform admin under User Management, otherwise the row is reported as Employee not found."),
    "plan_replace_hint": ("同一 期间+人员+计划 的 KPI 行以本次表格为准整体生成新版本（表内应包含该计划的全部 KPI）；与系统内数据完全一致的数据自动忽略、不报错。",
                          "The sheet's KPI rows fully define each plan (include ALL KPIs of the plan); a new version replaces the old one. Data fully identical to the system is ignored without error."),
    "import_submit": ("导入", "Import"),
    "format_docs": ("格式说明", "Format reference"),
    "template_download": ("下载导入模板", "Download import template"),
    "blank_template": ("空白模板", "Blank template"),
    "prefill_hint": ("可选择任意季度，按您的权限预填该季度现有数据（BG 管理员仅限本 BG 范围）",
                     "Pick any quarter to prefill the sheet with existing data within your permission scope (BG admins see only their managed BGs)"),
    "export_prefilled_note": ("用途：导出的预填大表可直接用于业务分析，也可作为下一季度计算的输入模板（改数值后回到本页上传导入）。",
                              "Purpose: the exported prefilled sheet can be used directly for business analysis, or edited and re-uploaded here as the next quarter's input."),
    "year_prefill_hint": ("可选择最近 3 个年份之一，将按您的权限把该年各季度现有计划合并成年度模板（同一个人同一计划的四个季度目标并排为 ytd_q1~ytd_q4）",
                          "Optionally pick one of the 3 most recent years to prefill a year-format template within your permission scope (each person/plan's four quarterly targets are laid side by side as ytd_q1..ytd_q4)"),
    "row_importable": ("可导入", "Importable"),
    "row_identical": ("忽略（与系统数据一致）", "Ignored (identical to system data)"),
    "row_dup": ("表内重复（同期间/人员/计划/KPI）", "Duplicate in sheet (period/person/plan/KPI)"),
    "row_overwritten": ("已被后续行覆盖（新值生效）", "Superseded by a later row (new value wins)"),
    "plan_renamed": ("已存在相同计划（KPI/权重/Curve 一致），计划名将从「{old}」改为「{new}」",
                     "An identical plan (same KPI/weight/Curve) already exists; plan name will change from '{old}' to '{new}'"),
    "plan_suffixed": ("计划名「{old}」已被不同组合占用，自动改名为「{new}」",
                      "Name '{old}' is already used by a different combination; renamed to '{new}' automatically"),
    "row_no_curve": ("Curve 不存在：{name}", "Curve not found: {name}"),
    "row_missing_fields": ("缺失必填项：{f}", "Missing required fields: {f}"),
    "row_bad_number": ("数值无效：{f}", "Invalid number: {f}"),
    "row_out_of_bg": ("超出本 BG 权限", "Outside your BG scope"),
    "summary_counts": ("可导入 {ok} 行 · 忽略 {ig} 行 · 报错 {er} 行",
                       "Importable {ok} · ignored {ig} · errors {er}"),
    "download_errors": ("下载报错清单 CSV", "Download error list CSV"),
    "download_conflicts": ("下载冲突清单 CSV", "Download conflict list CSV"),
    "conflict_counts": ("其中 {n} 行与季度计算数据冲突，已被拦截、不会写入", "{n} row(s) conflict with the quarterly calculation data and were blocked (not written)"),
    "row_letter_conflict": ("与季度计算数据冲突", "Conflicts with quarterly calc data"),
    "row_letter_conflict_note": ("季度大表 {old} ≠ 通知信 {new}", "quarterly sheet {old} ≠ letter {new}"),
    "row_weight_not_100": ("权重合计不是 100%（整个员工拒绝）", "Plan weights don't total 100% (whole employee rejected)"),
    "row_weight_not_100_note": ("计划「{plan}」权重合计不是 100%，该员工的全部行均未导入",
                                "Plan '{plan}' weights don't sum to 100%; none of this employee's rows were imported"),
    "conflict_quarter_detail": ("{q} 目标：季度大表 {old}，通知信 {new}", "{q} target: sheet {old}, letter {new}"),
    "confirm_import_exec": ("确认导入所有「可导入」行？忽略与报错行不会写入。",
                            "Import all Importable rows? Ignored and errored rows will not be written."),
    "msg_big_import": ("导入完成：计划新版本 {p} 个（KPI {k} 行）、实绩更新 {a} 条、员工信息更新 {u} 人；忽略 {i} 行、报错 {e} 行",
                       "Import done: {p} new plan versions ({k} KPI rows), {a} actuals updated, {u} employee records updated; {i} ignored, {e} errored"),
    "msg_no_rows": ("未解析到任何数据行", "No data rows parsed"),
    "kpi_col": ("KPI", "KPI"),
    "curve_col": ("Curve", "Curve"),

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
    "upload_preview": ("上传并预览", "Upload & Preview"),
    "preview_result": ("预览校验结果（第二遍将重新读取并执行）",
                       "Preview & validation (the second pass re-reads and executes)"),
    "preview_note": ("请核对以下清单。只有状态为「可计算/Ready」的行会在第二步被执行。",
                     "Review the list below; only rows marked Ready are executed in the second pass."),
    "confirm_execute": ("确认执行", "Confirm & Execute"),
    "confirm_adjust_exec": ("确认对「可应用」的行批量记录特殊调整？", "Apply all Ready adjustments?"),
    "no_action_rows": ("未解析到任何需要计算的行（action 应为「计算」）",
                       "No rows to calculate (action should be 计算)"),
    "row_ok": ("可计算", "Ready"),
    "row_no_period": ("缺少期间", "Missing period"),
    "row_no_employee": ("员工不存在", "Employee not found"),
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
    "export_note": ("导出为最新计算批次的费率结果（不含奖金基数/金额），按所选年份与 BG 过滤。已封存的数据一并导出，并以 sealed 列标注。",
                    "Exports the latest calculation that covers each record (no bonus base/amounts), filtered by the selected year and BG. Sealed records are included and flagged with a 'sealed' column."),
    "all_years": ("全部年份", "All years"),
    "all_bgs": ("全部 BG", "All BGs"),
    "download_csv": ("下载 CSV", "Download CSV"),
    "export_summary_title": ("表一 · 总支付率（每次计算每人每计划一行）",
                             "Sheet 1 · Total rate (one row per person/plan per run)"),
    "export_summary_note": ("反映每次计算的总支付率：加权支付率、权重合计、特殊调整、季度总支付率；权重合计不是 100% 时在 comment 列标注；已封存记录以 sealed 列=Y 标出并一并导出。不含未加权支付率。",
                            "Total payout rate per run: weighted rate, weight total, adjustment, quarterly total; a comment is flagged when weights do not total 100%; sealed rows are included and marked sealed=Y. No unweighted rate."),
    "export_kpi_title": ("表二 · 各 KPI 明细（每次计算每人每个 KPI 一行）",
                         "Sheet 2 · Per-KPI detail (one row per person/KPI per run)"),
    "export_kpi_note": ("反映每次计算每个人各 KPI 的情况：目标、实绩、Curve、权重、达成率、支付率，以及该 KPI 的加权贡献（weight%×rate）；已封存记录以 sealed 列=Y 标出并一并导出。",
                        "Per-KPI breakdown of each run: target, actual, curve, weight, attainment, payout rate, and the KPI's weighted contribution (weight%×rate); sealed rows are included and marked sealed=Y."),
    "download_summary_csv": ("下载总支付率表", "Download total-rate sheet"),
    "download_kpi_csv": ("下载各 KPI 明细表", "Download per-KPI detail sheet"),

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
    "letter_data_import": ("通知信数据导入", "Letter Data Import"),
    "letter_data_note": ("通知信所用计划数据以「年度格式」在此单独传入：每行一个 KPI，用 year 加四个 YTD 目标列（ytd_q1~ytd_q4）覆盖全年四个季度，系统自动展开成各季度计划（不含 actual 实绩列）。同样先预览校验、确认后导入；与系统一致的数据自动忽略。",
                         "Letter plan data is imported here in YEAR format: one row per KPI with a year plus four YTD target columns (ytd_q1..ytd_q4) covering Q1-Q4; the system expands them into per-quarter plans (no actual column). Preview and confirm as usual; data identical to the system is ignored."),
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
    "letter_body": ("正文（HTML，占位符：{{NAME}} {{EMPLOYEE_ID}} {{EMAIL}} {{BG}} {{DEPARTMENT}} {{JOB_TITLE}} {{MANAGER}} {{PERIOD}} {{PLAN_NAME}} {{MESSAGE}} {{PLAN_TABLE}} {{PERFORMANCE_TABLE}} {{CURVE_SUMMARY}}）",
                    "Body (HTML; placeholders {{NAME}} {{EMPLOYEE_ID}} {{EMAIL}} {{BG}} {{DEPARTMENT}} {{JOB_TITLE}} {{MANAGER}} {{PERIOD}} {{PLAN_NAME}} {{MESSAGE}} {{PLAN_TABLE}} {{PERFORMANCE_TABLE}} {{CURVE_SUMMARY}})"),
    "raw_rate": ("原始支付率", "Raw Rate"),
    "weighted_contribution": ("加权贡献", "Weighted Contribution"),
    "curve_col": ("Curve", "Curve"),
    "plan_col": ("计划", "Plan"),
    "save_as_new": ("另存为新模板", "Save as new template"),
    "template_name": ("模板名称", "Template name"),
    "no_templates": ("暂无模板，请先新建。", "No templates yet — create one first."),
    "templates_shared_note": ("模板在所有管理员之间共享。他人创建的模板为只读，可「复制」后编辑为自己的；平台管理员可删除任意模板。",
                              "Templates are shared across all admins. Others' templates are read-only — use Copy to fork one you can edit; a platform admin can delete any template."),
    "template_owner": ("创建者", "Owner"),
    "template_mine": ("我的", "Mine"),
    "template_read_only": ("只读", "Read-only"),
    "copy": ("复制", "Copy"),
    "copy_and_edit": ("复制并编辑", "Copy & edit"),
    "confirm_delete_template": ("确认删除该模板？此操作不可撤销。", "Delete this template? This cannot be undone."),
    "template_copy_suffix": ("（副本）", " (Copy)"),
    "msg_template_copied": ("已复制模板，现为你的「{name}」，可直接编辑", "Template copied as your '{name}' — you can edit it now"),
    "msg_template_deleted": ("模板 '{name}' 已删除", "Template '{name}' deleted"),
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
    "msg_deleted": ("已删除 {n} 条（均留痕）", "Deleted {n} (all logged)"),
    "msg_missing": ("，未找到 {n} 条", "; {n} not found"),
    "msg_locked_skipped": ("，封存跳过 {n} 条", "; {n} skipped (sealed)"),
    "msg_no_reason": ("，缺原因拒绝 {n} 条", "; {n} rejected (missing reason)"),
    "msg_labels_saved": ("已更新 {n} 条翻译", "Updated {n} translations"),
    "msg_adjust_recorded": ("已记录特殊调整（{period}，{delta} 个百分点），最新结果已同步",
                            "Adjustment recorded ({period}, {delta} pp); latest results refreshed"),
    "msg_adjust_batch": ("批量调整完成：成功 {ok} 条，跳过/失败 {skip} 条",
                         "Batch adjustments done: {ok} applied, {skip} skipped/failed"),
    "msg_calc_skipped": ("，封存跳过 {n} 人", "; {n} skipped (sealed)"),
    "msg_run_created": ("已触发计算 #{rid}（{period}），计算 {n} 人",
                        "Run #{rid} ({period}) finished, {n} computed"),
    "msg_sealed_done": ("已封存 {period} / {bg}，相关记录不再接受改动",
                        "Sealed {period} / {bg}; those records are now read-only"),
    "msg_sealed_exists": ("{period} / {bg} 已封存", "{period} / {bg} is already sealed"),
    "msg_sealed_multi": ("已封存 {period}：本次新封存 {sealed} 个 BG，{already} 个此前已封存",
                         "Sealed {period}: {sealed} BG(s) newly sealed, {already} already sealed"),
    "msg_seal_no_bg": ("请至少选择一个 BG 再封存", "Select at least one BG to seal"),
    "msg_user_created": ("已创建用户 {uid}（初始密码：{pw}）", "User {uid} created (initial password: {pw})"),
    "msg_user_exists": ("工号或邮箱已存在：{uid}", "Employee ID or email already exists: {uid}"),
    "msg_user_toggled": ("已更新用户状态", "User status updated"),
    "msg_users_batch_done": ("批量操作完成：{state} {n} 人，跳过 {skipped} 人",
                             "Batch done: {state} {n} user(s), {skipped} skipped"),
    "msg_users_batch_none": ("没有需要变更的用户（未选择或状态已一致）",
                             "No users changed (nothing selected or already in that state)"),
    "batch_disable": ("批量停用", "Batch disable"),
    "batch_enable": ("批量启用", "Batch enable"),
    "select_all": ("全选", "Select all"),
    "no_users_selected": ("未选择任何用户", "No users selected"),
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
    "bg_multi_hint": ("BG_ADMIN 可用 / | ; 分隔填写多个 BG",
                      "For BG_ADMIN, separate multiple BGs with / | ;"),
    "msg_not_bg_admin": ("目标用户不是 BG_ADMIN", "Target user is not a BG_ADMIN"),
    "msg_managed_bgs_saved": ("已更新 {uid} 管理的 BG：{bgs}",
                              "Updated managed BGs for {uid}: {bgs}"),
    "info_history": ("信息变更历史", "Info change history"),
    "info_history_note": ("每次资料被覆盖前，旧版本会封存于此（is_active=否）",
                          "Superseded snapshots are archived here (is_active = No)"),
    "version": ("版本", "Version"),
    "ended_at": ("封存时间", "Archived at"),
    "changed_by": ("变更人", "Changed by"),
    "no_versions": ("暂无历史版本", "No archived versions yet"),
    "is_active_col": ("启用", "Active"),

    # ---------- curve status (v5.0 #6/#7) ----------
    "curve_status": ("状态", "Status"),
    "curve_active": ("启用中", "Active"),
    "curve_inactive": ("已停用", "Retired"),
    "curve_disable": ("停用", "Retire"),
    "curve_enable": ("启用", "Activate"),
    "confirm_curve_disable": ("停用后新导入将拒绝该 Curve，已计算/已封存数据不受影响。确认停用？",
                              "Retiring rejects this curve for new imports; already-calculated/sealed data is unaffected. Retire it?"),
    "row_curve_inactive": ("该Curve已停用，请联系ADM", "This Curve is retired — contact an admin"),
    "msg_curve_retired": ("Curve '{name}' 已停用（历史数据不受影响）", "Curve '{name}' retired (history unaffected)"),
    "msg_curve_activated": ("Curve '{name}' 已重新启用", "Curve '{name}' re-activated"),
    "int_hint": ("请以整数格式输入", "enter whole numbers only"),
    "points_int_hint": ("插值点请全部使用整数，如 0:0,80:50,100:100",
                        "All interpolation points must be integers, e.g. 0:0,80:50,100:100"),
    "cap_int_hint": ("封顶支付率请填写整数（留空表示不封顶）",
                     "Enter the cap as a whole number (blank = no cap)"),

    # ---------- header translation & exports (v5.0 #2/#12/#13) ----------
    "export_plans": ("计划导出", "Export Plans"),
    "export_plans_note": ("导出全部出现过的计划（KPI 名 / Curve / 权重）及其历史总人-季次与按人季次的平均支付率。",
                          "Export every plan ever used (KPI name / curve / weight) with its total person-quarters and the average payout rate per person-quarter."),
    "export_kpis": ("KPI 导出", "Export KPIs"),
    "export_kpis_note": ("导出全部出现过的 KPI 名字，及其被包含的计划数与按人季次的平均完成率。",
                         "Export every KPI name ever used with how many plans contain it and its average attainment per person-quarter."),
    "dl_plans_csv": ("下载计划清单 CSV", "Download plans CSV"),
    "dl_kpis_csv": ("下载 KPI 清单 CSV", "Download KPIs CSV"),
    "person_quarters": ("人-季次", "person-quarters"),
    "avg_payout_rate": ("平均支付率", "Avg payout rate"),
    "plan_count": ("包含计划数", "Plans containing"),
    "avg_attainment": ("平均完成率", "Avg attainment"),
    "header_translate_note": ("表头本身也走翻译表：导出时按界面语言翻译列名，导入时中英文表头都能识别。",
                              "Column headers are translated too: exports localize header names, imports accept either the English key or its translation."),
    "view_quarter_detail": ("季度详情", "Quarter detail"),

    # ---------- letter-log export (v5.0 #16) ----------
    "export_letters": ("导出通知信记录", "Export letter log"),
    "export_letters_note": ("可导出权限范围内全部通知信记录，或仅指定季度。",
                            "Export all letters in your scope, or only a chosen period."),
    "all_periods_opt": ("全部期间", "All periods"),
    "dl_letters_csv": ("下载通知信记录 CSV", "Download letter log CSV"),
    "msg_users_status_import": ("批量启停完成：启用 {en} 人、停用 {dis} 人，跳过 {sk} 行",
                                "Batch status done: {en} enabled, {dis} disabled, {sk} skipped"),

    # ---------- user batch enable/disable (v5.0 #5) ----------
    "users_status_title": ("批量启停账号", "Batch enable / disable"),
    "users_status_note": ("先「导出用户清单」，在表里把 is_active 改成 Y/N，再上传回来即可批量启停；当前登录的管理员无法停用自身。",
                          "Export the roster, flip the is_active column to Y/N, then upload it back to enable or disable accounts in bulk. You cannot disable your own account."),
    "users_status_preview_note": ("仅标记为「变更」的行会在执行后生效；与现状一致的行会被跳过。",
                                  "Only rows marked as changed take effect; rows already in the desired state are skipped."),
    "user_status_counts": ("变更 {ch} 人 · 无需变更 {ig} 行 · 错误 {er} 行",
                           "{ch} to change · {ig} unchanged · {er} errors"),
    "dl_users_csv": ("导出用户清单 CSV", "Export user roster CSV"),

    # ---------- mail connection self-test (v5.0 #17) ----------
    "mail_test": ("测试邮件连接", "Test mail connection"),
    "mail_test_note": ("仅登录验证 SMTP/POP3 配置，不会真正发信。未配置 SMTP 时系统写入本地发件箱 data/outbox。",
                       "Logs in to verify SMTP/POP3 settings without sending. When SMTP is unset the platform writes to the local data/outbox folder."),
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
    global _label_cache, _alias_map
    _label_cache = None
    _alias_map = None


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


# ---------------- CSV column-header translation (v5.0 requirement #2) ----------------
#
# The translation (Label) table can drive not only the *values* under a column but the
# column HEADER itself: register original='plan_name' with zh='计划名'/en='Plan Name' and
# exports will show that header and imports will accept it. Built-in defaults below give
# a sensible label out of the box; a Label row always wins.

HEADER_DEFAULTS: dict[str, tuple[str, str]] = {
    "period": ("期间", "Period"),
    "employee_id": ("工号", "Employee ID"),
    "name": ("姓名", "Name"),
    "email": ("邮箱", "Email"),
    "bg": ("BG", "BG"),
    "department": ("部门", "Department"),
    "job_title": ("职称", "Job Title"),
    "manager_id": ("直线经理工号", "Manager ID"),
    "role": ("角色", "Role"),
    "plan_name": ("计划名", "Plan Name"),
    "kpi_name": ("KPI 名", "KPI Name"),
    "weight_pct": ("权重%", "Weight %"),
    "quota": ("目标", "Quota"),
    "curve_name": ("Curve 名", "Curve Name"),
    "actual": ("实绩", "Actual"),
    "year": ("年度", "Year"),
    "ytd_q1": ("YTD-Q1", "YTD Q1"),
    "ytd_q2": ("YTD-Q2", "YTD Q2"),
    "ytd_q3": ("YTD-Q3", "YTD Q3"),
    "ytd_q4": ("YTD-Q4", "YTD Q4"),
    "action": ("操作", "Action"),
    "reason": ("原因", "Reason"),
    "version": ("版本", "Version"),
    "imported_at": ("导入时间", "Imported At"),
    "adjustment_pct": ("调整(百分点)", "Adjustment (pp)"),
    "original": ("原始值", "Original"),
    "zh": ("中文", "Chinese"),
    "en": ("英文", "English"),
    "password": ("密码", "Password"),
    "status": ("状态", "Status"),
    "note": ("备注", "Note"),
    "weighted_rate_pct": ("YTD加权支付率", "YTD Weighted Rate"),
    "weight_total_pct": ("权重合计", "Weight Total"),
    "final_rate_pct": ("YTD加权支付率（经特殊调整后）", "YTD Weighted Rate (after adjustment)"),
    "adjusted": ("已调整", "Adjusted"),
    "sealed": ("是否已封存", "Sealed"),
    "comment": ("备注", "Comment"),
    "calculated_at": ("计算时间", "Calculated At"),
    "target": ("目标", "Target"),
    "attainment_pct": ("达成率%", "Attainment %"),
    "rate_pct": ("支付率%", "Payout Rate %"),
    "weighted_contribution_pct": ("加权贡献%", "Weighted Contribution %"),
    "person_quarters": ("人-季次", "Person-Quarters"),
    "avg_payout_rate": ("平均支付率", "Avg Payout Rate"),
    "plan_count": ("包含计划数", "Plans Containing"),
    "avg_attainment": ("平均完成率", "Avg Attainment"),
    "kpi_count": ("KPI 数", "KPI Count"),
    "kpi_structure": ("KPI 结构（KPI · Curve · 权重）", "KPI Structure (KPI · Curve · Weight)"),
    "kpi": ("KPI", "KPI"),
    "curve": ("Curve", "Curve"),
    "weight": ("权重", "Weight"),
    "is_active": ("是否启用", "Is Active"),
    "token": ("令牌", "Token"),
    "recipient_employee_id": ("收件人工号", "Recipient Employee ID"),
    "recipient_name": ("收件人", "Recipient"),
    "template_name": ("模板名", "Template"),
    "subject": ("主题", "Subject"),
    "send_mode": ("发送方式", "Send Mode"),
    "sent_at": ("发送时间", "Sent At"),
    "read_at": ("已读时间", "Read At"),
}


def header_label(key: str, lang: str) -> str:
    """Localized display name for a CSV column key: Label table first, then defaults."""
    zh, en = _labels().get(key, ("", ""))
    if lang == "zh":
        return zh or (HEADER_DEFAULTS.get(key, ("", ""))[0]) or key
    return en or (HEADER_DEFAULTS.get(key, ("", ""))[1]) or key


def translate_headers(cols: list[str], lang: str) -> list[str]:
    """Localize a header row for export (used by every CSV producer)."""
    return [header_label(c, lang) for c in cols]


_alias_map: dict[str, str] | None = None


def invalidate_header_alias_cache() -> None:
    global _alias_map
    _alias_map = None


def _header_aliases() -> dict[str, str]:
    """alias (any accepted header spelling) -> canonical English key. Built from the
    canonical keys, their built-in zh/en defaults, and any Label-table header rows.
    Language-agnostic: an import may present either language."""
    global _alias_map
    if _alias_map is not None:
        return _alias_map
    amap: dict[str, str] = {}

    def add(alias: str, key: str) -> None:
        alias = (alias or "").strip()
        if alias and alias not in amap:
            amap[alias] = key

    for key, (zh, en) in HEADER_DEFAULTS.items():
        add(key, key)          # canonical English wins first
        add(zh, key)
        add(en, key)
    for original, (zh, en) in _labels().items():
        add(original, original)  # a Label row for 'plan_name' also validates the raw key
        if original in HEADER_DEFAULTS:
            add(zh, original)
            add(en, original)
    _alias_map = amap
    return amap


def normalize_header(raw_key: str) -> str:
    """Map an incoming column header (English key OR its zh/en translation) back to the
    canonical English key so parsers stay language-agnostic."""
    k = (raw_key or "").strip()
    if not k:
        return k
    return _header_aliases().get(k, k)
