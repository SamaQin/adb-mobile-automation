import { mkdir } from 'node:fs/promises'
import { chromium } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL || 'http://127.0.0.1:8000'
const outputDir = process.env.PLAYWRIGHT_OUTPUT_DIR || 'artifacts'
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE

async function dragConnection(page, source, target) {
  const sourceBox = await source.boundingBox()
  const targetBox = await target.boundingBox()
  if (!sourceBox || !targetBox) throw new Error('连接点位不可见')
  await source.hover({ force: true })
  await page.mouse.move(sourceBox.x + sourceBox.width / 2, sourceBox.y + sourceBox.height / 2)
  await page.mouse.down()
  await page.mouse.move(targetBox.x + targetBox.width / 2, targetBox.y + targetBox.height / 2, { steps: 8 })
  await page.mouse.up()
}

await mkdir(outputDir, { recursive: true })

const browser = await chromium.launch({
  headless: true,
  ...(executablePath ? { executablePath } : {}),
})

try {
  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1280, height: 800 },
  ]) {
    const page = await browser.newPage({ viewportSize: viewport })
    const browserErrors = []
    page.on('pageerror', (error) => browserErrors.push(error.message))
    page.on('console', (message) => {
      if (message.type() === 'error') browserErrors.push(message.text())
    })

    const response = await page.goto(baseURL, { waitUntil: 'networkidle' })
    if (!response?.ok()) throw new Error(`页面加载失败: ${response?.status()}`)
    await page.locator('.topbar').waitFor()
    await page.locator('.ws-state.connected').waitFor({ timeout: 10000 })

    const health = await page.evaluate(async () => {
      const result = await fetch('/api/health')
      return { status: result.status, body: await result.json() }
    })
    if (health.status !== 200 || health.body.status !== 'ok') {
      throw new Error(`前后端健康检查失败: ${JSON.stringify(health)}`)
    }

    const layout = await page.evaluate(() => {
      const box = (selector) => {
        const rect = document.querySelector(selector)?.getBoundingClientRect()
        return rect ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height } : null
      }
      return {
        topbar: box('.topbar'),
        palette: box('.palette'),
        canvas: box('.flow-canvas'),
        properties: box('.properties'),
        logs: box('.log-panel'),
        topbarOverflow: document.querySelector('.topbar')?.scrollWidth > document.querySelector('.topbar')?.clientWidth,
        nodeCount: document.querySelectorAll('.step-node').length,
        controlButtons: [...document.querySelectorAll('.vue-flow__controls-button')].map((button) => {
          const rect = button.getBoundingClientRect()
          return { top: rect.top, height: rect.height }
        }),
      }
    })
    if (!layout.palette || !layout.canvas || !layout.properties || !layout.logs) {
      throw new Error(`工作台区域缺失: ${JSON.stringify(layout)}`)
    }
    if (layout.topbarOverflow) throw new Error(`顶部工具栏在 ${viewport.width}x${viewport.height} 溢出`)
    if (layout.palette.x + layout.palette.width > layout.canvas.x || layout.canvas.x + layout.canvas.width > layout.properties.x) {
      throw new Error(`主工作区横向重叠: ${JSON.stringify(layout)}`)
    }
    if (layout.canvas.y + layout.canvas.height > layout.logs.y + 1) {
      throw new Error(`画布与日志区域重叠: ${JSON.stringify(layout)}`)
    }
    if (layout.nodeCount < 2) throw new Error('未从后端配置渲染出步骤节点')
    if (layout.controlButtons.length !== 4
      || new Set(layout.controlButtons.map((button) => button.top)).size !== 1
      || new Set(layout.controlButtons.map((button) => button.height)).size !== 1) {
      throw new Error(`画布控制按钮未对齐: ${JSON.stringify(layout.controlButtons)}`)
    }

    await page.locator('.canvas-toolbar button[title="自动布局"]').click()
    await page.waitForTimeout(450)
    const autoLayoutCenters = await page.evaluate(() => {
      const centerX = (selector) => {
        const rect = document.querySelector(selector)?.getBoundingClientRect()
        return rect ? rect.x + rect.width / 2 : null
      }
      return {
        start: centerX('.vue-flow__node-start'),
        firstStep: centerX('.vue-flow__node-step'),
      }
    })
    if (autoLayoutCenters.start == null || autoLayoutCenters.firstStep == null
      || Math.abs(autoLayoutCenters.start - autoLayoutCenters.firstStep) > 1) {
      throw new Error(`自动布局未将开始节点与主步骤居中对齐: ${JSON.stringify(autoLayoutCenters)}`)
    }

    const presetSelect = page.locator('.preset-select select')
    const presetOptions = await presetSelect.locator('option').allTextContents()
    if (presetOptions.length > 1) {
      const initialPreset = await presetSelect.inputValue()
      const initialEdges = await page.locator('.vue-flow__edge-path').count()
      await Promise.all([
        page.waitForResponse((item) => item.url().includes('/api/config') && item.request().method() !== 'GET'),
        presetSelect.selectOption({ index: 1 }),
      ])
      await Promise.all([
        page.waitForResponse((item) => item.url().includes('/api/config') && item.request().method() !== 'GET'),
        presetSelect.selectOption(initialPreset),
      ])
      await page.waitForTimeout(250)
      const returnedEdges = await page.locator('.vue-flow__edge-path').evaluateAll((paths) => paths.map((path) => path.getAttribute('d')))
      if (returnedEdges.length !== initialEdges || returnedEdges.some((path) => !path || path.includes('NaN'))) {
        throw new Error(`切换预设后连接线未恢复: ${JSON.stringify(returnedEdges)}`)
      }
    }

    const canvasWidth = layout.canvas.width
    await page.getByTitle('收起节点库').click()
    const collapsedPaletteWidth = await page.locator('.palette').evaluate((element) => element.getBoundingClientRect().width)
    const canvasAfterPaletteCollapse = await page.locator('.flow-canvas').evaluate((element) => element.getBoundingClientRect().width)
    if (collapsedPaletteWidth !== 42 || canvasAfterPaletteCollapse <= canvasWidth) throw new Error('节点库折叠未释放画布空间')
    await page.getByTitle('展开节点库').click()
    await page.getByTitle('收起检查器').click()
    const collapsedPropertiesWidth = await page.locator('.properties').evaluate((element) => element.getBoundingClientRect().width)
    if (collapsedPropertiesWidth !== 42) throw new Error('检查器折叠宽度不正确')
    await page.getByTitle('展开检查器').click()

    const recognitionLabels = await page.locator('.palette-item strong').allTextContents()
    if (recognitionLabels.filter((label) => label === '识别模板并点击/连击').length !== 1
      || recognitionLabels.some((label) => label === '识别模板并连击')) {
      throw new Error(`识别节点未正确合并: ${JSON.stringify(recognitionLabels)}`)
    }
    await page.locator('.step-node').filter({ hasText: '模板分支验证' }).click()
    const recognitionInspector = await page.evaluate(() => ({
      choices: [...document.querySelectorAll('.choice-field label')].map((item) => item.textContent.trim()),
      text: document.querySelector('.step-form')?.textContent || '',
      coordinateGroups: [...document.querySelectorAll('.coordinate-group')].map((group) => {
        const groupRect = group.getBoundingClientRect()
        const buttonRect = group.querySelector('.coordinate-group-picker')?.getBoundingClientRect()
        return { rows: group.querySelectorAll('.field').length, height: groupRect.height, buttonHeight: buttonRect?.height }
      }),
      customClickChecked: Boolean([...document.querySelectorAll('.toggle-field')]
        .find((element) => element.textContent.includes('自定义点击'))
        ?.querySelector('input[type="checkbox"]')?.checked),
    }))
    if (recognitionInspector.choices.join(',') !== '点击,连击'
      || !recognitionInspector.text.includes('自定义点击')
      || recognitionInspector.text.includes('点击偏移 X')
      || recognitionInspector.coordinateGroups.length !== 2
      || recognitionInspector.customClickChecked) {
      throw new Error(`识别属性或坐标拾取分组不正确: ${JSON.stringify(recognitionInspector)}`)
    }
    const customClickToggle = page.locator('.toggle-field', { hasText: '自定义点击' }).locator('input[type="checkbox"]')
    await customClickToggle.check()
    const groupsWithCustomClick = await page.locator('.coordinate-group').evaluateAll((groups) => groups.map((group) => {
      const rect = group.getBoundingClientRect()
      const buttonRect = group.querySelector('.coordinate-group-picker')?.getBoundingClientRect()
      return { rows: group.querySelectorAll('.field').length, height: rect.height, buttonHeight: buttonRect?.height }
    }))
    if (groupsWithCustomClick.length !== 3
      || groupsWithCustomClick.some((group) => group.rows < 2 || Math.abs(group.height - group.buttonHeight) > 1)) {
      throw new Error(`开启自定义点击后坐标拾取分组不正确: ${JSON.stringify(groupsWithCustomClick)}`)
    }

    const startNode = page.locator('.vue-flow__node-start')
    const startBefore = await startNode.boundingBox()
    if (!startBefore) throw new Error('开始节点不可见')
    await page.mouse.move(startBefore.x + startBefore.width / 2, startBefore.y + startBefore.height / 2)
    await page.mouse.down()
    await page.mouse.move(startBefore.x + startBefore.width / 2 + 36, startBefore.y + startBefore.height / 2 + 24, { steps: 6 })
    await page.mouse.up()
    const startAfter = await startNode.boundingBox()
    const storedStart = await page.evaluate(() => Object.keys(localStorage)
      .filter((key) => key.startsWith('layout:'))
      .map((key) => JSON.parse(localStorage.getItem(key)))
      .find((value) => value.start)?.start)
    if (!startAfter || startAfter.x <= startBefore.x + 20 || !storedStart) throw new Error('开始节点未移动或未持久化布局')

    await page.locator('.step-node').first().click({ button: 'right' })
    await page.locator('.canvas-context-menu').getByText('修改属性', { exact: true }).waitFor()
    await page.locator('.canvas-context-menu').getByText('修改属性', { exact: true }).click()
    await page.locator('.step-form').waitFor()

    const nodeCountBeforeContextAdd = await page.locator('.step-node').count()
    const pane = page.locator('.vue-flow__pane')
    const paneBox = await pane.boundingBox()
    if (!paneBox) throw new Error('画布空白区域不可见')
    await page.mouse.click(paneBox.x + paneBox.width - 70, paneBox.y + 90, { button: 'right' })
    await page.locator('.canvas-context-menu').getByText('新增节点', { exact: true }).waitFor()
    await page.locator('.context-node-list button').first().click()
    if (await page.locator('.step-node').count() !== nodeCountBeforeContextAdd + 1) throw new Error('右键菜单新增节点失败')

    const edgesBeforeDoubleClick = await page.locator('.vue-flow__edge').count()
    const handles = await page.evaluate(() => ({
      start: getComputedStyle(document.querySelector('.vue-flow__node-start [data-handleid="order-source"]')).pointerEvents,
      branch: getComputedStyle(document.querySelector('.branch-handle')).pointerEvents,
      dependency: getComputedStyle(document.querySelector('.dependency-handle')).pointerEvents,
    }))
    if (Object.values(handles).some((value) => value !== 'all')) throw new Error(`连接点位不可拖线: ${JSON.stringify(handles)}`)
    await page.locator('.vue-flow__pane').dblclick({ position: { x: 300, y: 300 } })
    await page.waitForTimeout(250)
    const edgesAfterDoubleClick = await page.locator('.vue-flow__edge').count()
    if (edgesAfterDoubleClick !== edgesBeforeDoubleClick) {
      throw new Error(`双击画布导致连接线丢失: ${edgesBeforeDoubleClick} -> ${edgesAfterDoubleClick}`)
    }

    await page.locator('.step-node').first().click()
    await page.locator('.step-form').waitFor()
    await page.getByTitle('模板管理').click()
    await page.locator('.template-drawer').waitFor()
    await page.getByTitle('关闭模板管理').click()

    await page.screenshot({
      path: `${outputDir}/workbench-${viewport.width}x${viewport.height}.png`,
      fullPage: true,
    })
    if (browserErrors.length) throw new Error(`浏览器错误: ${browserErrors.join(' | ')}`)
    await page.close()
  }

  if (process.env.PLAYWRIGHT_INTERACTIVE === '1') {
    const page = await browser.newPage({ viewportSize: { width: 1440, height: 900 } })
    await page.goto(baseURL, { waitUntil: 'networkidle' })
    await page.locator('.ws-state.connected').waitFor({ timeout: 10000 })

    const mainNodes = page.locator('.vue-flow__node-step')
    await dragConnection(
      page,
      mainNodes.nth(2).locator('[data-handleid="dependency-source"]'),
      mainNodes.nth(3).locator('[data-handleid="order-target"]'),
    )
    await page.waitForTimeout(750)
    const dependencyResult = await page.evaluate(() => ({
      count: document.querySelectorAll('.edge-dependency').length,
      nodes: [...document.querySelectorAll('.vue-flow__node-step')].map((node) => ({ id: node.dataset.id, text: node.textContent.trim() })),
      toast: document.querySelector('.toast')?.textContent.trim() || '',
    }))
    if (dependencyResult.count !== 2) throw new Error(`拖线创建依赖失败: ${JSON.stringify(dependencyResult)}`)

    await dragConnection(
      page,
      mainNodes.nth(3).locator('[data-handleid="order-source"]'),
      mainNodes.nth(0).locator('[data-handleid="order-target"]'),
    )
    await page.waitForTimeout(750)
    const returnCount = await page.locator('.edge-return').count()
    const returnBadge = await page.locator('.badge.return').count()
    if (returnCount !== 1 || returnBadge !== 1) throw new Error(`返回连接未创建: ${returnCount} 边 / ${returnBadge} 徽标`)
    await page.locator('.edge-return').click()
    await page.locator('.edge-panel').waitFor()
    await page.getByText('返回连接', { exact: true }).waitFor()
    await page.keyboard.press('Delete')
    await page.waitForTimeout(350)
    if (await page.locator('.edge-return').count() !== 0) throw new Error('返回连接删除失败')

    const branchPane = page.locator('.vue-flow__pane')
    const branchPaneBox = await branchPane.boundingBox()
    if (!branchPaneBox) throw new Error('画布空白区域不可见')
    await page.mouse.move(branchPaneBox.x + branchPaneBox.width * 0.3, branchPaneBox.y + branchPaneBox.height * 0.6)
    await page.mouse.down()
    await page.mouse.move(branchPaneBox.x + branchPaneBox.width * 0.3 - 260, branchPaneBox.y + branchPaneBox.height * 0.6 - 90, { steps: 8 })
    await page.mouse.up()
    await page.waitForTimeout(400)
    await dragConnection(
      page,
      page.locator('.vue-flow__node-branch').locator('[data-handleid="order-source"]'),
      mainNodes.nth(0).locator('[data-handleid="order-target"]'),
    )
    await page.waitForTimeout(750)
    const branchReturnCount = await page.locator('.edge-return').count()
    const branchReturnBadge = await page.locator('.vue-flow__node-branch .badge.return').count()
    if (branchReturnCount !== 1 || branchReturnBadge !== 1) throw new Error(`分支步骤返回主流程连接未创建: ${branchReturnCount} 边 / ${branchReturnBadge} 徽标`)
    const branchSourceHandle = await page.locator('.vue-flow__node-branch [data-handleid="order-source"]').boundingBox()
    if (!branchSourceHandle) throw new Error('分支节点下点位不可见')
    await page.mouse.click(branchSourceHandle.x + branchSourceHandle.width / 2, branchSourceHandle.y + branchSourceHandle.height / 2 + 6)
    await page.locator('.edge-panel').waitFor()
    await page.getByText('返回连接', { exact: true }).waitFor()
    await page.keyboard.press('Delete')
    await page.waitForTimeout(350)
    if (await page.locator('.edge-return').count() !== 0) throw new Error('分支返回连接删除失败')

    await page.locator('.step-node').first().click()
    await page.locator('.step-node').nth(1).click({ modifiers: ['Shift'] })
    page.once('dialog', (dialog) => dialog.accept('验收泳道'))
    await page.getByTitle('将所选步骤加入新泳道').click()
    await page.locator('.group-node').waitFor()

    const connectionGeometry = await page.evaluate(() => {
      const position = (selector) => {
        const rect = document.querySelector(selector)?.getBoundingClientRect()
        return rect ? { x: rect.x, y: rect.y } : null
      }
      return {
        first: position('.step-node'),
        special: position('.step-node:nth-of-type(2)'),
        dependencyHandles: document.querySelectorAll('.dependency-handle').length,
        branchHandles: document.querySelectorAll('.branch-handle').length,
        branchLabels: [...document.querySelectorAll('.branch-output-label')].map((element) => element.textContent.trim()),
      }
    })
    if (!connectionGeometry.dependencyHandles || !connectionGeometry.branchHandles || !connectionGeometry.branchLabels.includes('branch.png')) {
      throw new Error(`特殊/分支点位缺失: ${JSON.stringify(connectionGeometry)}`)
    }

    await page.getByTitle('运行当前预设').click()
    await page.getByTitle('停止运行').waitFor({ timeout: 10000 })
    await page.locator('.step-node.state-running').waitFor({ timeout: 10000 })
    if (await page.locator('.step-node.state-running').count() !== 1) throw new Error('运行时必须只有一个节点外发光')
    await page.screenshot({ path: `${outputDir}/workbench-running.png`, fullPage: true })
    await page.getByTitle('停止运行').click()
    await page.getByTitle('运行当前预设').waitFor({ timeout: 10000 })
    await page.getByText('执行已停止', { exact: false }).last().waitFor({ timeout: 10000 })

    await page.locator('.step-node').nth(1).click()
    const pointBefore = await page.locator('.coordinate-group input').evaluateAll((inputs) => inputs.map((input) => input.value))
    await page.getByTitle('从截图选取X 坐标、Y 坐标').click()
    await page.locator('.screenshot-modal').waitFor()
    const canvas = page.locator('.screenshot-stage canvas')
    const canvasBox = await canvas.boundingBox()
    if (!canvasBox) throw new Error('截图画布不可见')
    await canvas.click({ position: { x: canvasBox.width * 0.62, y: canvasBox.height * 0.43 } })
    await page.getByRole('button', { name: '确认选择' }).click()
    await page.locator('.screenshot-modal').waitFor({ state: 'detached' })
    const pointAfter = await page.locator('.coordinate-group input').evaluateAll((inputs) => inputs.map((input) => input.value))
    if (pointAfter.length !== 2 || pointAfter.some((value, index) => value === pointBefore[index])) {
      throw new Error(`共用坐标按钮未同步回填 X/Y: ${JSON.stringify({ pointBefore, pointAfter })}`)
    }

    await page.screenshot({ path: `${outputDir}/workbench-interactive.png`, fullPage: true })
    await page.close()
  }

  console.log(`acceptance_ok base=${baseURL} output=${outputDir}`)
} finally {
  await browser.close()
}
