# 奖金计算平台（MVP v3）

基于 Python 的线上奖金计算与沟通平台：CSV 导入（版本化、留痕）→ 管理员配置 Curve → 两步式触发计算 → 特殊调整（单人或 CSV 批量、增量、留痕）→ 数据删除（CSV、留痕）→ 封存与导出（按年份 + BG 筛选）→ 角色化查看（员工/多层经理/BG 管理员）→ 奖金通知信（模板 + HTML 邮件 + Curve 区间表 + 已阅追踪）。默认中文界面，支持中/英切换，数据库字段值可通过「语言管理」维护翻译。

## 技术栈

FastAPI + SQLAlchemy 2.x + SQLite + Jinja2 服务端渲染。纯 Python、可读性优先、无外部服务依赖。

## 快速开始

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows；Linux/macOS 用 .venv/bin/pip
.venv/Scripts/python seed.py                    # 重建数据库并写入演示数据
.venv/Scripts/python run.py                     # 启动 http://127.0.0.1:8000
```

演示账号：

| 角色 | 账号 | 密码 | 说明 |
|---|---|---|---|
| 平台管理员 | ADMIN1 | admin123 | 全部后台 |
| BG 管理员（Retail） | BGA1 | BGA1 | BG 视图、通知信 |
| 高层经理（Retail） | SM1 | SM1 | 团队含 N-1 ~ N-3 |
| 经理（Retail） | M001 | M001 | 团队含 N-1 / N-2 |
| 一线经理（Retail） | M003 | M003 | 直属 E001 / E002 |
| 员工 | E001 | E001 | 含 Sales Incentive + Quality Bonus 双计划 |

## 本版核心规则

- **计划以 `plan_name` 为身份**（v3 已移除 `stip_type`）：同一「期间 + 员工 + 计划名」的多个 KPI 行构成一个计划。
- **最终支付率 = 系统加权支付率 + 特殊调整（±百分点）**。调整为增量而非覆盖，可正可负。
- **不存储奖金基数**，系统只计算到「季度 YTD 总支付率」，不计算应付金额。
- **导入的实绩为 YTD 累计值**，系统不做季度间加总。
- **版本化导入**：每条导入数据自动生成时间戳与版本号；有工号按工号匹配、无工号按姓名匹配；重复导入生成新版本，系统始终调用最新（`is_current`）数据，旧版本锁定不可变。
- **软删除 + 留痕**：管理员可删除数据，但必须填写原因；删除逐条写入审计日志（`DataOpLog`），数据本身仅标记删除、不物理清除。
- **员工信息**包含部门名（`department`）与职称（`job_title`）；用户管理页显示「信息更新时间」。

## 界面语言（v3 新增）

- 默认中文，页面右上角可切换 中 / EN（记入 Cookie，下次保持）。
- 静态界面文字内置中英两套；数据库字段值（BG、部门、职称、计划名、KPI 名、Curve 名）通过「语言管理」页维护中英翻译。
- 翻译规则：预设与数据库原始字段值一致；系统内已是中文的值在中文界面直接使用，无需配置。
- 「后台 → 语言管理」可下载全量翻译 CSV（`original,zh,en`）、修改后上传批量更新，也可逐条保存。

## 核心流程（管理员）

1. **导入**（后台 → CSV 导入）：可单独或一起上传，自动版本化
   - `employees.csv`：`employee_id,name,email,bg,department,job_title,manager_id,role,password`（后几列可空，密码缺省为工号）
   - `plans.csv`：`period,employee_id,name,plan_name,kpi_name,weight_pct,quota,curve_name`
   - `actuals.csv`：`period,employee_id,name,kpi_name,actual`（YTD 累计值）
   - `curve_name` 必须先存在。示例见 `sample_data/`。
2. **Curve 管理**：分段线性插值点 `达成率%:支付率%`（如 `0:0,80:50,100:100,150:200`），可设封顶；区间外按端点取值（不外推）。页面展示每段的区间斜率。
3. **两步式触发计算**（后台 → 触发计算）：
   - 第一步：上传计算清单（表头 `period,employee_id,name,plan_name,action`，每行 `action` 填「计算」，可先下载模板）→ 系统第一次读取并校验，展示预览（可计算 / 无计划 / 已封存 / 员工不存在）。
   - 第二步：确认 → 系统第二次读取并执行计算，生成批次（Run）。重复触发生成新批次，视图始终取最新批次。
4. **特殊支付率调整**（后台 → 特殊支付率调整）：
   - 单人：填写增量百分点（可负）与原因，即时生效。
   - **批量（v3 新增）**：下载调整模板（`period,employee_id,name,adjustment_pct,reason`）→ 上传先预览校验（成功/失败逐条标注）→ 确认后执行，逐条留痕；已封存范围自动跳过。
5. **数据删除**（后台 → 数据删除）：下载删除模板 → 在要删除的行 `action` 填 `DELETE` 并填 `reason`（必填）→ 上传执行软删除，逐条留痕；已封存数据不可删除。
6. **封存**：按「期间 + BG」封存，不可撤销；封存后导入、调整、删除、计算均跳过该范围，仅可读取与导出。
7. **导出**（后台 → 导出结果，v3 新增页面）：选择**年份**与 **BG**（均可不选即全部），生成含未加权/加权/调整/最终四类费率的 CSV；BG 管理员仍下载本 BG 完整历史。

## 查看（角色化）

- **员工（我的奖金）**：按年度查看，Q1–Q4 四季度横向排布；未计算的季度留空但显示目标。每个计划（按计划名）展示各 KPI 的目标/达成率/支付率，以及 **未加权支付率、加权支付率、特殊调整、季度总支付率**。年度下拉仅可选当前年度与上一年度。页头显示部门与职称。
- **经理（团队）**：可见向下最多 5 层的整个团队，每人标注相对层级（直属为 N-1，其下属为 N-2，依此类推）；支持按层级筛选（如只看 N-3）、按工号/总支付率排序，并显示团队平均总支付率。
- **BG 管理员（BG 视图）**：本 BG 全员当期结果（含部门/职称）与平均总支付率，可下载本 BG 完整历史。

## 通知信（BG 管理员）

- 收件人以列表选择：支持**筛选**（按姓名/工号检索）、**全选**、**Shift+点击区间多选**，并实时显示已选人数。
- 模板支持占位符 `{{NAME}} {{PERIOD}} {{MESSAGE}} {{PLAN_TABLE}} {{CURVE_SUMMARY}}`，可保存、编辑、另存为新模板。
- **Curve 在信中以表格呈现（v3 新增）**：每条 Curve 按区间列出「达成率范围 → 支付率范围」及**区间斜率**，并注明封顶与否；帮助员工理解「完成多少、支付多少」。
- 信件以 HTML 发出，正文附已阅链接；平台记录发出时间、已阅时间、所用模板。
- **仅收件人本人（或邮件链接的匿名访问者）可确认已阅**；管理员打开信件只能预览、不能代为确认。页面仅一个「确认已阅」按钮。

## 邮件配置

默认无 SMTP 时降级为本地发件箱（`data/outbox/*.html`），便于演示。配置真实发信：

```bash
set SMTP_HOST=smtp.example.com& SMTP_PORT=587& SMTP_USER=...& SMTP_PASSWORD=...& SMTP_FROM=bonus@example.com& BASE_URL=https://your-host
```

（Linux/macOS 用 `export`。）`BASE_URL` 用于生成已阅链接。

## 计算规则

- 达成率 = YTD 实绩 ÷ Quota × 100%；支付率 = Curve 插值（受封顶约束）；缺失实绩按 0 计并标注。
- 未加权支付率 = 各 KPI 支付率的简单平均；加权支付率 = Σ(权重% × 支付率) ÷ 100。
- 季度总支付率（最终）= 加权支付率 + 特殊调整（±百分点）。
- 内部支付率保留四位小数，展示取整到可读位数。

## 测试与目录

```bash
.venv/Scripts/python tests/test_calc.py     # 引擎单测（离线，含端到端计算与区间斜率）
# 先启动服务（.venv/Scripts/python run.py），再：
.venv/Scripts/python tests/test_e2e.py      # 端到端 14 步（导入/两步计算/调整与批量/封存/导出筛选/语言管理/中英切换/多层团队/四季度/已阅）
```

```
app/            应用代码（db/models/curves/calc/csvio/i18n/mailer/security/deps/routers/templates）
data/           SQLite 数据库、密钥、本地发件箱（运行生成）
sample_data/    示例 CSV（v3 新格式：含 department/job_title，无 stip_type）
seed.py         演示数据种子脚本（重建库，含演示翻译词条）
run.py          开发服务器入口
```

## 设计取舍与后续迭代方向（MVP 边界）

- SQLite + 单进程，适合小团队验证；生产建议 PostgreSQL + 部署网关（HTTPS、CSRF 加固、邮件服务化）、以及 Alembic 数据库迁移。
- 期间假设为 `YYYY-Qn` 季度格式；封存不可撤销（符合审计最佳实践）。
- 版本化通过 `version + is_current + is_deleted` 字段实现；如需完整历史回放，可在此基础上扩展审计视图。
- 后续可迭代：计划审批流、多币种、已读提醒、更细的数据权限、金额结算模块。
