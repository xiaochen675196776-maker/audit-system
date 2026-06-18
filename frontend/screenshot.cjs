// Screenshot script for TASK-010 acceptance verification
const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

const BASE_URL = 'http://127.0.0.1:5173';
const OUT_DIR = path.resolve(__dirname, 'ui-acceptance-shots');

if (!fs.existsSync(OUT_DIR)) {
  fs.mkdirSync(OUT_DIR, { recursive: true });
}

const pages = ['/', '/data/import', '/data/companies'];
const viewports = [
  { name: 'desktop', width: 1440, height: 1024 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'small', width: 480, height: 900 },
];

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files/Google/Chrome/Application/chrome.exe',
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  const page = await browser.newPage();

  for (const vp of viewports) {
    await page.setViewport({ width: vp.width, height: vp.height, deviceScaleFactor: 2 });

    for (const url of pages) {
      const name = url === '/' ? 'home' : url.replace('/data/', '').replace('/', '-');
      const filename = `${name}-${vp.name}.png`;
      const filepath = path.join(OUT_DIR, filename);

      try {
        await page.goto(BASE_URL + url, { waitUntil: 'networkidle2', timeout: 15000 });
        // Wait a bit more for Vue rendering
        await new Promise(r => setTimeout(r, 1000));
        await page.screenshot({ path: filepath, fullPage: false });
        console.log(`OK: ${filename}`);
      } catch (err) {
        console.error(`FAIL: ${filename} — ${err.message}`);
      }
    }
  }

  await browser.close();
  console.log('Done.');
})();
