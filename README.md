# OpenIncentive

> 🌐 **English** | [中文](#chinese)

## 💡 Why I Built This Project

I created OpenIncentive because I'm fed up with SaaS products that deliver little to no value — or even negative value.

I hope this project can help anyone — whether you're a department, a company, a project team, or any stakeholder who wants (or is forced) to implement a sales incentive system — to have something simple, effective, and low-cost to operate. I also hope every SaaS company will reflect on whether their annual fees are truly worth it.

If you find this useful, feel free to ⭐ Star / Fork / open an Issue. Any form of support is deeply appreciated! 🙏

A quick note about me: I'm not a programmer. I rely heavily on AI Agent tools to build this. So I may not be able to answer technical questions, and I'll likely struggle to decide whether to merge your changes. I might also only get a chance to check in once every week or two. But all communication is welcome — I just might not respond promptly.

I'm just a butterfly flapping its wings wildly, hoping one day it will create a butterfly effect.

If you're curious about the story behind this project, you can find my story at the very end of this README.

---

<a id="chinese"></a>

## 💡 为什么做这个项目

我创建 OpenIncentive 是因为我受够了没有价值甚至是负价值的SaaS。

希望这个项目能帮到每个希望或被"强迫"上销售奖金系统的部门或公司或项目团队或任何一个相关方，都能够有一个简洁有效及低运营成本的系统。也希望每个SaaS公司都能好好反思他们的年费是不是真的值得。

如果你觉得有用，欢迎 ⭐ Star / Fork / 提 Issue，任何形式的支持都很感谢！🙏

我是个编程外行，很依赖AI Agent工具。所以我可能没法回答一些技术问题，也很难决定是不是要合并你的改动。我也可能一两周才有机会上来看一眼。但任何交流都是欢迎的，我只是可能没法及时反馈。

我只是一只疯狂挥动翅膀的蝴蝶，期望有一天能产生"蝴蝶效应"。

如果你对项目背景有些好奇，在readme的最后有我的故事。

---

# 奖金计算平台（MVP v5.0）

> 版本历史见 [CHANGELOG.md](CHANGELOG.md)。

基于 Python 的线上奖金计算与沟通平台：**主表格导入**（一张表、版本化、校验 + 留痕，与系统一致的数据静默忽略，计划名按组合唯一化）→ **通知信数据导入**（独立页面、年度格式、权重合计≠100% 整员工拒绝、与季度计算数据冲突自动拦截并可导出冲突清单）→ 管理员配置 **Curve** → **一键触发计算** → **特殊调整**（单人或 CSV 批量、增量、留痕）→ **数据删除**（CSV、留痕）→ **封存** → **导出（两张表：总支付率 + 各 KPI 明细）** + **季度预填大表导出**（供业务分析与下季计算改写）→ **角色化查看**（员工 / 多层经理 / BG 管理员，BG 管理员可多对多管理多个 BG）→ **代操作**（平台管理员代理 BG 管理员）→ **批量导入用户**（仅平台管理员，员工信息变更自动版本化封存留痕）→ **奖金通知信**（模板全员共享、他人只读可复制、计划/绩效两张表占位符 + HTML 邮件 + Curve 区间表 + 已阅追踪）。默认中文界面，支持中/英切换，数据库字段值可通过「语言管理」维护翻译。并提供 **backup.py / restore.py / reset_empty.py** 三个运维脚本做整库快照、一键回滚与空白起步。

## 技术栈

FastAPI + SQLAlchemy 2.x（`Mapped[]` 类型化列）+ SQLite + Jinja2 服务端渲染。会话用 itsdangerous 签名 Cookie，口令用 PBKDF2 加盐哈希。纯 Python、可读性优先、无外部服务依赖。数据库以 `create_all` 建表（无迁移）——**改动模型后需重新运行 `seed.py` 重建库**。

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
| 平台管理员 | ADMIN1 | admin123 | 全部后台，可代操作任一 BG 管理员 |
| BG 管理员（Retail + Commercial） | BGA1 | BGA1 | 同时管理两个 BG；BG 视图、导入、通知信 |
| BG 管理员（Retail，与 BGA1 共管） | BGA2 | BGA2 | 演示一个 BG 可由多名 BG 管理员共管 |
| 高层经理（Retail） | SM1 | SM1 | 团队含 N-1 ~ N-3 |
| 经理（Retail） | M001 | M001 | 团队含 N-1 / N-2 |
| 一线经理（Retail） | M003 | M003 | 直属 E001 / E002 |
| 员工 | E001 | E001 | 含 Sales Incentive + Quality Bonus 双计划 |

## 本版核心规则（v5.0）

- **计划以 `plan_name` 为身份**：同一「期间 + 员工 + 计划名」的多个 KPI 行构成一个计划。
- **计划名按组合唯一（跨 BG 且跨季度，#11）**：**全库范围**内（不再局限于单一期间），一套独特的 `(KPI, Curve, 权重)` 组合只对应一个计划名（Quota 不计入签名）。导入时若「同组合、不同名」则**自动并入既有计划名并提示改名**（即便该组合首次在别的 BG / 别的季度出现也沿用最早登记的名字）；若「同名、不同组合」则**按传入顺序自动追加 `_v1` / `_v2` 后缀**。
- **通知信权重必须合计 100%（F1）**：通知信数据导入按「员工 + 期间 + 计划」校验权重合计，只要某员工任一计划≠100%（容差 1e-6）即**整员工全部行拒绝、不导入**，其余员工照常。计算大表不受此约束（口径仍是加权加总、绝不归一化，仅记录 `weight_total_pct` 并在导出批注）。
- **YTD 加权支付率按原状加权加总、不归一化**：`YTD加权支付率 = Σ(权重% × 支付率) ÷ 100`。当某计划 KPI 权重合计不是 100% 时，支付率随其等比缩放——这有时是正常/有意的，系统不改数值，仅记录当次计算的权重合计（`weight_total_pct`）并在导出 `comment` 列标注「本次计算权重不是100%」。
- **系统不提供未加权（简单平均）支付率**（已从模型 / 计算 / 导出 / 视图 / 通知信 / 文案全量移除）。
- **最终支付率 = YTD 加权支付率 + 特殊调整（±百分点）**。调整为增量而非覆盖，可正可负。员工界面里：常态显示「YTD加权支付率」，**仅当该员工当年确有过特殊调整时**才额外显示「YTD加权支付率（经特殊调整后）」这一行（#8）。
- **季度尚未录入实绩时留空（#1）**：某 KPI 尚无实际业绩时，其达成率 / 支付率 / 加权贡献一律留空（不再按 0 计），也不计入该计划的加权；一旦导入实绩再计算即自动补齐。
- **Curve 封顶与插值点强制整数（#6）**：封顶支付率与各插值点均须为整数，输入小数即报错并提示「请以整数格式输入」，且不落库。
- **Curve 可停用、不影响历史（#7）**：管理员可停用某 Curve；已计算 / 已封存的数据完全不受影响；但一旦把引用了停用 Curve 的行提交导入，会被拒绝并提示「该Curve已停用，请联系ADM」。
- **不存储奖金基数**，系统只计算到「YTD 总支付率」，不计算应付金额。
- **导入的实绩为 YTD 累计值**，系统不做季度间加总。
- **版本化导入 + 一致即忽略**：每条导入数据自动生成时间戳与版本号；有工号按工号匹配、无工号按姓名匹配；重复导入生成新版本，系统始终调用最新（`is_current`）数据，旧版本锁定不可变；**与系统完全一致的数据静默忽略，不算错误**。
- **软删除 + 留痕**：删除必须填写原因，逐条写入审计日志（`DataOpLog`），数据仅标记删除、不物理清除。
- **员工信息**含部门（`department`）与职称（`job_title`）；用户管理页显示「信息更新时间」。
- **计算时点快照（#4）**：每次计算把当时的姓名 / 工号 / BG / 部门 / 职称冻结进结果（`snapshot_*`）。员工换部门后，**旧季度仍按旧部门展示，之后的新计算才反映新部门**；旧信息在改动作废前自动封存为 `UserVersion` 留痕。
- **BG 多对多**：一名 BG 管理员可管理多个 BG，一个 BG 也可由多名管理员共管（`UserManagedBg` 关联表）。BG 视图、导入模板、导出、通知信收件人都按管理员所辖 BG 集合并集过滤；BG 管理员姓名旁与页面标题会列出其全部所辖 BG。平台管理员可在「用户管理」页内联编辑每位 BG 管理员的所辖 BG 集合。
- **查看权限分层（#3 / #14）**：ADM 与 BG 管理员可从各自界面下钻查看某员工某季度详情；**员工本人的「我的奖金」页不再展示信息变更历史**，「汇报给」措辞统一为「直线经理：」。
- **批量启停账号（#5）**：平台管理员可导出用户花名册（本地化表头），改其中的 `is_active` 列后整表上传，批量停用 / 启用账号（操作者本人自动跳过）。
- **代操作留痕**：平台管理员代理 BG 管理员的开始与结束均写入审计日志（`op_type=PROXY`）。
- **全站界面重构（#10）**：统一为高对比黑白、大号粗体无衬线、锐利直角 + 能量色强调的运动风视觉（纯 CSS、无构建工具、CDN 字体），中英双语一致。

## 界面语言

- 默认中文，页面右上角可切换 中 / EN（记入 Cookie，下次保持）。
- 静态界面文字内置中英两套；数据库字段值（BG、部门、职称、计划名、KPI 名、Curve 名）通过「语言管理」页维护中英翻译。
- **表头也可翻译（#2）**：各类导入模板与导出 CSV 的列名（如 `plan_name` → 中「计划名」/ 英「Plan Name」）默认走内置表头字典，并可在「语言管理」里用同名 label 覆盖成任意措辞；导入解析对语言无关（中英文表头都能识别）。
- 翻译规则：预设与数据库原始字段值一致；系统内已是中文的值在中文界面直接使用，无需配置。
- 「后台 → 语言管理」可下载全量翻译 CSV（`original,zh,en`）、修改后上传批量更新，也可逐条保存。

## 核心流程（管理员）

1. **主表格导入**（后台 → 主表格导入，BG 管理员亦可用）：一张表搞定人员 + 计划 + KPI + 实绩，每行一个 KPI。
   - 表头：`period,employee_id,name,email,bg,department,job_title,manager_id,role,plan_name,kpi_name,weight_pct,quota,curve_name,actual`
   - 可下载模板：空白模板，或按**指定季度预填**（F6，权限内、按 BG 范围，季度下拉可选任意有数据的期间）——把该季度现有计划 / 目标 / 实绩 / Curve 预先填成大表下载，供业务分析或改写到下一季度后再上传。
   - 两步式：上传 → **预览校验**（逐条标注 可导入 / 忽略 / 报错，并给出汇总）→ 确认执行。
   - 校验项：必填、`curve_name` 是否已存在、表内重复、员工不存在等；报错行可下载 **errors.csv** 修正后重传；**与系统完全一致的行自动忽略**（不算错误）。示例见 `sample_data/quarter_import.csv`。
2. **通知信数据导入**（独立页面，BG 管理员 / 平台管理员）：以**年度格式**传入通知信所需的人员与计划数据——每行一个 KPI，用 `year` 加四个 YTD 目标列（`ytd_q1~ytd_q4`）覆盖全年四个季度，系统自动按年度**展开成各季度计划**（空白季度跳过），复用大表的解析 / 最新覆盖 / 版本化流程。
   - 表头：`year,employee_id,name,email,bg,department,job_title,manager_id,role,plan_name,kpi_name,weight_pct,curve_name,ytd_q1,ytd_q2,ytd_q3,ytd_q4`
   - 可下载模板：空白模板，或按**最近年份预填**（把权限内该年各季度现有计划并排成四个 YTD 列）作为起点。
   - 同样不含 `actual` 实绩列；两步式预览 → 确认执行。
   - **权重合计≠100% 整员工拒绝（F1）**：按「员工 + 期间 + 计划」汇总权重，任一计划合计不等于 100% 时，**该员工的全部行整体标记「权重合计不是 100%（整个员工拒绝）」并一律不导入**（提示指向具体计划与其权重合计），其余员工行照常导入。此约束只作用于通知信导入，计算大表允许≠100% 的权重（见「本版核心规则」）。
   - **与季度计算数据冲突自动拦截**：当展开后的「期间 + 员工 + 计划 + KPI」在系统里已有当期计划、且目标值不同，预览阶段即把该行标记为「与季度计算数据冲突」并拒绝写入（季度计算数据为准），第二遍执行也再次校验确保不落库；非冲突行照旧最新版本覆盖。冲突行可下载**冲突清单 CSV**（`/letters/data/conflicts.csv`），逐行标注季度现有值与通知信传入值，便于人工核对。示例见 `sample_data/letter_data.csv`。
3. **Curve 管理**：分段线性插值点 `达成率%:支付率%`（如 `0:0,80:50,100:100,150:200`），可设封顶；区间外按端点取值（不外推）。页面展示每段的区间斜率。
4. **一键触发计算**（后台 → 计算批次）：选定期间点击触发即对该期间全部 current 计划执行计算，生成批次（Run）；已封存「期间 + BG」自动跳过并计入留痕。重复触发生成新批次。**（F2）** BG / 团队 / 个人视图取「该期间所有批次中每人每计划的最新结果」，因此封存后再次触发（跳过已封存人员）也不会让已算好的人员回退成「未计算」。批次详情页展示每人每 KPI 明细，并在权重合计≠100% 时内联告警。
5. **特殊支付率调整**（后台 → 特殊支付率调整）：
   - 单人：填写增量百分点（可负）与原因，即时生效。
   - 批量：下载调整模板（`period,employee_id,name,adjustment_pct,reason`）→ 预览校验 → 确认执行，逐条留痕；已封存范围自动跳过。
6. **数据删除**（后台 → 数据删除）：下载删除模板（可按季度筛选）→ 在要删除的行 `action` 填 `DELETE` 并填 `reason`（必填）→ 上传执行软删除，逐条留痕；已封存数据不可删除。
7. **封存**：按「期间 + BG」封存，不可撤销；封存后导入、调整、删除、计算均跳过该范围，仅可读取与导出。
8. **导出结果**（后台 → 导出结果）：选择**年份**与 **BG**（均可不选即全部），页面上共四个下载按钮，表头均随界面语言本地化：
   - **表一 · 总支付率**（`bonus_results*.csv`）：每次计算每人每计划一行。列 `period,employee_id,name,bg,department,job_title,plan_name,weighted_rate_pct,weight_total_pct,adjustment_pct,final_rate_pct,adjusted,comment,calculated_at`（其中 `weighted_rate_pct`→「YTD加权支付率」、`final_rate_pct`→「YTD加权支付率（经特殊调整后）」）。权重合计≠100% 时 `comment` 标注「本次计算权重不是100%」；**不含未加权支付率**。
   - **表二 · 各 KPI 明细**（`bonus_kpi_detail*.csv`）：每次计算每人每个 KPI 一行，取自计算时留存的 `detail_json`。列含 `kpi_name,target,actual,curve_name,weight_pct,attainment_pct,rate_pct,weighted_contribution_pct,sealed`（**实绩尚空的 KPI，`actual/attainment_pct/rate_pct` 留空**）。
   - **表三 · 计划清单（#12）**（`bonus_plans*.csv`）：全部计划各一行，列出 KPI 数、`KPI 结构（KPI · Curve · 权重）`、累计被计算的**人-季次**与**按人季次的平均支付率**，供横向比较各计划的激励力度。
   - **表四 · KPI 清单（#13）**（`bonus_kpis*.csv`）：全部 KPI 名各一行，列出**被多少计划包含**与**按人季次的平均完成率**。
9. **代操作（proxy）**：平台管理员在「用户管理」页对任一在职 BG 管理员点击「代操作」，即以其身份进入 BG 视图 / 导入 / 通知信等页面；页面顶部显示醒目横幅，「退出代操作」一键恢复。开始与结束均写入审计日志，期间的导入在原因中标注 proxy 来源。BG 管理员越权访问后台会被拒绝。
10. **批量导入用户 / 批量启停账号（仅平台管理员）**：在「用户管理」页下载模板（`employee_id,name,email,role,bg,department,job_title,manager_id,password`，表头随语言本地化）→ 上传预览校验 → 确认执行。幂等 upsert：**工号不存在则新建**（`password` 留空即以工号为初始密码）、**已存在则只更新有变化的字段**、**与系统完全一致的行自动忽略**（可反复上传同一份花名册）。校验：必填、角色合法性（ADMIN/BG_ADMIN/MANAGER/EMPLOYEE）、表内工号或邮箱重复、邮箱被其他工号占用。逐条留痕，报错行可下载 errors.csv。示例见 `sample_data/users_import.csv`。
    - **批量启停（#5）**：另可下载**用户花名册**（`工号,姓名,邮箱,角色,BG,是否启用`），把 `是否启用` 改成 `Y/N` 后整表上传预览→执行，即可批量停用 / 启用账号；**未变化的行跳过、操作者本人一律跳过**，避免把自己锁在门外。

## 查看（角色化）

- **员工（我的奖金）**：按年度查看，Q1–Q4 四季度横向排布；未计算的季度留空但显示目标。每个计划展示各 KPI 的目标/达成率/支付率，以及 **YTD加权支付率**；**仅当年有过特殊调整时**才追加「特殊调整」与「YTD加权支付率（经特殊调整后）」两行（不再展示未加权支付率，也不再在本页展示信息变更历史）。页头部门 / 职称按**计算时点快照**呈现（旧季度显示旧部门）。年度下拉仅可选当前与上一年度。「汇报给」统一标注为「直线经理：」。
- **经理（团队）**：可见向下最多 5 层的整个团队，每人标注相对层级（直属为 N-1，其下属为 N-2，依此类推）；支持按层级筛选（如只看 N-3）、按工号/总支付率排序，并显示团队平均总支付率。
- **BG 管理员（BG 视图）**：所辖 BG 集合（可多个）全员当期结果（含部门/职称）与平均总支付率，页面标题列出全部所辖 BG，可下载本范围的**两张表**（总支付率 + 各 KPI 明细）。

## 通知信（BG 管理员 / 平台管理员）

- 收件人以列表选择：支持**筛选**（按姓名/工号检索）、**全选**、**Shift+点击区间多选**，并实时显示已选人数。BG 管理员只能选所辖 BG 集合内的员工；平台管理员可对任意在职员工**群发**。
- 占位符覆盖数据表全部字段：`{{NAME}} {{EMPLOYEE_ID}} {{EMAIL}} {{BG}} {{DEPARTMENT}} {{JOB_TITLE}} {{MANAGER}} {{PERIOD}} {{PLAN_NAME}} {{MESSAGE}} {{PLAN_TABLE}} {{PERFORMANCE_TABLE}} {{CURVE_SUMMARY}}`。其中 **`{{PLAN_TABLE}}`（计划结构：KPI / 权重 / 目标 / Curve，不含实绩）** 与 **`{{PERFORMANCE_TABLE}}`（绩效明细：目标 / 实绩 / 达成率 / Curve / 原始支付率 / 加权贡献 + YTD加权支付率与经特殊调整后汇总）** 是两张独立表格，可分别放入正文。
- **正文与标题都直接取库里已有的计算结果（#1）**：无需为发信重复导入业绩数据；某季度若尚无实绩，对应达成率 / 支付率一律留空。标题里的 `{{PERIOD}}` 现已正确展开为实际期间（#15）。
- **模板全员共享、他人只读可复制（F4）**：通知信模板在平台 ADMIN 与所有 BG 管理员之间**完全共享可见**（含 `bg=Global` 模板）。列表显示「创建者」及「我的 / 只读」标记。**他人创建的模板只读**，可「复制并编辑」派生一份归属自己的副本（名称加「（副本）」后缀、落到创建者的主属 BG）后自由改写；**创建者可删除自己的模板，平台 ADMIN 可删除任意模板**。
- **Curve 在信中以表格呈现**：每条 Curve 按区间列出「达成率范围 → 支付率范围」及**区间斜率**，并注明封顶与否；帮助员工理解「完成多少、支付多少」。
- 信件以 HTML 发出，正文附已阅链接；平台记录发出时间、已阅时间、所用模板。
- **发信记录可导出（#16）**：通知信记录页可把**权限范围内全部或指定季度**的发信明细（收件人工号 / 姓名 / BG / 期间 / 模板 / 主题 / 发送方式 / 发出与已阅时间）导出为本地化表头的 CSV。
- **一键邮件连通性自检（#17）**：撰写页提供「测试邮件配置」动作，依次探测 SMTP 与 POP3 连通性并回显结果；未配置或本地演示时明确提示降级为 outbox。
- **仅收件人本人（或邮件链接的匿名访问者）可确认已阅**；管理员打开信件只能预览、不能代为确认。页面仅一个「确认已阅」按钮。

## 邮件配置

默认无 SMTP 时降级为本地发件箱（`data/outbox/*.html`），便于演示。配置真实发信：

```bash
set SMTP_HOST=smtp.example.com& SMTP_PORT=587& SMTP_USER=...& SMTP_PASSWORD=...& SMTP_FROM=bonus@example.com& BASE_URL=https://your-host
```

（Linux/macOS 用 `export`。）`BASE_URL` 用于生成已阅链接。支持 SMTPS（隐式 TLS）/ STARTTLS 与 POP3 收件；真实凭据放在被 `.gitignore` 排除的 `.env` 里，绝不入库。本地跑测试或演示时可设 `SMTP_DISABLED=1` 强制降级为 outbox（不触网），保证 `seed.py` / 端到端测试的确定性。

## 运维：备份 / 还原 / 空白起步

三个命令行脚本，无需进界面即可完成整库快照与回滚（均使用 SQLite 在线备份 API，服务器运行时也能取到一致快照）：

```bash
.venv/Scripts/python backup.py                      # 生成一次快照到 backups/<时间戳>/
.venv/Scripts/python backup.py before-q3-import     # 带人工标签，便于日后按名还原
.venv/Scripts/python restore.py latest              # 一键还原到最近一次快照
.venv/Scripts/python restore.py before-q3-import    # 按标签还原（也可用时间戳目录名）
.venv/Scripts/python restore.py latest --yes        # 跳过交互确认
.venv/Scripts/python reset_empty.py                 # 清空成全空库，仅留一个平台管理员
```

- **backup.py**：把 `app.db` 的一致副本、会话签名密钥 `secret.key`、本地发件箱一并写入带时间戳的快照目录，并生成 `manifest.json`（记录时间、标签、Git 版本、完整性校验、各表行数）。滚动保留最近 N 份（默认 20，`--keep` 或 `BACKUP_KEEP` 覆盖），超出部分移动到回收站而非硬删。
- **restore.py**：还原前先校验快照完整性，并**自动对当前状态做一次“还原前”快照**（误还原也可再回退）；若检测到代码版本与快照不一致（本项目无迁移机制）会警告并要求确认；Windows 上服务器会锁定 SQLite 文件，脚本会检测到并提示先停服务，绝不半途覆盖。
- **reset_empty.py**：删除并重建空表，仅插入一个平台管理员（默认 `ADMIN1/admin123`，可用环境变量 `ADMIN_ID/ADMIN_NAME/ADMIN_EMAIL/ADMIN_PW` 覆盖），供从零手动录入验证。

## 计算规则

- 达成率 = YTD 实绩 ÷ Quota × 100%；支付率 = Curve 分段线性插值（受封顶约束）；**季度尚无实绩的 KPI 一律留空、不按 0 计，也不计入加权**（待导入实绩后重算自动补齐）。
- **YTD加权支付率** = Σ(权重% × 支付率) ÷ 100，**按原状加权加总、不归一化**。当某计划权重合计不是 100% 时，支付率随之等比缩放——这有时是正常/有意的，系统不改数值。
- **系统不提供未加权（简单平均）支付率**。计算时记录权重合计（`weight_total_pct`）；导出表一在权重合计≠100% 时于 `comment` 列标注「本次计算权重不是100%」。
- **YTD加权支付率（经特殊调整后）**（最终）= YTD加权支付率 + 特殊调整（±百分点，增量而非覆盖）；这一行只在当年确有调整时才出现。
- 内部支付率保留四位小数，展示与导出均以常规十进制呈现（避免科学计数法）。

## 测试与目录

离线引擎单测可直接运行；端到端测试需要一个**已启动的服务器**（会写入演示数据，测完请重新 `seed.py`）。全程带 `SMTP_DISABLED=1` 让邮件固定在本地 outbox、绝不触网，结果可复现。Windows（git bash）顺序：

```bash
SMTP_DISABLED=1 .venv/Scripts/python tests/test_calc.py   # 引擎单测（离线：端到端计算、部分权重加总、区间斜率、Curve 整数、实绩缺失留空）

taskkill //F //IM python.exe                              # 释放 SQLite 占用（git bash 用双斜杠）
SMTP_DISABLED=1 .venv/Scripts/python seed.py             # 重建演示库
( SMTP_DISABLED=1 .venv/Scripts/python run.py > server.log 2>&1 & )  # 后台启动 http://127.0.0.1:8000（子 shell 内 & ，避免把 cd 一起后台化）
SMTP_DISABLED=1 .venv/Scripts/python tests/test_e2e.py   # 端到端 34 步（需活服务器）
SMTP_DISABLED=1 .venv/Scripts/python seed.py             # 测完重新 seed，清掉测试污染的数据
```

端到端 34 步覆盖：主表格导入 / 通知信数据导入（含年度格式、YTD 列展开、**F1 权重≠100% 整员工拒绝**、与季度计算冲突拦截与冲突清单导出）/ Curve / **一键计算** / **F2 封存后再算仍显示已计算** / 单人与批量调整 / 数据删除 / 封存 / **四张表导出与筛选（结果 + 各 KPI 明细 + #12 计划清单 + #13 KPI 清单）** / **F6 指定季度预填大表导出** / **F5 计划名跨 BG 跨季度全局唯一化（改名与自动加后缀，#11）** / **Curve 整数强制（#6）与停用后导入被拒（#7）** / **员工界面 YTD 术语、调整行按需显现、隐藏变更历史（#8 / #14）** / **计算时点快照随部门变更（#4）** / **本地化表头（#2）** / **用户花名册导出 + 批量启停（#5）** / **通知信记录导出（#16）与邮件连通性自检（#17）** / BG 多对多与共管 / 代操作（proxy）/ **F4 模板全员共享 · 他人只读 · 复制 · 各自删除 / 平台 ADMIN 任意删除** 与计划-绩效两张表占位符 / 语言管理 / 中英切换 / 多层团队 / 四季度 / 批量导入用户 / 员工信息版本化封存 / 所辖 BG 重新同步 / 已阅追踪。

```
app/            应用代码（db/models/curves/calc/csvio/i18n/mailer/security/deps/routers/templates）
data/           SQLite 数据库、密钥、本地发件箱（运行生成，已在 .gitignore 排除）
backups/        backup.py 生成的整库快照（已在 .gitignore 排除）
sample_data/    示例 CSV：quarter_import.csv（季度大表）/ letter_data.csv（通知信·年度格式）/ users_import.csv（批量导入用户）
tests/          test_calc.py（离线引擎单测）+ test_e2e.py（端到端 34 步，需活服务器）
seed.py         演示数据种子脚本（重建库，含演示翻译词条）
run.py          开发服务器入口
backup.py       整库快照（DB + 密钥 + 发件箱 + manifest），滚动保留
restore.py      一键还原到任一快照（还原前自动再快照一次）
reset_empty.py  清空为空白库、仅留一个平台管理员
```

## 设计取舍与后续迭代方向（MVP 边界）

- SQLite + 单进程，适合小团队验证；生产建议 PostgreSQL + 部署网关（HTTPS、CSRF 加固、邮件服务化）、以及 Alembic 数据库迁移。
- 数据库以 `create_all` 建表、**无迁移机制**：改动模型后需重新 `seed.py` 重建库；生产化时应引入 Alembic 管理版本迁移。
- 期间假设为 `YYYY-Qn` 季度格式；封存不可撤销（符合审计最佳实践）。
- 版本化通过 `version + is_current + is_deleted + imported_at` 字段实现（计划与实绩两表各自版本化）；如需完整历史回放，可在此基础上扩展审计视图。
- 每人每 KPI 的计算明细以 `detail_json` 快照留存于批次结果中，导出表二（各 KPI 明细）即由此展开；导出分「总支付率」与「各 KPI 明细」两张表，共用年份 / BG 筛选。
- 后续可迭代：计划审批流、多币种、已读提醒、更细的数据权限、金额结算模块。

---

## The Story Behind This Project / 这个项目背后的故事

<details>
<summary>🇺🇸 English</summary>

About ten years ago, I was sent as the China HR representative to a global sales incentive system implementation project. (Yes, I only taught myself some basic Python and SQL — without AI Agent tools, I could never have built this project.)

I initially accepted this challenge with great enthusiasm. But as I learned more about the situation and witnessed the disruption to the business, my mindset gradually shifted — from excitement, to concern, to confusion, and in recent years, to sustained anger. Of course, to survive in a corporation, we all learn to hide our true feelings. I tried to make this project valuable. I tried to bury this project. I failed.

After attempt after attempt, my anger only grew. I went from "maybe I don't understand," to "the people above don't understand," to today — where I suspect that some of them may have taken kickbacks from the SaaS vendor. Of course I have no evidence. Maybe the decision-makers really are just that incompetent. I simply cannot understand: a system that received extensive global negative feedback, a system proven to deliver no business value — in a company that prides itself on cost control — why has it kept taking our money for ten years?

You might ask how I can prove it has no business value. Let me put it this way: countries that use this system and those that don't show no difference in sales completion rates. Salespeople who log into the system and those who don't show no performance difference. Salespeople using the system and those not using it show no difference in their understanding of or satisfaction with sales incentives. And finally, the most damning point — because the system we chose is so poorly designed, the more completely you use it, the more back-office support staff you need.

This is probably politics. Some people cannot bring themselves to reverse their own decisions. Some enjoy watching their teams expand, even without business value. Some like having an excuse to reach into the business — when things go well, they take credit; when they don't, they point fingers. Some like to be in a controlling role; surveillance through data is the foundation of control. But market competition is fierce, and companies cannot afford this kind of disruption. Why do I care? This company gave me my livelihood, and most people here are genuinely good.

Finally, some thoughts on sales incentive management. I hope that anyone passing by — whether you're in IT, Finance, Sales Ops, General Management, or Sales — can take away something that helps you avoid falling into the same traps I did.

- **Nobody actually needs a "sales incentive system" to manage sales incentives.** Most calculation, analysis, and display functions can be achieved with Tableau or Power BI. For notification letter acknowledgments, there are plenty of solutions — mail merge, Power Automate, or a simple HTML web form. This is also why I was initially surprised that there were no open-source solutions for sales incentive systems, but later I realized — the demand itself probably never existed in the first place.
- **The above is technical. From a management perspective**, sales managers don't need an incentive system to understand the business. For performance, just look at Salesforce or the order system. It's normal for sales teams to review performance biweekly; sales managers stay on top of their reps' work through weekly meetings — this is far more timely and insightful than anything inside a sales incentive system. Salespeople's energy should be directed at customers and making more money; staring at a "report card" 20 times won't improve results. Even more damaging: because sales commission calculations are inherently complex, heavy employee focus on calculation logic only generates more questions about bonus details, increasing back-office support burden. Most of the time, 99% of these issues are just misunderstandings. In reality, salespeople just need to know that the more they do, the more they earn. Only underperforming or average salespeople have the time and energy to argue with Payroll over numbers. Good salespeople spend their time with clients.
- **Automated sales credit attribution is only possible when the sales model is simple.** Many decisions are inherently impossible to automate because they depend on judgment of complex situations. When a major deal involves five salespeople — regional, central, channel, industry, solutions — you can't simply divide by five, nor can you double-count everything.
- **Sales incentive design must align company and employee interests.** This sounds obvious, but when too many decision-makers get involved — like Finance — it easily goes off track. When interests are aligned, incentives are an investment. Every dollar spent on bonuses brings in hundreds or thousands of times that in sales revenue. Finance's real control point should be whether the total payout ratio roughly matches the achievement rate — as long as they match, it's money well spent.

Finally, I certainly have my biases. If you've read this far, I'm deeply grateful. At the same time, I welcome your advice, alternative perspectives, or corrections to where I might be wrong.

</details>

<details>
<summary>🇨🇳 中文</summary>

我是在大概十年前，作为中国区的HR代表被派到全球销售激励系统上线的项目上。
（对，我只有自学过基本的python和sql语句，没有AI Agent我是做不了这个项目的）
我一开始很热情的接受了这个挑战，但随着我对事情的了解，及看到对业务的干扰，我的心态逐渐从兴奋，到担心，到困惑，到最近几年持续的愤怒。当然在公司里生存，我们都得学着隐藏真实的感受。我试图让这个项目有价值，我试图埋葬这个项目，我没有成功。
在一次又一次的试图中，我越来越愤怒。我从也许我不懂，到上面的人不懂，到今天我怀疑也许他们里面有些人拿了SaaS公司的钱。
当然我没有证据，也许做决定的人真的那么蠢。我只是不能理解，一个收到大量全球性负面反馈的系统，一个被证实没有业务价值的系统，在一个重视成本控制的公司，为何能连续收了我们十年的钱。

你也许会问，我怎么证明这事没有业务价值。我这么说吧，用这个系统的国家和不用这个系统的国家，在业务完成率上没有区别。进到这个系统里看信息的销售，和不进这个系统的销售没有业绩差异。用这个系统的销售，和不用这个系统的销售，对销售激励的理解及满意度没有差异。最后，最致命的，由于我们选择的系统是如此的差，这个系统用的越完整，越需要大量的后台人员支持。

这也许是政治。有些人无法推翻自己的决定。有些人乐见自己的团队扩张，即便没有业务价值。有些人喜欢找个理由伸一只手到业务里，业务好了，他贪功，业务不好，他指责。有些人喜欢站在控制的角色，窥视数据是控制的基础。但市场竞争是激烈的，公司经不起折腾。我为啥在意，这公司确实给了我人生，这个公司多数的人是可爱的。

最后，销售激励管理的一些心得体会。希望路过的你，不论是IT、还是财务、还是Sales Ops、还是总经理、还是销售总监，都有些启发能让你不要掉进我的坑。
- 没人真的需要一个"销售激励系统"来管理销售激励。绝大部分的计算、分析、展示功能，可以使用Tableau或PowerBI实现。通知信签收功能，方案也很多，包含mail merge，power automate及弄个简单的HTML网页表单。这也是为啥，我一开始很讶异销售激励系统居然没有开源方案，后来就理解也许其实这个需求本身根本不存在。
- 上面是技术上的。从管理上来看，销售经理不需要激励系统来了解业务情况。业绩情况，直接看salesforce或订单系统就可以了。一般销售团队双周会看业绩是正常的，销售经理是通过周会来掌握下属工作状态，这远远比销售奖金系统内的信息及时且深入。销售员工的精力应该放在客户和赚更多的钱身上，不会因为看了20次成绩单成绩就变好。更致命的是，销售奖金的计算本身有复杂性，大量员工关注计算逻辑，只是导致了更多奖金计算细节的问题，加重后台支持负担，很多时候这些问题99%都是销售误会了。其实销售只需要知道，他做的多，拿的多就是了。只有销售业绩差或一般的人才有时间精力去和payroll掰扯数字。好的销售时间精力都在客户身上。
- 销售奖金业绩归属自动化，只有在销售模式简单的情况下才是可能的。很多决定本质上是不能自动化，因为依赖对复杂情况的判断。一个大项目5个销售在上面，有地区的，有中央的，有渠道的，有行业的，有方案部门的，业绩怎么算并不可能直接除五，也不可能都双记。
- 销售激励的设计，一定要设计成公司和员工利益一致。听起来像废话，但往往当决策人变多如财务，就容易走偏。利益一致时，激励是投资。每一分奖金花出去，背后都是百倍千倍的销售额进来。财务真正的控制点在于，激励总支付率和业绩完成率能否大致匹配，只要匹配就是值得。

最后，我肯定是有我的偏见，如果你都看到这里了，我很感谢，同时也希望你能给我建议，提出不同观点或指出我的可能错误。

</details>

## ☕ Support This Project

If this project helps you or you like my story “very much”, consider supporting its development and, mm... me:D.  
如果这个项目对你有“很大”帮助或者你“很喜欢”我的故事，欢迎支持它的持续维护还有...我:D。

- 🌍 PayPal: https://paypal.me/buckwheat123123
- 🐙 GitHub Sponsors: (coming soon)

> ⚠️ This is a voluntary donation, not a commercial transaction.  
> 此为自愿赞助，不属于商业交易行为。
