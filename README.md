# 审计系统基座

审计系统基础数据平台，支持导入科目余额表、序时账、辅助明细账等基础数据。

## 技术栈

- **后端**: Python 3.12 + FastAPI + SQLAlchemy
- **前端**: Vue 3 + Element Plus + TypeScript
- **数据库**: PostgreSQL 16（开发可用 SQLite）
- **部署**: Docker Compose

## 快速开始

### Docker 部署（推荐）

```bash
docker compose up -d
```

然后浏览器打开 `http://localhost`

### 本地开发

**后端**：
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**前端**：
```bash
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`

## 项目结构

```
├── backend/           # FastAPI 后端
│   ├── app/
│   │   ├── api/       # REST API 路由
│   │   ├── models/    # ORM 数据模型
│   │   ├── services/  # 业务逻辑层
│   │   ├── schemas/   # Pydantic 请求/响应模型
│   │   └── core/      # 配置/数据库/中间件
│   └── alembic/       # 数据库迁移
├── frontend/          # Vue 3 前端
│   └── src/
│       ├── views/     # 页面组件
│       ├── components/# 通用组件
│       ├── api/       # API 请求
│       └── router/    # 路由配置
└── docker-compose.yml # Docker 编排
```
