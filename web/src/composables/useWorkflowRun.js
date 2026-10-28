import { useConfigStore } from '../stores/configStore.js'
import { useDeviceStore } from '../stores/deviceStore.js'
import { useRunStore } from '../stores/runStore.js'
import { useUiStore } from '../stores/uiStore.js'

function hasEnabledStep(steps) {
  for (const step of steps || []) {
    if (step.enabled) return true
    for (const branch of Object.values(step.params?.branches || {})) {
      if (hasEnabledStep(branch)) return true
    }
  }
  return false
}

export function useWorkflowRun() {
  const config = useConfigStore()
  const device = useDeviceStore()
  const run = useRunStore()
  const ui = useUiStore()

  async function startWorkflow(startStepId = null) {
    if (run.running || run.preparing || config.saving || device.operationBusy) return
    const preset = config.selectedPreset
    if (!preset) throw new Error('请先选择要运行的预设')
    if (startStepId) {
      const step = preset.steps.find((item) => item.id === startStepId)
      if (!step) throw new Error('找不到要运行的步骤')
      if (!step.enabled) throw new Error('该步骤已停用，无法从它开始运行')
    }

    run.preparing = true
    try {
      const connected = await device.check()
      if (!connected) throw new Error(device.error || '未连接 ADB 设备')
      if (config.dirty) {
        if (device.resolution) config.applyScreenResolution(device.resolution)
        await config.save()
        ui.notify('未保存的修改已自动保存', 'success')
      }
      if (!startStepId && preset.loop_count === 0 && !hasEnabledStep(preset.steps)) {
        throw new Error('无限循环预设至少需要一个启用步骤')
      }
      ui.clearSelection()
      if (startStepId) await run.start(preset.id, startStepId)
      else await run.start(preset.id)
    } finally {
      run.preparing = false
    }
  }

  return { startWorkflow }
}
