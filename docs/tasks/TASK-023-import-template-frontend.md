# TASK-023：导入模板管理页面

状态：OPEN
执行者：
开始时间：
完成时间：

## 目标

新增独立“导入模板”页面，让用户可以管理全局导入模板：列表、筛选、启停、删除、上传样本生成草稿、编辑映射、测试模板。

## 前置依赖

- 必须等待 `TASK-021` 后端 API 初稿完成并验收。
- 开始前阅读 `docs/COMMAND_CENTER.md` 和本任务。
- 开始前运行 `git status --short`。

## 允许修改范围

可以修改：

- `frontend/src/router/`
- `frontend/src/App.vue`
- `frontend/src/types/`
- `frontend/src/api/`
- `frontend/src/views/ImportTemplatesView.vue`
- `frontend/src/styles/`

不要修改：

- `frontend/src/views/DataImportView.vue`
- 后端
- `docs/UI_OPTIMIZATION_PLAN.md`

## 必须完成

1. 新增路由 `/data/templates`。
2. 数据模块导航新增“导入模板”。
3. 新增 `ImportTemplatesView.vue`，页面中文文案，不出现用户可见英文。
4. 页面支持：
   - 模板列表
   - 按数据类型筛选
   - 启用/停用
   - 删除确认
   - 上传样本生成模板草稿
   - 编辑模板名称、数据类型、来源标识
   - 编辑字段映射
   - 编辑默认年度/期间
   - 上传文件测试模板
5. 页面应保持现有企业级 SaaS 风格：
   - 信息密度适中
   - 不做营销页
   - 不做大面积渐变/插画
   - 移动端不阻断核心操作
6. API 错误统一使用现有 `normalizeError()`。

## 接口约定

以后端 `TASK-021` 实际 API 为准。若字段名和本任务不一致，优先适配后端已验收契约，并在完成回报里说明。

## 验收命令

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
```

## 浏览器验收

启动前后端后打开：

```text
http://127.0.0.1:5173/data/templates
```

至少检查：

1. 空状态。
2. 上传样本生成草稿。
3. 保存模板。
4. 启停模板。
5. 测试模板。
6. 窄屏不出现关键操作被裁切。

## 完成回报

按 `docs/tasks/DONE_TEMPLATE.md` 追加到本文件底部。
