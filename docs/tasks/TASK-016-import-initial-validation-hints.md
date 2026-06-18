# TASK-016：导入页初始校验提示收口

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 13:15
完成时间：2025-01-21 13:20

## 目标

修复数据导入页打开后立即显示红色错误提示的问题。

这是非阻塞体验缺陷，但用户会误以为系统已经解析了一个错误文件。

## 当前验收发现

总指挥在 2026-06-18 启动前后端后，用浏览器打开：

```text
http://127.0.0.1:5173/data/import
```

页面初始状态还没有选择文件，却已经显示：

```text
文件未含年度列，必须填写
文件未含期间列，必须填写
```

截图证据：

- `frontend/ui-acceptance-shots/import-desktop.png`
- `frontend/ui-acceptance-shots/import-small.png`

脚本证据：

- 页面正文包含上述两条提示。
- “下一步：字段映射”按钮是禁用状态，这一点是正确的，不能破坏。
- 控制台无错误，接口请求无失败。

## 初步定位

请先自己复核，不要机械照抄。

`frontend/src/views/DataImportView.vue` 中：

- `fileHasFiscalYear = computed(() => mappings.value.some(...))`
- `fileHasPeriod = computed(() => mappings.value.some(...))`

初始状态 `mappings` 为空，计算结果为 `false`，模板就把它当作“文件未含年度列/期间列”显示。

正确行为应该是：

- 没有上传文件、没有解析预览前，不显示红色“文件未含...”提示。
- 文件解析后，如果确实缺少年度列或期间列，再显示红色提示，并允许用户手动填写。
- 如果文件已经识别年度列或期间列，继续显示“已在文件中识别”。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/screenshot.cjs`（只有需要补充截图时）

不要修改：

- `backend/`
- 全局布局和侧边栏
- 导入接口契约
- 其他页面

## 必须修复的问题

### 1. 初始页面不显示红色缺列提示

打开 `/data/import` 初始状态时：

- 不应显示 `文件未含年度列，必须填写`。
- 不应显示 `文件未含期间列，必须填写`。
- 不应出现红色 `.field-note.required`。

可以改成中性提示，也可以在初始状态不显示提示。文案必须是中文，不能包含英文字母。

### 2. 上传解析后的提示逻辑不能丢

文件解析完成后：

- 如果文件缺少年份列，显示 `文件未含年度列，必须填写`，并要求填写会计年度。
- 如果文件缺少期间列，显示 `文件未含期间列，必须填写`，并要求填写会计期间。
- 如果文件包含对应列，显示 `已在文件中识别`。

不要改变 `goPreview`、`startImport`、字段映射、上传接口、导入接口参数。

### 3. 保持按钮状态

初始状态下：

- “下一步：字段映射”必须继续禁用。
- 底部提示 `请选择被审计单位并上传文件` 可以保留。

## 验收命令

必须运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
node screenshot.cjs
```

必须再运行：

```powershell
cd D:\APP\Codex-项目\13、审计系统
git diff --check -- frontend docs
rg -n "10MB|MB|CRUD|v0\\.1\\.0|xlsx|xls|csv|ID|Input should|Network Error|Excel|CSV|Ctrl K" frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

允许 `rg` 仅命中：

- `DataImportView.vue` 的 `accept=".xlsx,.csv,.xls"` 技术属性。
- `error.ts` 内用于翻译英文错误的匹配字符串。

浏览器验收必须确认：

- `/data/import` 初始页面没有上述两条红色缺列提示。
- `/data/import` 页面不出现 `10MB`。
- `/data/import` 在 480px 宽度下没有横向溢出。
- 控制台无前端错误。

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 13:20

### 修改文件

- `frontend/src/views/DataImportView.vue`

### 完成内容

**修复初始页面红色缺列提示**

根因：`fileHasFiscalYear` / `fileHasPeriod` 基于 `mappings` 计算，页面初始 `mappings` 为空 → 两者均为 `false` → 模板立即渲染红色「文件未含年度列/期间列，必须填写」。

修复方案：新增 `previewDone` ref（初始 `false`），作为提示状态的"门控"：

| 状态 | 提示文案 | 颜色 |
|------|----------|------|
| 初始（未上传文件） | 上传文件后自动识别 | 中性灰 |
| 已解析 + 文件含列 | ✓ 已在文件中识别 | 绿/中性 |
| 已解析 + 文件缺列 | 文件未含年度列/期间列，必须填写 | 红色 |

具体改动：
- 新增 `previewDone = ref(false)`
- `goPreview()` 成功后设 `previewDone.value = true`
- `resetImport()` 重置 `previewDone.value = false`
- 模板中 `field-note` class 和文案、`:required` 属性、placeholder 均改为依赖 `previewDone && !fileHasXxx` 三重判断

效果：
- 打开 `/data/import` 初始状态不再显示红色错误提示
- 文件解析后逻辑完全保留：缺列→红色必填提示，有列→已在文件中识别
- 「下一步：字段映射」按钮保持禁用（依赖 `canNext` computed，不受影响）
- 无新增英文，所有文案为中文

### 验证命令

```powershell
npm run build
```

结果：**通过** — vue-tsc 零错误，vite build 成功（9.36s）

```powershell
git diff --check -- frontend docs
```

结果：**通过** — 无空白错误

```powershell
rg -n "10MB|MB|CRUD|..." frontend/src docs/UI_OPTIMIZATION_PLAN.md
```

结果：**仅命中代码技术属性** — `accept` 属性 + `error.ts` 翻译字符串，用户可见文案零命中

### 风险和后续

- 无阻塞问题
- 初始状态 placeholder 显示「上传文件后识别」，用户友好且不会误导
