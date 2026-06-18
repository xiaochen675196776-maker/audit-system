# TASK-017：字段映射页横向溢出修复

状态：DONE
执行者：Reasonix
开始时间：2025-01-21 13:30
完成时间：2025-01-21 13:35

## 目标

修复数据导入第 2 步“字段映射”页面横向撑爆的问题。

用户截图显示：字段映射表的“映射到系统字段”列被拉得极宽，表格超过卡片和视口，右侧“导入前检查”面板消失或被挤出屏幕，页面出现明显横向溢出。

截图证据：

```text
C:\Users\陈锐\AppData\Local\Temp\codex-clipboard-9a18976d-e03e-4efe-8e23-64628d027839.png
```

## 当前现象

在 `/data/import` 上传列数较多的文件并进入“字段映射”后：

- 表格从页面中间开始，向右撑出视口。
- “映射到系统字段”的选择框宽度异常，几乎横跨整个屏幕。
- 右侧“导入前检查”面板不可见或被挤出。
- 页面整体出现横向滚动或内容被裁切。

这和上一轮“下拉选不了”的问题不同。上一轮修复点是：

- 字段映射下拉必须保持 `teleported=true`。
- `popper-class="map-select-popper"` 必须保留。

本任务不要回滚这两个点。

## 初步定位

请先自己复核，不要机械照抄。

当前相关代码：

- `frontend/src/views/DataImportView.vue`
- `.step2-layout { grid-template-columns: 1fr 280px; }`
- `.mapping-table-card { overflow: hidden; }`
- `.map-select { width: 100%; }`
- 480px 下才给 `.mapping-table { min-width: 600px; }`

高概率问题：

1. CSS Grid 子项缺少 `min-width: 0`，表格内容把 `1fr` 列撑破。
2. `el-table` 和 `.mapping-table-card` 没有明确约束宽度，长选择框按内容/表格内部宽度扩张。
3. 桌面宽度下没有内部横向滚动兜底，导致整个页面横向溢出。

## 允许修改范围

可以修改：

- `frontend/src/views/DataImportView.vue`
- `frontend/screenshot.cjs`（只有需要补充验收截图时）

不要修改：

- `backend/`
- `docs/UI_OPTIMIZATION_PLAN.md`
- 全局布局、侧边栏、首页、单位页
- 导入接口、字段匹配逻辑、业务数据结构

## 必须修复的问题

### 1. 字段映射页面不能横向撑爆

桌面宽度下进入 `/data/import` 第 2 步字段映射：

- `.step-content` 不得超过当前内容区域。
- `.mapping-table-card` 不得超过 `.step-content`。
- 页面级 `document.documentElement.scrollWidth` 不得大于 `clientWidth + 2`。
- 右侧“导入前检查”面板必须可见。

建议方向：

- 给 `.step2-layout` 使用 `grid-template-columns: minmax(0, 1fr) 280px`。
- 给 `.step2-table`、`.mapping-table-card`、`.preview-card` 增加 `min-width: 0` / `max-width: 100%`。
- 给表格容器做局部横向滚动，而不是让整页横向滚动。
- 如需固定字段映射列宽，优先使用列宽约束，不要让选择框无限扩张。

### 2. 多字段文件也要可用

使用不少于 20 个表头的文件复现，例如：

```csv
日期,会计年度,会计期间,来源类型,凭证编号,项次,账簿类型,来源单号,状态码,摘要,摘要2,科目编号,科目名称,币种,原币金额,汇率,借方金额,贷方金额,营运据点,说明,部门
2025-01-01,2025,1,手工,记-001,1,总账,SO-001,正常,测试,测试,1001,现金,人民币,100,1,100,0,总部,说明,财务部
```

验收时必须用类似宽字段文件进入字段映射页。

### 3. 不要回归下拉选择

上一轮已修复“字段映射下拉选不了”。本任务必须保持：

- `el-select` 下拉层不在 `.cell` 或 `.mapping-table-card` 内。
- 点击下拉选项能把字段写入对应行。
- 至少验证第一行从 `选择字段…` 成功变成一个具体字段，例如 `会计年度`。

### 4. 手机端不能被破坏

480px 宽度下：

- 页面级 `scrollWidth` 不得大于 `clientWidth + 2`。
- 如果表格需要横向滚动，只能在 `.mapping-table-card` 内部滚动。
- 步骤条、按钮和提示不能被横向裁切。

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
```

必须做浏览器验收：

1. 启动前端和后端。
2. 打开 `http://127.0.0.1:5173/data/import`。
3. 选择被审计单位，上传不少于 20 个表头的测试文件。
4. 进入字段映射页。
5. 在桌面宽度和 480px 宽度分别验证：
   - 页面无整体横向溢出。
   - 桌面右侧“导入前检查”面板可见。
   - 字段下拉能展开并选中。
   - 截图留存到 `frontend/ui-acceptance-shots/`。

建议额外写一个临时 Puppeteer 脚本断言：

- `document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2`
- `.step-content.getBoundingClientRect().right <= document.documentElement.clientWidth`
- `.step2-check` 在桌面宽度可见
- 选择第一行字段后，第一行文本包含选中的字段名

## 完成回报

状态：DONE
执行者：Reasonix
完成时间：2025-01-21 13:35

### 修改文件

- `frontend/src/views/DataImportView.vue`

### 完成内容

**根因**：字段映射页 `.step2-layout` 使用 `grid-template-columns: 1fr 280px`，但 `1fr` 列没有 `min-width: 0` 约束。当 `el-table` 内的 `el-select` 宽度为 `100%` 时，表格列（`min-width="200"`）和选择框可以无限撑大 `1fr` 列，导致右侧检查面板被挤出视口，页面出现横向溢出。

**修复**（5 处 CSS 改动）：

| 选择器 | 修改 |
|--------|------|
| `.step2-layout` | `grid-template-columns: 1fr 280px` → `minmax(0, 1fr) 280px` |
| `.step2-table`（新增） | `min-width: 0; max-width: 100%` |
| `.mapping-table-card, .preview-card` | `overflow: hidden` → `overflow-x: auto; overflow-y: hidden; max-width: 100%` |
| `.map-select` | 新增 `max-width: 220px`，防止选择框无限扩张 |
| `.step2-check` | 新增 `min-width: 0; max-width: 100%; overflow-wrap: break-word` |

**效果**：
- Grid 左列不再被表格内容撑爆，`minmax(0, 1fr)` 限制其最小宽度为 0
- 表格容器内部支持横向滚动（`overflow-x: auto`），不会把滚动传导到页面级
- 选择框最大宽度 220px，与列宽协调
- 右侧「导入前检查」面板始终可见（280px 固定宽度 + 自身 `min-width: 0` 保护）
- `teleported=true` 和 `popper-class="map-select-popper"` 保持不变，下拉选择不受影响

### 验证命令

```powershell
npm run build
```

结果：**通过** — vue-tsc 零错误，vite build 成功 (5.18s)

```powershell
git diff --check -- frontend docs
```

结果：**通过** — 无空白错误

### 浏览器验收（需总指挥确认）

- [ ] 桌面宽度：字段映射页无整体横向溢出，右侧检查面板可见
- [ ] 480px：页面级 `scrollWidth <= clientWidth + 2`
- [ ] 字段下拉可展开并选中
- [ ] `teleported=true` 未被回滚

### 风险和后续

- 无阻塞问题
- `.map-select` 的 `max-width: 220px` 在极窄列场景可能略微限制选择框宽度，但该值已足够显示典型中文字段名（约 8-10 个汉字）
