/**
 * TASK-073/074 QA: DataView 横向滚动验收脚本
 * 1366x768 / 1920x1080 下验证滚动到最右能看到"期末贷方余额"
 */
import puppeteer from 'puppeteer'

const url = process.env.QA_URL || 'http://127.0.0.1:5177/data/view'
const ENDING_CREDIT = '\u671f\u672b\u8d37\u65b9\u4f59\u989d'

const browser = await puppeteer.launch({
  headless: 'new',
  args: ['--no-sandbox', '--disable-setuid-sandbox'],
})
const page = await browser.newPage()

// 一次性加载页面（用小视口，后面再 resize）
await page.setViewport({ width: 1366, height: 768 })
await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 })
await page.waitForSelector('.trial-balance-tree-table', { timeout: 30000 })
await new Promise(r => setTimeout(r, 2000))

async function runQa(viewportWidth, viewportHeight, label) {
  // resize 触发布局重算（不需要重新导航）
  await page.setViewport({ width: viewportWidth, height: viewportHeight })
  await new Promise(r => setTimeout(r, 800))

  const result = await page.evaluate(async (ENDING_CREDIT) => {
    const table = document.querySelector('.trial-balance-tree-table')
    const wrap = document.querySelector('.trial-balance-tree-table .el-scrollbar__wrap')
    if (!table || !wrap) throw new Error('表格或滚动容器不存在')

    const beforeScroll = {
      clientWidth: wrap.clientWidth,
      scrollWidth: wrap.scrollWidth,
      innerWrapperWidth:
        document.querySelector('.trial-balance-tree-table .el-table__inner-wrapper')
          ?.clientWidth,
    }

    // 设置横向滚动并派发 scroll 事件，触发 Element Plus 表头同步
    wrap.scrollLeft = wrap.scrollWidth
    wrap.dispatchEvent(new Event('scroll', { bubbles: true }))
    await new Promise(resolve => setTimeout(resolve, 500))

    const tableRect = table.getBoundingClientRect()

    // 收集所有匹配的表头，检查哪些真实可见
    const endingHeaders = [...document.querySelectorAll('.trial-balance-tree-table th')]
      .filter(th => th.innerText.includes(ENDING_CREDIT))
      .map(th => {
        const rect = th.getBoundingClientRect()
        return {
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          visible:
            rect.right > tableRect.left &&
            rect.left < tableRect.right &&
            rect.width > 0,
        }
      })

    const endingCreditVisible = endingHeaders.some(h => h.visible)

    return {
      beforeScroll,
      afterScroll: {
        clientWidth: wrap.clientWidth,
        scrollWidth: wrap.scrollWidth,
        scrollLeft: wrap.scrollLeft,
      },
      endingCreditVisible,
      endingHeaders,
      tableRect: {
        left: Math.round(tableRect.left),
        right: Math.round(tableRect.right),
        width: Math.round(tableRect.width),
      },
    }
  }, ENDING_CREDIT)

  console.log(`\n=== ${label} Results ===`)
  console.log(JSON.stringify(result, null, 2))

  // 校验
  if (!(result.afterScroll.scrollWidth > result.afterScroll.clientWidth)) {
    throw new Error(`${label}: 表格没有横向滚动宽度`)
  }
  if (!result.endingCreditVisible) {
    throw new Error(`${label}: 滚动到最右后仍看不到期末贷方余额`)
  }

  // 滚动同步完成后再截图
  await page.screenshot({
    path: `qa-data-view-scroll-${label}.png`,
    fullPage: false,
  })
  console.log(`PASS: ${label} screenshot saved to qa-data-view-scroll-${label}.png`)
}

try {
  await runQa(1366, 768, '1366x768')
  await runQa(1920, 1080, '1920x1080')
  console.log('\n=== ALL QA CHECKS PASSED ===')
} finally {
  await browser.close()
}
