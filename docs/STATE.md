# 审计系统基座 · 项目状态

## 技术栈
Python 3.12 + FastAPI · Vue 3 + Element Plus · PostgreSQL/SQLite · Docker Compose

## 仓库
`https://github.com/xiaochen675196776-maker/audit-system`

---

## 当前进度

| 阶段 | 状态 | 会话 | 交付 |
|------|------|------|------|
| 项目骨架 | ✅ 完成 | — | backend/FastAPI + frontend/Vue3 + Docker Compose |
| 数据模型 | ✅ 完成 | 会话 A | 五张 ORM 表 + Company CRUD API + Alembic 迁移 |
| 导入引擎 | 🔲 待开始 | [会话 B](docs/sessions/session-b-import-engine.md) | 文件解析/智能匹配/校验/批量导入 |
| 前端页面 | 🔲 待开始 | [会话 C](docs/sessions/session-c-frontend.md) | 公司管理/数据导入页/首页 |
| 串联收尾 | 🔲 待开始 | 会话 D | API 对接 + 联调 + Docker 验证 |

---

## 核心 API（已可用）

```
GET    /api/v1/health              健康检查
GET    /api/v1/companies           公司列表（分页+搜索）
GET    /api/v1/companies/{id}      公司详情
POST   /api/v1/companies           创建公司
PUT    /api/v1/companies/{id}      更新公司
DELETE /api/v1/companies/{id}      删除公司
```

## 数据库表

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `companies` | 被审计单位 | name, code(唯一), tax_id, industry, firm_id(预留) |
| `accounts` | 科目字典 | code, name, level, parent_code, direction |
| `trial_balances` | 科目余额表 | 期初/本期/期末 各借/贷 + extra_fields(JSON) |
| `journal_entries` | 序时账 | voucher_no/date, summary, account, debit/credit |
| `subsidiary_ledgers` | 辅助明细账 | 序时账字段 + auxiliary_type/code/name |

---

## 如何开始新会话

1. `git pull` 拉最新代码
2. 打开对应的任务说明书（上方表格链接）
3. 按说明书开发
4. 完成后 `git push`

## 本地运行

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端
cd frontend
npm install
npm run dev
```
