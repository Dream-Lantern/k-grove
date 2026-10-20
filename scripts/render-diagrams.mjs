import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = fileURLToPath(new URL('../', import.meta.url))
const source = path.join(root, 'diagrams', 'examples')
const output = path.join(root, 'artifacts', 'diagrams')
const candidates = [
  process.env.MERMAID_BROWSER_PATH,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/chromium',
  '/usr/bin/google-chrome',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
]
const browser = candidates.find(candidate => candidate && fs.existsSync(candidate))
if (!browser) throw new Error('请用 MERMAID_BROWSER_PATH 指定本机 Chromium/Chrome/Edge；不会自动下载浏览器。')

// 仅渲染仓库内人工编写的示例，不读取私有笔记，不将图自动写入网站。
const files = fs.readdirSync(source).filter(file => file.endsWith('.mmd')).sort()
if (!files.length) throw new Error('没有 Mermaid 示例图源')
fs.mkdirSync(output, { recursive: true })
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'kb-mermaid-'))
try {
  const config = path.join(temporary, 'puppeteer.json')
  fs.writeFileSync(config, JSON.stringify({ executablePath: browser }))
  for (const file of files) {
    const input = path.join(source, file)
    if (fs.lstatSync(input).isSymbolicLink()) throw new Error('图源不能是符号链接')
    const target = path.join(output, file.replace(/\.mmd$/, '.svg'))
    const result = spawnSync(process.execPath, [
      path.join(root, 'node_modules', '@mermaid-js', 'mermaid-cli', 'src', 'cli.js'),
      '-i', input, '-o', target, '-c', path.join(root, 'diagrams', 'mermaid.config.json'),
      '-p', config, '-b', 'white'
    ], { cwd: root, stdio: 'inherit' })
    if (result.error) throw result.error
    if (result.status !== 0) throw new Error(`图源渲染失败：${file}`)
  }
  console.log(`已生成 ${files.length} 个本地示例 SVG：artifacts/diagrams/（未加入公开站点）`)
} finally {
  fs.unlinkSync(path.join(temporary, 'puppeteer.json'))
  fs.rmdirSync(temporary)
}
