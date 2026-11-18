# TESTING.md

实际运行记录（2026-11-18，Linux / Python 3.11.2）。下表的命令均在
`/workspace/backend` 下执行，依赖按 `requirements.txt` 安装（另加
`pytest`、`httpx`、`fakeredis` 仅用于测试）。数据库使用临时 SQLite 文件、
Redis 使用 `fakeredis`，不触碰 docker 卷。

## 命令

```bash
python -m pytest tests -q
```

## 结果

```
16 passed in 3.18s
```

测试内容：

| 文件 | 覆盖点 |
|---|---|
| `tests/test_interval_bounds.py` | 与穷举线性扩展逐例对照的精确上下界（含孔隙率并列）；两端取值严格位于开区间、彼此互异、回算 ρ 一致；窄区间触发精确十进制回退时仍逐位校验；双精度取值可按 round-trip 文本精确复现；2000 试件、任一点 8 段重叠的时限与容量；超容量批次快速拒绝；常量孔隙率与非有限/倒置端点的拒绝 |
| `tests/test_interval_api.py` | 登录与权限；区间研究创建→worker→结果展示；超容量在写运行记录与入队前 422 拒绝（队列长度不变）；发起后并发修订观测不影响冻结快照及结果；缺上界的结果被隐藏为 failed 且导出 409；观察员不能发起；倒置区间录入被拒 |

## 性能实测（2000 试件，单核）

| 场景 | 最大重叠 | `interval_bounds.calculate` 用时 |
|---|---|---|
| 8 组交错滑窗（最坏容量） | 8 | 0.65 – 0.83 s |
| 完全嵌套（应拒绝） | 2000 | 0.002 s 内抛错，无运行记录入队 |
| 互不重叠 | 1 | 0.06 s |

峰值内存约 34 MB；完整结果 JSON 约 650 KB（2000 试件、两端各一组取值）。
运行时限由 `domain.json` 的 `interval.deadline_seconds`（30 秒）在 worker 中强制。

另以独立随机可行顺序抽样核对：把可行顺序对应的 ρ 与返回上下界比较，
样本全部落在 `[下界, 上界]` 内。

## 未验证项

- 本机无 Docker 守护进程，`docker compose up -d --build` 与 MySQL 8 链路未实际启动；
  API 测试使用 SQLite + fakeredis 替代。真实 MySQL 下的 JSON 列读写、
  Nginx 代理与浏览器端交互未自动化覆盖。
- 前端未做自动化测试（无 Node 构建链路）；仅做代码级检查。
