# 审计系统基座 · 项目状态

## 技术栈
Python 3.12 + FastAPI · Vue 3 + Element Plus · PostgreSQL/SQLite · Docker Compose

## 仓库
`https://github.com/xiaochen675196776-maker/audit-system`

---

## 当前进度

| 阶段 | 状态 | 交付 |
|------|------|------|
| 项目骨架 | ✅ 完成 | FastAPI + Vue3 + Docker Compose |
| 数据模型 | ✅ 完成 | 5 张 ORM 表 + Company CRUD + Alembic 迁移 |
| 导入引擎 | ✅ 完成 | 文件解析 / 智能匹配(83关键词) / 借贷校验 / 批量导入 |
| 前端页面 | ✅ 完成 | 公司管理页 / 三步导入向导 / 首页仪表盘 |
| 串联收尾 | 🔄 进行中 | 前后端联调 + Docker 验证 |

---

## 核心 API

```
GET    /api/v1/health              健康检查
GET    /api/v1/companies           公司列表（分页+搜索）
GET    /api/v1/companies/{id}      公司详情
POST   /api/v1/companies           创建公司
PUT    /api/v1/companies/{id}      更新公司
DELETE /api/v1/companies/{id}      删除公司
POST   /api/v1/imports/preview     预览导入（上传文件→返回匹配结果）
POST   /api/v1/imports/execute     执行导入（上传文件→校验→入库）
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

## 本地运行

```bash
# 后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端（另一个终端）
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

## Docker 部署

```bash
docker compose up -d
# 打开 http://localhost
```
