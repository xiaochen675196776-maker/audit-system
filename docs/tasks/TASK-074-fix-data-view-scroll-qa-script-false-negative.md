# TASK-074：修复数据查询页横向滚动验收脚本误报失败

**Status:** DONE  
**Priority:** P2  
**Owner:** 待领取  
**Context:** TASK-073 的产品功能已通过真实页面验收，但 `frontend/scripts/qa-data-view-scroll.mjs` 仍会误报失败。

## 验收记录

2026-06-24 已验收通过：

- `D:\python\python.exe -m pytest -q`：373 passed。
- `npm run build`：通过。
- 使用真实文件 `aglq710-科目余额表 20251231.xlsx` 导入临时库：289 行、201 条标准余额明细、未匹配 0、warning 0、error 0。
- `node scripts\qa-data-view-scroll.mjs`：1366x768 和 1920x1080 均输出 `endingCreditVisible: true`，最终输出 `=== ALL QA CHECKS PASSED ===`。
- 页面删除按钮实测：删除前批次 1，确认删除后批次 0，页面显示空状态。

## 背景

当前 `DataView.vue` 的真实页面在 1366x768 下可以横向滚动到最右，并且可见 `期末贷方余额`：

```json
{
  "clientWidth": 1100,
  "scrollWidth": 1840,
  "scrollLeft": 740,
  "endingHeaders": [
    { "left": 1115, "right": 1265, "visible": true }
  ]
}
```

但直接运行 `frontend/scripts/qa-data-view-scroll.mjs` 会失败：

```json
{
  "afterScroll": {
    "clientWidth": 1100,
    "scrollWidth": 1840,
    "scrollLeft": 740
  },
  "endingCreditVisible": false,
  "headerRect": {
    "left": 1855,
    "right": 2005,
    "width": 150
  },
  "tableRect": {
    "left": 245,
    "right": 1345,
    "width": 1100
  }
}
```

根因不是页面功能失败，而是脚本只执行：

```js
wrap.scrollLeft = wrap.scrollWidth
```

Element Plus 表格的表头同步依赖滚动事件或真实用户滚动。脚本设置 `scrollLeft` 后没有触发同步，导致读取到未同步的表头位置，形成 false negative。

## 任务目标

修复 `frontend/scripts/qa-data-view-scroll.mjs`，让它可靠模拟真实横向滚动，并且只把真实页面问题判为失败。

## 必改要求

1. 设置横向滚动后必须触发同步：

```js
wrap.scrollLeft = wrap.scrollWidth
wrap.dispatchEvent(new Event('scroll', { bubbles: true }))
await new Promise(resolve => setTimeout(resolve, 500))
```

2. 判定 `期末贷方余额` 是否可见时，不要只取第一个匹配表头；必须过滤到真实可见表头：

```js
const endingHeaders = [...document.querySelectorAll('.trial-balance-tree-table th')]
  .filter(th => th.innerText.includes(ENDING_CREDIT))
  .map(th => {
    const rect = th.getBoundingClientRect()
    return {
      left: rect.left,
      right: rect.right,
      width: rect.width,
      visible: rect.right > tableRect.left && rect.left < tableRect.right && rect.width > 0,
    }
  })

const endingCreditVisible = endingHeaders.some(h => h.visible)
```

3. 保留当前 1366x768 和 1920x1080 两档验收。

4. 保留截图输出，但截图要在滚动同步完成后再截。

5. 不要为了让脚本通过而放宽到“只要存在 scrollWidth 就通过”。必须确认 `期末贷方余额` 真实可见。

## 验收步骤

在已有真实科目余额表导入后的本地服务上执行：

```powershell
cd frontend
$env:QA_URL = 'http://127.0.0.1:<vite-port>/data/view'
node scripts\qa-data-view-scroll.mjs
```

必须输出：

```text
=== ALL QA CHECKS PASSED ===
```

并生成：

```text
frontend/qa-data-view-scroll-1366x768.png
frontend/qa-data-view-scroll-1920x1080.png
```

截图中必须可见 `期末贷方余额` 列。

## 禁止事项

- 不要改掉 `DataView.vue` 的冻结列需求：`科目代码` 和 `科目名称 / 客户明细` 仍必须冻结。
- 不要恢复 `.el-table__inner-wrapper { min-width: 1760px }` 之类的写法。
- 不要删除横向滚动校验。
- 不要只改脚本退出码掩盖失败。

## 给其他 AI 的提示词

请修复 `frontend/scripts/qa-data-view-scroll.mjs` 的误报失败问题。真实页面在 1366x768 下已经能横向滚动看到 `期末贷方余额`，但脚本只设置 `wrap.scrollLeft = wrap.scrollWidth`，没有派发 scroll 事件，导致 Element Plus 表头没有同步，读取到错误的表头位置。  

你需要在滚动后触发 `wrap.dispatchEvent(new Event('scroll', { bubbles: true }))`，等待同步，再检查所有匹配 `期末贷方余额` 的表头，使用 `getBoundingClientRect()` 过滤出真实可见的表头。不要只取第一个表头。保留 1366 和 1920 两档截图验收，脚本必须在真实页面上输出 `=== ALL QA CHECKS PASSED ===`。如果修完脚本后真实页面仍不可见，再回头修 `DataView.vue`，但不要为了脚本通过而掩盖真实问题。
