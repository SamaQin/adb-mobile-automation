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

export function appearanceFor(kind) {
  return NODE_APPEARANCE[kind] || NODE_APPEARANCE.default
}
