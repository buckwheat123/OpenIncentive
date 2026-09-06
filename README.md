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

- **计划以 `plan_name` 为身份**：同一「期间 + 员工 + 计划名」的多个 KPI 行构成一个计划。
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
sample_data/    示例 CSV（v3 新格式：含 department/job_title）
seed.py         演示数据种子脚本（重建库，含演示翻译词条）
run.py          开发服务器入口
```

## 设计取舍与后续迭代方向（MVP 边界）

- SQLite + 单进程，适合小团队验证；生产建议 PostgreSQL + 部署网关（HTTPS、CSRF 加固、邮件服务化）、以及 Alembic 数据库迁移。
- 期间假设为 `YYYY-Qn` 季度格式；封存不可撤销（符合审计最佳实践）。
- 版本化通过 `version + is_current + is_deleted` 字段实现；如需完整历史回放，可在此基础上扩展审计视图。
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
