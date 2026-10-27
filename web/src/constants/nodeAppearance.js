import {
  CircleDot,
  Crosshair,
  GitBranch,
  Hourglass,
  Layers3,
  Play,
  Repeat2,
  Route,
  Search,
} from 'lucide-vue-next'

export const NODE_APPEARANCE = {
  find_and_tap: { color: '#34d399', icon: Search },
  tap: { color: '#38bdf8', icon: Crosshair },
  swipe: { color: '#fbbf24', icon: Route },
  wait: { color: '#94a3b8', icon: Hourglass },
  end_loop: { color: '#c084fc', icon: Repeat2 },
  run_preset: { color: '#22d3ee', icon: Play },
  branch: { color: '#f59e0b', icon: GitBranch },
  group: { color: '#94a3b8', icon: Layers3 },
  default: { color: '#94a3b8', icon: CircleDot },
}

// Short explanations are shared by the library and the canvas quick menu.
const STEP_GUIDANCE = {
  find_and_tap: { description: '按图片找到按钮，再点击或连击', aliases: '识图 找图 图片 模板 识别 查找 按钮 连点 连击 recognition' },
  tap: { description: '点击屏幕上的固定位置', aliases: '单击 点按 触摸 坐标 按钮' },
  swipe: { description: '滑动屏幕，翻页或拖动内容', aliases: '拖动 滚动 翻页 上滑 下滑 左滑 右滑' },
  wait: { description: '暂停几秒，等页面加载完成', aliases: '延时 延迟 暂停 休息 加载 等待' },
  end_loop: { description: '结束这一轮，从下一轮重新开始', aliases: '循环 下一轮 结束 跳过 本轮' },
  run_preset: { description: '接着执行另一组已保存的步骤', aliases: '调用 子流程 复用 预设 组合 另一组' },
}

export function descriptionFor(kind) {
  return STEP_GUIDANCE[kind]?.description || '添加后设置这一步的具体操作'
}

export function matchesStepSearch(definition, query) {
  const text = `${definition.label} ${definition.key} ${descriptionFor(definition.key)} ${STEP_GUIDANCE[definition.key]?.aliases || ''}`.toLowerCase()
  return query.trim().toLowerCase().split(/\s+/).every((term) => text.includes(term))
}

export function appearanceFor(kind) {
  return NODE_APPEARANCE[kind] || NODE_APPEARANCE.default
}
