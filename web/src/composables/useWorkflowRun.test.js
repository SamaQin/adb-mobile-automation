import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useWorkflowRun } from './useWorkflowRun.js'
import { useConfigStore } from '../stores/configStore.js'
import { useDeviceStore } from '../stores/deviceStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'

beforeEach(() => setActivePinia(createPinia()))

function setup() {
  const config = useConfigStore()
  config.config = {
    acceleration: 'cpu',
    selected_preset_id: 'p',
    presets: [{
      id: 'p',
      name: 'Preset',
      loop_count: 1,
      steps: [
        { id: 'a', name: 'A', kind: 'wait', enabled: true, depends_on: [], params: { seconds: 1 } },
        { id: 'b', name: 'B', kind: 'wait', enabled: true, depends_on: [], params: { seconds: 1 } },
      ],
    }],
  }
  config.dirty = false
  const device = useDeviceStore()
  device.resolution = null
  const run = useRunStore()
  const ui = useUiStore()
  vi.spyOn(device, 'check').mockResolvedValue(true)
  vi.spyOn(config, 'save').mockResolvedValue()
  vi.spyOn(config, 'applyScreenResolution').mockImplementation(() => {})
  vi.spyOn(run, 'start').mockResolvedValue()
  vi.spyOn(ui, 'clearSelection').mockImplementation(() => {})
  vi.spyOn(ui, 'notify').mockImplementation(() => {})
  return { config, device, run, ui, ...useWorkflowRun() }
}

describe('useWorkflowRun', () => {
  it('rejects a disabled start step before touching the device', async () => {
    const { config, device, startWorkflow } = setup()
    config.selectedPreset.steps[1].enabled = false

    await expect(startWorkflow('b')).rejects.toThrow('已停用')
    expect(device.check).not.toHaveBeenCalled()
  })

  it('saves a dirty draft and starts at the requested step', async () => {
    const { config, device, run, ui, startWorkflow } = setup()
    config.dirty = true
    device.resolution = { width: 100, height: 60 }

    await startWorkflow('b')

    expect(device.check).toHaveBeenCalledTimes(1)
    expect(config.applyScreenResolution).toHaveBeenCalledWith({ width: 100, height: 60 })
    expect(config.save).toHaveBeenCalledTimes(1)
    expect(ui.notify).toHaveBeenCalledWith('未保存的修改已自动保存', 'success')
    expect(ui.clearSelection).toHaveBeenCalledTimes(1)
    expect(run.start).toHaveBeenCalledWith('p', 'b')
    expect(run.preparing).toBe(false)
  })

  it('keeps the normal full-run call signature without a start step', async () => {
    const { run, startWorkflow } = setup()

    await startWorkflow()

    expect(run.start).toHaveBeenCalledWith('p')
  })

  it('clears preparing when the device is unavailable', async () => {
    const { device, run, startWorkflow } = setup()
    device.check.mockResolvedValue(false)
    device.error = '未连接 ADB 设备'

    await expect(startWorkflow()).rejects.toThrow('未连接 ADB 设备')
    expect(run.start).not.toHaveBeenCalled()
    expect(run.preparing).toBe(false)
  })

  it('clears preparing and does not start when saving fails', async () => {
    const { config, run, startWorkflow } = setup()
    config.dirty = true
    config.save.mockRejectedValue(new Error('保存失败'))

    await expect(startWorkflow()).rejects.toThrow('保存失败')
    expect(run.start).not.toHaveBeenCalled()
    expect(run.preparing).toBe(false)
  })

  it('rejects an infinite preset with no enabled steps', async () => {
    const { config, run, startWorkflow } = setup()
    config.selectedPreset.loop_count = 0
    config.selectedPreset.steps.forEach((step) => { step.enabled = false })

    await expect(startWorkflow()).rejects.toThrow('无限循环预设至少需要一个启用步骤')
    expect(run.start).not.toHaveBeenCalled()
  })
})
