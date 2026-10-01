# StallSpan 市集摊档开间

沿街段一维 First-Fit 开间分配，挡柱不可被摊位跨越，输出分配图与放不下清单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4700 |
| API | http://localhost:9700 |
| API 文档 | http://localhost:9700/docs |
| Postgres | localhost:5448 |

健康检查：`GET http://localhost:9700/api/health`

## 使用说明

1. 在「集日」「街段」确认开市日与可用宽度。
2. 在「摊主」「挡柱」维护需求宽度与障碍位置。
3. 打开「分配图」执行一维开间分配。
4. 在「放不下」查看无法安置的摊位。

## 保留已落摊

- 「分配图」勾选「保留已落摊」再分配：上一次成功运行的已落摊起止锁定（图中斜纹 🔒 色块），本轮只对其余摊从左填，新摊不得侵入锁区。
- 低优先摊顶不掉已锁摊：该摊进入「放不下」并标记「锁区冲突」（与「空档不够」区分）。
- 尚无成功运行时勾选保留会被拒绝（409），图与放不下保持不变。
- 不勾选则为整段重算。「运行记录」抽屉可回看历次运行（保留/重算、落/锁/拒数量），点开历史运行不影响当前结果。

## 开发与测试

```bash
docker compose exec api pytest -q
```
