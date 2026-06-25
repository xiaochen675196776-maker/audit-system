# TASK-073：修复数据查询页横向滚动不可用和标准科目导入层级残留风险

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans`. Do not mark complete until browser-level QA proves `期末贷方余额` is visible after horizontal scroll.

**Goal:** 收尾 TASK-072 验收发现的两个问题：数据查询页横向滚动仍不可用，导致 `期末贷方余额` 实际看不到；`import_standard_accounts()` 更新已有标准科目时没有清空旧 `parent_id`，存在层级残留风险。

**Architecture:** 后端匹配、真实文件导入、删除接口已经通过服务级验收。当前主要缺陷在 `DataView.vue` 的 Element Plus 表格滚动容器 CSS：把 `min-width: 1760px` 加在 `.el-table__inner-wrapper` 上，导致滚动容器自己被撑到 1760px，再被外层 1100px 容器裁掉，用户看不到真正的横向滚动条。

---

## 验收证据

已通过：

- `D:\python\python.exe -m pytest -q`
  - 结果：`372 passed, 3 warnings`
- `npm run build`
  - 结果：`vue-tsc && vite build` 成功
- 真实文件服务级导入：
  - 文件：`D:/NAS/xiaochen/李辉辉项目组/SynologyDrive/汇达228股改审计/1.账套/aglq710-科目余额表 20251231.xlsx`
  - `total_rows=289`
  - `participating_leaf=201`
  - `unmatched=0`
  - `warnings={}`
  - `errors={}`
  - execute：`entry_count=201`，`raw_row_count=289`
  - 删除接口：删除前 entries=201/raw_rows=289/batches=1，删除后 entries=0/raw_rows=0/batch_exists=False/standard_accounts=200

真实文件关键快照已通过：

```text
包装物        -> 141101 包装物
低值易耗品    -> 141102 低值易耗品
在建工程      -> 160401 在建工程-原值
在建工程_生产线 -> 160401 在建工程-原值
管理费用_*    -> 6602 减：管理费用
研发支出_费用化支出_* -> 660201 减：研发费用
```

未通过：

Puppeteer 打开 `http://127.0.0.1:5177/data/view`，1366x768 截图显示表格右侧只到 `期初贷方余额`，看不到后续金额列。自动 DOM 检查结果：

```json
{
  "hasDeleteButton": true,
  "standardColumn": true,
  "hasFixedCode": true,
  "hasFixedName": true,
  "scroll": {
    "clientWidth": 1760,
    "scrollWidth": 1840,
    "after": 80,
    "endingHeaderRect": {
      "left": 1775,
      "right": 1925,
      "tableLeft": 245,
      "tableRight": 1345
    }
  },
  "endingCreditVisibleAfterScroll": false
}
```

根因 DOM：

```json
[
  {
    "cls": "tree-table-wrap",
    "clientWidth": 1100,
    "scrollWidth": 1100,
    "overflowX": "hidden"
  },
  {
    "cls": "el-table ... trial-balance-tree-table",
    "clientWidth": 1100,
    "scrollWidth": 1760,
    "overflowX": "hidden"
  },
  {
    "cls": "el-table__inner-wrapper",
    "clientWidth": 1760,
    "scrollWidth": 1760,
    "rect": { "left": 245, "right": 2005 },
    "overflowX": "visible"
  },
  {
    "cls": "el-scrollbar__wrap",
    "clientWidth": 1760,
    "scrollWidth": 1840,
    "rect": { "left": 245, "right": 2005 },
    "overflowX": "auto"
  }
]
```

也就是说：真正的滚动容器宽度已经被撑到 1760px，超出外层可见区域 1100px；用户看不到有效横向滚动。

---

## 任务 1：修 DataView 横向滚动容器

**文件：**

- 修改：`frontend/src/views/DataView.vue`

**当前错误代码：**

```css
/* fixed 150 + fixed 360 + 标准科目 280 + 方向 70 + 6 金额列*150 + 条目数 80 = 1760 */
.trial-balance-tree-table :deep(.el-table__inner-wrapper) {
  min-width: 1760px;
}
```

这个规则必须删除或改掉。不要把 `min-width` 加在 `.el-table__inner-wrapper` 上。

**建议改法：**

1. 删除 `.el-table__inner-wrapper { min-width: 1760px; }`。
2. 保持 `<el-table style="width: 100%">`，让 Element Plus 自己根据列总宽生成横向滚动。
3. 不要在 `.tree-table-wrap` 上设置 `overflow-x: hidden` 后再把内部 wrapper 撑宽。可保留圆角裁剪，但不能阻断 Element Plus 的横向 scrollbar。
4. 如果删除后仍没有横向滚动，优先使用 Element Plus 原生配置：

```vue
<el-table
  ...
  :fit="false"
  style="width: 100%"
>
```

5. 表格列宽仍按现有：

```text
科目代码 150 fixed left
科目名称 / 客户明细 360 fixed left
标准科目 280
方向 70
六个金额列各 150
条目数 80
```

不要用缩窄金额列来掩盖滚动问题。

**浏览器验收必须满足：**

1366x768 下：

- 表格外层可见宽度约 1100px；
- `.el-scrollbar__wrap.clientWidth` 应接近表格可见宽度，而不是 1760；
- `.el-scrollbar__wrap.scrollWidth > clientWidth`；
- 设置 `.el-scrollbar__wrap.scrollLeft = scrollWidth` 后，`期末贷方余额` 的 header rect 必须落在 table rect 内；
- 截图上能看见 `期末贷方余额`。

Puppeteer 验收核心断言：

```js
const ENDING_CREDIT = '\u671f\u672b\u8d37\u65b9\u4f59\u989d'
const table = document.querySelector('.trial-balance-tree-table')
const wrap = document.querySelector('.trial-balance-tree-table .el-scrollbar__wrap')

wrap.scrollLeft = wrap.scrollWidth
await new Promise(r => setTimeout(r, 300))

const endingHeader = [...document.querySelectorAll('.trial-balance-tree-table th')]
  .find(th => th.innerText.includes(ENDING_CREDIT))
const headerRect = endingHeader.getBoundingClientRect()
const tableRect = table.getBoundingClientRect()

console.log({
  clientWidth: wrap.clientWidth,
  scrollWidth: wrap.scrollWidth,
  scrollLeft: wrap.scrollLeft,
  headerLeft: headerRect.left,
  headerRight: headerRect.right,
  tableLeft: tableRect.left,
  tableRight: tableRect.right,
})

if (!(wrap.scrollWidth > wrap.clientWidth)) throw new Error('表格没有横向滚动宽度')
if (!(headerRect.right > tableRect.left && headerRect.left < tableRect.right)) {
  throw new Error('滚动到最右后仍看不到期末贷方余额')
}
```

---

## 任务 2：补前端视觉回归脚本或手工验收记录

**文件：**

- 可创建：`frontend/scripts/qa-data-view-scroll.mjs`
- 或者不提交脚本，但必须在汇报里贴出 Puppeteer 检查输出和截图路径。

建议创建脚本，避免以后反复回归：

```js
import puppeteer from 'puppeteer'

const url = process.env.QA_URL || 'http://127.0.0.1:5177/data/view'
const ENDING_CREDIT = '\u671f\u672b\u8d37\u65b9\u4f59\u989d'

const browser = await puppeteer.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox'],
})
const page = await browser.newPage()
await page.setViewport({ width: 1366, height: 768 })
await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 })
await page.waitForSelector('.trial-balance-tree-table', { timeout: 30000 })

const result = await page.evaluate(async (ENDING_CREDIT) => {
  const table = document.querySelector('.trial-balance-tree-table')
  const wrap = document.querySelector('.trial-balance-tree-table .el-scrollbar__wrap')
  if (!table || !wrap) throw new Error('表格或滚动容器不存在')

  wrap.scrollLeft = wrap.scrollWidth
  await new Promise(resolve => setTimeout(resolve, 300))

  const endingHeader = [...document.querySelectorAll('.trial-balance-tree-table th')]
    .find(th => th.innerText.includes(ENDING_CREDIT))
  if (!endingHeader) throw new Error('找不到期末贷方余额表头')

  const headerRect = endingHeader.getBoundingClientRect()
  const tableRect = table.getBoundingClientRect()
  return {
    clientWidth: wrap.clientWidth,
    scrollWidth: wrap.scrollWidth,
    scrollLeft: wrap.scrollLeft,
    endingCreditVisible:
      headerRect.right > tableRect.left && headerRect.left < tableRect.right,
    headerRect: {
      left: Math.round(headerRect.left),
      right: Math.round(headerRect.right),
      width: Math.round(headerRect.width),
    },
    tableRect: {
      left: Math.round(tableRect.left),
      right: Math.round(tableRect.right),
      width: Math.round(tableRect.width),
    },
  }
}, ENDING_CREDIT)

console.log(JSON.stringify(result, null, 2))
if (!(result.scrollWidth > result.clientWidth)) {
  throw new Error('表格没有横向滚动宽度')
}
if (!result.endingCreditVisible) {
  throw new Error('滚动到最右后仍看不到期末贷方余额')
}

await page.screenshot({ path: 'qa-data-view-scroll.png', fullPage: false })
await browser.close()
```

---

## 任务 3：修 `import_standard_accounts()` 更新时旧 parent_id 残留

**文件：**

- 修改：`backend/app/services/standard_account_service.py`
- 测试：`backend/tests/test_standard_account_import.py`

**问题：**

`seed_standard_accounts()` 已经会修已有内置库，但 `import_standard_accounts()` 更新已有标准科目时没有清空旧 `parent_id`。如果用户曾经导入过错误层级，再导入新标准科目表把 `141101/141102/660201` 提为一级，旧 `parent_id` 可能仍残留。

当前逻辑只在 `parent_code` 非空时设置父级：

```python
if parent_code and parent_code in code_to_id:
    sa = code_to_id[code]
    parent_sa = code_to_id[parent_code]
    sa.parent_id = parent_sa.id
```

但没有在设置前执行：

```python
for a in accounts:
    code_to_id[a["account_code"]].parent_id = None
```

**必须补测试：**

```python
@pytest.mark.asyncio
async def test_import_standard_accounts_clears_old_parent_id_for_business_roots(db):
    parent = StandardAccount(account_code="1411", account_name="周转材料", level=1, is_leaf=False)
    child = StandardAccount(account_code="141101", account_name="包装物", level=2, is_leaf=True)
    db.add_all([parent, child])
    await db.flush()
    child.parent_id = parent.id
    await db.flush()

    file_path = _make_standard_accounts_excel([
        ["科目代码", "科目名称", "余额方向", "科目类别"],
        ["1411", "周转材料", "debit", "资产类"],
        ["141101", "包装物", "debit", "资产类（明细）"],
    ])

    try:
        result = await import_standard_accounts(db, file_path)
        assert result["error_rows"] == []
        await db.refresh(child)
        assert child.parent_id is None
        assert child.level == 1
        assert child.is_leaf is True
    finally:
        os.unlink(file_path)
```

按测试文件现有 helper 命名调整 `_make_standard_accounts_excel`。

**实现要求：**

在 `import_standard_accounts()` 中，`await db.flush()` 后、补 parent_id 前：

```python
for a in accounts:
    code_to_id[a["account_code"]].parent_id = None
```

`seed_standard_accounts()` 新建库时也可以保持同样模式，虽然新建对象默认 `parent_id=None`。

---

## 任务 4：清理重复常量定义

**文件：**

- 修改：`backend/app/services/standard_account_service.py`

当前 `BUSINESS_ROOT_ACCOUNT_CODES` 在文件头部定义了两次。虽然值相同，不影响运行，但这是明显的任务合并痕迹。保留一次定义即可，注释写清楚：

```python
BUSINESS_ROOT_ACCOUNT_CODES = {
    "141101",  # 包装物：用户要求一级展示，不挂 1411 周转材料
    "141102",  # 低值易耗品：用户要求一级展示，不挂 1411 周转材料
    "660201",  # 减：研发费用：利润表独立展示线，不挂 6602 管理费用
}
```

---

## 必跑命令

后端：

```powershell
cd D:\APP\Codex-项目\13、审计系统\backend
D:\python\python.exe -m pytest tests/test_standard_account_import.py -q
D:\python\python.exe -m pytest tests/test_standard_trial_balance_view.py -q
D:\python\python.exe -m pytest tests/test_client_account_mapping_service.py -q
D:\python\python.exe -m pytest -q
```

前端：

```powershell
cd D:\APP\Codex-项目\13、审计系统\frontend
npm run build
```

浏览器验收：

1. 用真实文件或临时库跑出至少 1 个 executed 批次。
2. 启动后端和前端。
3. 打开 `/data/view`。
4. 1366x768：
   - 删除按钮存在；
   - `科目代码`、`科目名称 / 客户明细` 两列冻结；
   - 有 `标准科目` 列；
   - 展开明细行不换行；
   - 横向滚动到最右能看到 `期末贷方余额`；
   - 截图保存。
5. 1920x1080：
   - 同样检查 `期末贷方余额`，不要只测大屏。

---

## 给执行 AI 的提示词

```text
你来领取并执行：

D:/APP/Codex-项目/13、审计系统/docs/tasks/TASK-073-data-view-horizontal-scroll-acceptance-fixes.md

TASK-072 的后端匹配、真实文件导入和删除接口已经基本通过，但数据查询页横向滚动仍失败。1366x768 下，表格右侧只能看到期初借/贷，滚不到期末贷方。Puppeteer 验收显示：

- .tree-table-wrap clientWidth=1100 overflowX=hidden
- .el-table__inner-wrapper clientWidth=1760 rect.right=2005
- .el-scrollbar__wrap clientWidth=1760 scrollWidth=1840
- 滚动后 期末贷方余额 header left=1775，但 table right=1345

根因是 DataView.vue 把 min-width:1760px 加到了 .el-table__inner-wrapper，导致真正的滚动容器被撑出可视区域。不要继续缩金额列。删除/修正这个 CSS，让 Element Plus 自己在 1100px 可视表格内产生横向滚动。

另外补一个后端小风险：import_standard_accounts() 更新已有标准科目时没有清空旧 parent_id。补测试并在补 parent_id 前把本次 accounts 的 parent_id 先置 None。

完成后必须跑：
- 后端专项和全量 pytest
- frontend npm run build
- Puppeteer 或真实浏览器 1366x768 验收，证明滚动到最右能看到期末贷方余额
```
