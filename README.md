# 澄石材料共变研究册

独立材料试件孔隙率/吸水率→秩相关研究→后续试验假设；相关不解释为因果。原生 HTML/CSS/JavaScript 多模块工作席，所有计算由 Python 完成。

## 模拟业务
澄石研究协作组，12名分析师与业务人员，日常使用 `stone-spearman-202611-1.csv` 手工抄表。当前三个痛点：观测与口径不可追溯、重算易出错、结果与复核割裂。上游提供独立合成业务观测；本应用接管数据登记、方法执行和输入冻结；下游负责人形成复测/预算方案，观察员获取复核后的CSV。

核心业务实体：MaterialBatch / Specimen / CorrelationRun / ResearchNote。源码 model/schema/service/controller/route 与前端 api/store/pages 完成链路，不依赖浏览器本地假数据。

## 功能与方法
- 材料批次、独立试件录入/编辑/删除；重名记录与非法数值明确拒绝。吸水率按开区间 `low`/`high` 录入（端点不含），孔隙率保留实测数值。
- 分析页发起 `interval` 开区间研究：吸水率只给开区间、要求各试件取值互异，求 ρ 的精确上下界。API 仍保留 `exact` 精确值模式（并列平均秩Spearman与固定seed置换p）供脚本调用。相关关系只支持后续假设，不解释为因果。
- 开区间上下界通过对区间序的线性扩展做端点扫描求得：状态只保留当前重叠的前沿，任一点重叠不超过8段时每段至多 2^8 个状态，因此两千试件可在秒级得到精确界（不是抽样近似）。
- 每个界都附一组严格位于各自开区间内、彼此互异的取值；结果页给出这两组取值并独立回算 ρ，回算与界一致才展示。两端取值齐全前结果页只显示等待状态。
- 每次运行在发起时冻结参数、区间和孔隙率并生成SHA256；之后并发修订观测不会影响该次计算。Redis任务由独立worker计算，写DB与共享产物卷。
- 发起区间研究前先做容量预检：任一点重叠超过容量的批次在写入运行记录和入队之前即以422拒绝，不占用队列。worker对区间结果再做完整性复核，并要求在30秒时限内完成。
- 负责人复核不可覆盖；审计记录登录、数据改动、排队、复核与导出；240请求/分钟限流、全局可恢复错误。

## 快速启动
```bash
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```
访问 http://localhost:18243 ，API http://localhost:19243/docs 。数据库映射 17743。无需Node构建。可以从中文和带空格目录启动。清理 `docker compose down -v --remove-orphans` 会删除本题演示数据卷。

|角色|账号|密码|权限与典型动作|
|---|---|---|---|
|admin 负责人|admin@demo.local|Research2026!|全部读写、批准复核、下载|
|analyst 分析师|analyst@demo.local|Research2026!|数据修改、创建任务、读取结果及下载；不能复核|
|viewer 观察员|viewer@demo.local|Research2026!|只读；仅可导出已复核结果|

## 一天的工作剧本
1. 09:00 admin登录，查“澄石·细砂岩批次”。
2. 09:10 analyst核对 `stone-spearman-202611-1.csv` 的seed记录。
3. 09:15 来源录入页检查 `孔隙率 (%)` 等业务字段，必要时编辑。
4. 09:20 分析执行页选择“开区间研究”，保留重叠容量 `8`，命名本轮研究。
5. 09:21 冻结输入并排队；超出重叠容量的批次当场被拒绝，其余由 worker 实算，结果页自动刷新。
6. 09:25 阅读 ρ 精确上下界、两端回算取值、逐试件明细与SHA256；发现失败先修数据重跑。
7. 09:35 admin打开业务复核，写明限制与下一步动作，归档后不可覆盖。
8. 09:40 viewer读取复核意见并下载CSV，在操作留痕页核对下载事件。

## 技术与目录
|部分|实现|
|---|---|
|前端|原生ES modules、HTML/CSS、Nginx1.27，无前端框架|
|API|Python3.11、FastAPI0.115、SQLAlchemy2、JWT、PBKDF2密码|
|计算|NumPy2.2、SciPy1.15，固定seed42；开区间精确包络为纯Python实现|
|数据库|MySQL8|
|任务|Redis7持久队列，Python独立worker，心跳healthcheck|

`frontend/src/`分api、stores、types、components/common、hooks、pages、router、utils、constants；`backend/src/`分config、models、schemas、services、controllers、routes、middlewares、utils、constants；`backend/scripts/seed_demo.py`自然键插入、重复不覆盖修改；`backend/migrations/README.md`说明schema版本。

环境变量 `.env.example`：COMPOSE_PROJECT_NAME、FRONTEND_PORT、BACKEND_PORT、DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO。开发时在本地venv安装backend/requirements.txt，设置DATABASE_URL、REDIS_URL、JWT_SECRET再运行uvicorn；前端开发经Nginx代理 `/api/` 到不带前缀的API。

共享枚举：角色admin/analyst/viewer和队列queued/running/completed/failed；后端`src/constants/enums.py`、认证与worker使用相同值；前端`src/types/enums.js`、状态与角色界面使用相同值。研究模式与区间容量来自 `backend/src/constants/domain.json`（`modes`、`interval.overlap_capacity`、`interval.deadline_seconds`），前端 `src/constants/domain.js` 同步生成。Google Fonts：Noto Serif SC + IBM Plex Mono；断网使用serif/monospace回退。

## 算法输入、失败态与复现
输入为选定批次全部观测和参数，输出核心数值、明细、解释；参数经后端严格白名单和范围验证，两种模式各收各的参数（`interval` 只接受 `overlap_capacity`）。并列值使用平均秩；置换检验假定独立且可交换的试件。相关关系只支持后续假设，不解释为因果。空批次拒绝；不完整字段/非有限数/非法计数拒绝；常量相关列与不足样本使任务failed并保留错误。固定seed42、输入checksum相同可复现。独立oracle：对scipy spearmanr相关系数；单调/反向/并列/常量边界。

开区间研究的正确性由穷举校验：`tests/test_interval_bounds.py` 对数百个小规模实例枚举全部可行线性扩展，逐例核对上下界；两端取值以精确有理数构造，十进制输出在 24 位以上有效数字，并再次用十进制取值独立求秩回算 ρ。实测 2000 试件、任一点 8 段重叠时约 0.7 秒完成，峰值内存约 34 MB；超过容量的批次在入队前拒绝（实测 0.002 秒内）。

已知边界：小型本地研究应用，使用合成数据，不含企业SSO与外发邮件；结果由人工复核，不自动执行业务决策；单worker恢复queued/running任务，数据库与Redis间未采用分布式事务。以当前测试目录TESTING.md记录实际验证结果。

MIT License。
