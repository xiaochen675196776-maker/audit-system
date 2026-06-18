# 会话 C · 前端页面

## 前置依赖（会话 A 已完成）

### 后端 API 已就绪
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/health` | GET | 健康检查 |
| `/api/v1/companies` | GET | 公司列表（分页 + 关键词搜索） |
| `/api/v1/companies/{id}` | GET | 公司详情 |
| `/api/v1/companies` | POST | 创建公司 `{name, code, tax_id?, address?, industry?}` |
| `/api/v1/companies/{id}` | PUT | 更新公司 |
| `/api/v1/companies/{id}` | DELETE | 删除公司 |

### 前端已有文件
```
frontend/src/
├── main.ts              # Element Plus + Router 已注册
├── App.vue              # 侧边栏布局（数据管理菜单）
├── router/index.ts      # 三个路由：/  /data/import  /data/companies
├── api/index.ts         # Axios 实例，baseURL=/api/v1
├── styles/global.css    # 全局样式
└── views/
    ├── HomeView.vue         # 骨架（需完善）
    ├── CompaniesView.vue    # 骨架（需完善）
    └── DataImportView.vue   # 骨架（需完善）
```

---

## 你的任务：完善前端三个页面 + 通用组件

### 启动开发环境

```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

后端 API 代理已配置在 `vite.config.ts`：`/api` → `http://localhost:8000`

---

### 1. 公司管理页 `views/CompaniesView.vue`

**功能**：
- 表格展示公司列表（名称、编码、税号、行业、状态）
- 搜索框：按名称/编码模糊搜索
- 新建按钮 → 弹出对话框（表单：名称、编码、税号、地址、行业）
- 编辑按钮 → 弹出对话框（预填数据）
- 删除按钮 → 确认后删除
- 分页

**关键 Element Plus 组件**：
- `el-table` + `el-table-column`
- `el-dialog` + `el-form` + `el-form-item`
- `el-input`, `el-button`, `el-pagination`
- `el-popconfirm`（删除确认）

### 2. 数据导入页 `views/DataImportView.vue`

整个导入分三步走：

#### 步骤 1：选择公司和上传文件
- 下拉选择公司（调用 GET /api/v1/companies 获取列表）
- 选择数据类型：科目余额表 / 序时账 / 辅助明细账
- 拖拽或点击上传 Excel/CSV 文件

#### 步骤 2：字段映射
- 显示系统自动匹配结果（绿色=已匹配，红色=未匹配）
- 未匹配的列提供下拉框让用户手动选择
- 预览前 5 行数据
- "确认映射"按钮

#### 步骤 3：导入执行
- 进度条显示
- 完成后显示结果：成功 X 条，失败 Y 条
- 失败详情表格（行号 + 错误原因）

**关键组件**：
- `el-steps`（步骤条）
- `el-upload`（文件上传）
- `el-select`（下拉选择）
- `el-table`（映射展示 + 预览）
- `el-progress`（进度条）
- `el-result`（完成结果）

### 3. 首页 `views/HomeView.vue`

- 统计卡片：被审计单位数 / 已导入凭证数 / 辅助核算条目数
- 快速入口：导入数据 / 管理单位
- 后续可扩展图表

### 4. 通用组件（可选，放到 `components/`）

- `FileUpload.vue` — 封装拖拽上传
- `FieldMapping.vue` — 字段映射表格（列名 ↔ 标准字段下拉）

---

## API 调用方式

```typescript
import api from '@/api'

// 获取公司列表
const { data } = await api.get('/companies', { params: { page: 1, page_size: 20, keyword: '搜索' } })
// data = { items: [...], total: 100 }

// 创建公司
await api.post('/companies', { name: 'xx公司', code: 'C001' })

// 删除
await api.delete(`/companies/${id}`)
```

**注意**：导入相关 API（预览/执行）由会话 B 开发，你可先用 Mock 数据开发界面，接口路径约定为：
- `POST /api/v1/imports/preview` — 预览
- `POST /api/v1/imports/execute` — 执行

---

## 页面效果参考

```
┌──────────────────────────────────────────────┐
│  📊 审计系统    │  首页 / 数据导入 / 单位管理  │
├────────────────┼──────────────────────────────┤
│ 侧边栏          │  [步骤条: ①上传 → ②映射 → ③完成] │
│ ▸ 数据管理      │                              │
│   · 数据导入    │  ┌─────────────────────┐     │
│   · 被审计单位  │  │  拖拽文件到此处      │     │
│                │  │  支持 .xlsx .csv    │     │
│                │  └─────────────────────┘     │
└────────────────┴──────────────────────────────┘
```

## 自测

```bash
cd frontend && npm run dev
# 浏览器打开 http://localhost:5173
# 检查三个页面是否正常渲染，公司管理 CRUD 是否可用
```
