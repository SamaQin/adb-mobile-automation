# ADB 图像自动化应用 Android 移植功能技术文档

## 1. 文档信息

| 项目 | 内容 |
| --- | --- |
| 文档状态 | 移植设计基线 |
| 源应用 | Windows Python 3.12 + Tkinter + ADB + OpenCV |
| 目标应用 | Android 原生应用 |
| 推荐技术栈 | Kotlin、Jetpack Compose、Coroutines、OpenCV Android SDK |
| 推荐最低版本 | Android 11（API 30） |
| 配置协议 | `fgo_config.json`，schema version 2 |
| 预设包协议 | ZIP，archive version 1 |
| 当前自动化测试基线 | 39 项单元测试 |

本文档根据当前仓库代码定义 Android 移植目标。它用于产品评审、技术设计、开发拆分和验收，不包含移植代码。

## 2. 移植目标

Android 版本必须在同一台手机上完成预设编辑、屏幕捕获、模板识别、点击、滑动、循环执行、停止控制和预设交换，不再依赖电脑、USB 调试或外部 `adb.exe`。

Android 版本必须兼容桌面版的配置数据和导出预设包。相同预设在满足截图权限、无障碍权限和目标页面可截图的条件下，应保持相同执行语义。

### 2.1 必须保留

- 预设的新建、复制、重命名、删除、选择和循环次数。
- 步骤的新增、编辑、复制、启停、删除、上移、下移和拖拽排序。
- 等待、坐标点击、滑动、识别模板并点击、识别模板并连击五种步骤。
- 步骤失败控制、前置步骤依赖、整套预设循环和手动停止。
- 模板截图、框选、导入、重新截取、删除和阈值设置。
- 设备分辨率记录、导入时坐标与模板缩放。
- 多目标识别时从上到下、同一高度从左到右选择。
- 运行状态、执行日志和明确的失败原因。
- 含模板图片的预设导入和导出。

### 2.2 本次移植不新增

- OCR、文字识别或语义控件识别。
- 条件分支、变量、脚本语言和跨预设调用。
- 云同步、账号系统和远程控制。
- 多设备并行控制。
- 绕过 `FLAG_SECURE`、系统安全页面或目标应用反自动化机制。

## 3. 当前代码基线

| 模块 | 当前职责 | Android 处理方式 |
| --- | --- | --- |
| `model_automation/models.py` | `Step`、`Preset`、`AppConfig` 及 JSON 转换 | 按相同字段移植为 Kotlin 可序列化数据类 |
| `model_automation/registry.py` | 步骤定义和字段元数据 | 移植为步骤类型注册表或密封类 |
| `model_automation/steps.py` | 五种步骤的执行逻辑和参数默认值 | 保持语义，改为挂起函数 |
| `model_automation/engine.py` | 顺序、循环、依赖、失败和停止控制 | 移植为协程执行引擎 |
| `model_automation/device.py` | 调用 `adb.exe` 截图、点击、滑动 | 完全替换为 Android 设备控制实现 |
| `model_automation/vision.py` | OpenCV 匹配、图片读写、桌面选区窗口 | 保留匹配算法，重写图片和触摸选区 UI |
| `model_automation/config.py` | 配置读写、校验和旧格式迁移 | 使用应用私有存储并保持 schema 兼容 |
| `model_automation/preset_archive.py` | ZIP 导入导出、图片打包和分辨率适配 | 使用 SAF、ZipInputStream/ZipOutputStream 和 OpenCV Android |
| `model_automation/gui.py` | Tk 界面、编辑流程、工作线程和事件队列 | 使用 Compose、ViewModel、StateFlow 和前台服务重写 |

不能直接复用的运行时依赖包括 Tkinter、Windows `adb.exe`、`subprocess.run()`、`cv2.namedWindow()`、`cv2.selectROI()` 和 Windows Python 虚拟环境。

## 4. 功能需求

### 4.1 权限和运行条件

Android 应用首次使用时必须显示权限状态页，并分别处理以下能力：

| 能力 | 推荐实现 | 必要性 |
| --- | --- | --- |
| 屏幕捕获 | `MediaProjection` + `ImageReader` | 必需 |
| 点击和滑动 | `AccessibilityService.dispatchGesture()` | 必需 |
| 长时间运行 | Foreground Service | 必需 |
| 前台服务通知 | Foreground Service 通知 | 必需 |
| 通知显示授权 | `POST_NOTIFICATIONS`（Android 13+） | 推荐；拒绝后不得阻止前台服务运行 |
| 文件导入导出 | Storage Access Framework | 必需 |
| 悬浮控制 | `TYPE_APPLICATION_OVERLAY` | 可选，首版可用通知操作替代 |
| 防止执行中休眠 | `WAKE_LOCK` | 可选，按产品策略启用 |

应用不得以“已授权”作为永久状态。每次运行前必须检查无障碍服务、屏幕捕获会话和前台服务启动条件。

目标 API 34 及以上必须声明 `mediaProjection` 前台服务类型和对应服务权限。每次新的 MediaProjection 会话都应取得新的用户授权结果，不得复用已经消费或失效的授权 token。

目标 API 34 及以上的顺序必须是：先通过 Activity 获取用户同意结果，再启动 `mediaProjection` 类型前台服务，然后调用 `getMediaProjection()` 并创建 VirtualDisplay。创建 VirtualDisplay 前必须注册 `MediaProjection.Callback`。首版只允许默认显示器全屏捕获，不使用 Android 14 的单应用窗口捕获，避免截图缺少可靠的全局手势原点。

用户拒绝 `POST_NOTIFICATIONS` 后仍可启动前台服务，但通知抽屉中的停止和捕获动作不可用。此时必须提供应用内停止入口和固定倒计时捕获流程；需要后台通知交互的功能应明确提示用户开启通知权限。

屏幕关闭、设备锁定、截图得到空帧或目标窗口设置 `FLAG_SECURE` 时，应停止或按步骤失败策略处理，不得继续盲点。

### 4.2 首页与权限状态

应用首屏应直接进入可操作的预设编排界面，不设置营销页。权限未满足时，在运行区域显示具体缺失项和对应系统设置入口。

权限状态至少包括：

- 无障碍服务未开启、已开启、服务断开。
- 屏幕捕获未授权、授权中、会话有效、会话失效。
- 通知权限状态。
- 当前截图分辨率和方向。

### 4.3 预设管理

必须支持：

- 创建空预设，名称非空且在本地配置内唯一。
- 复制预设，生成新预设 ID 和全部新步骤 ID，并同步重映射 `depends_on`。
- 重命名预设，不允许重名。
- 删除预设，但配置中必须至少保留一个预设。
- 切换当前预设，并持久化 `selected_preset_id`。
- 设置 `loop_count`；`1` 为默认值，`0` 表示无限循环。界面拒绝负数；桌面版从文件反序列化时会把负数钳制为 `0`，Android 兼容读取必须保留这一行为。
- 导出当前预设和导入预设包。

导入时若名称冲突，按当前规则生成“`原名称 导入`”、“`原名称 导入 2`”等唯一名称。

### 4.4 步骤列表

列表应显示以下信息：

| 字段 | 说明 |
| --- | --- |
| 顺序 | 从 1 开始的执行序号 |
| 状态 | 启用或停用 |
| 名称 | 用户定义的步骤名称 |
| 前置依赖 | 已关联的前置步骤名称 |
| 类型 | 步骤类型显示名称 |
| 失败处理 | 停止预设或跳到下一步 |
| 参数摘要 | 坐标、模板、连击次数等关键值 |

步骤必须支持新增、编辑、复制、启用/停用、删除、上移、下移和长按拖拽排序。

排序、删除后必须重新规范化依赖：一个步骤只能依赖当前顺序中位于它之前的步骤。移动后成为同级或后置的依赖必须删除。

### 4.5 步骤公共字段

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| `id` | String | 全局唯一；新建数据使用 32 位十六进制 UUID，兼容读取不限制历史 ID 格式 |
| `name` | String | 非空 |
| `kind` | String | 规范输出必须是已注册类型；兼容读取允许未知值，执行时按未知步骤失败 |
| `enabled` | Boolean | 默认 `true` |
| `on_failure` | String | `stop` 或 `continue` |
| `depends_on` | String[] | 编辑器规范输出只能引用同预设中更早的步骤 |
| `params` | Object | 按步骤类型定义 |
| `screen_resolution` | Object? | `{width, height}`，宽高必须大于 0 |

新增或保存步骤时必须取得当前屏幕帧，并将实际帧宽高记录到 `screen_resolution`。

编辑已有步骤且设备分辨率发生变化时，未被用户修改的坐标字段按旧分辨率自动换算；用户重新输入或通过截图选择的坐标视为当前分辨率坐标。

桌面版反序列化是宽松的：缺失 ID、名称、类型会得到默认值；除 `continue` 外的 `on_failure` 值统一转为 `stop`；加载阶段不校验步骤类型和参数。Android 应先宽松解析，再对可执行性给出校验结果，避免严格 JSON 解码导致历史文件无法导入。

桌面运行器对历史或手工修改配置执行以下兼容归一化，Android 执行层应保持一致：

| 参数 | 运行时行为 |
| --- | --- |
| `seconds`、各类 `wait_after` | 负数钳制为 `0` |
| `attempts` | 小于 `1` 时钳制为 `1` |
| `interval`、`click_interval` | 负数钳制为 `0` |
| 滑动 `duration` | 负数钳制为 `0`，Android 平台调用再将 `0` 映射为 `1ms` |
| 模板 `threshold` | 钳制到 `[0.0, 1.0]` |
| `click_count` | 小于 `1` 时步骤失败，不自动钳制 |

### 4.6 步骤类型与参数

#### 4.6.1 等待 `wait`

| 参数 | 类型 | 默认值 | 校验 |
| --- | --- | --- | --- |
| `seconds` | Float | `1.0` | 大于或等于 0 |

等待必须可被手动停止立即打断。

#### 4.6.2 坐标点击 `tap`

| 参数 | 类型 | 默认值 | 校验 |
| --- | --- | --- | --- |
| `x` | Int | `540` | 屏幕 X 坐标 |
| `y` | Int | `1000` | 屏幕 Y 坐标 |
| `wait_after` | Float | `0.0` | 大于或等于 0 |

编辑器必须支持从设备截图触摸选点。执行顺序为点击，然后执行 `wait_after`。

注意：编辑器新建默认坐标是 `(540, 1000)`，但桌面运行器在参数缺失时回退到 `(0, 0)`。Android 对桌面配置兼容执行时必须采用运行器回退值；Android 编辑器仍显示新建默认值。

#### 4.6.3 滑动 `swipe`

| 参数 | 类型 | 默认值 | 校验 |
| --- | --- | --- | --- |
| `x1` | Int | `540` | 起点 X |
| `y1` | Int | `1800` | 起点 Y |
| `x2` | Int | `540` | 终点 X |
| `y2` | Int | `800` | 终点 Y |
| `duration` | Int | `300` | 毫秒，大于或等于 0 |
| `wait_after` | Float | `0.0` | 大于或等于 0 |

编辑器必须支持在冻结截图上拖动生成起点和终点。执行顺序为滑动，然后执行 `wait_after`。

桌面运行器会把负 `duration` 和负等待时间钳制到 `0`，当前桌面编辑器未对滑动步骤的这些负值做完整拦截。Android 编辑器应直接拒绝负值，但兼容执行历史配置时应保留钳制行为。

Android Accessibility 手势不接受 0 毫秒路径。协议中的 `duration=0` 在 Android 设备适配层按 1 毫秒执行；超过平台最大手势时长的值应在运行前报告不支持，不应静默改变为完全不同的时长。

#### 4.6.4 识别模板并点击 `find_and_tap`

| 参数 | 类型 | 默认值 | 校验 |
| --- | --- | --- | --- |
| `templates` | TemplateRef[] | `[]` | 编辑器至少要求一个引用；运行时忽略无法解码的文件 |
| `attempts` | Int | `1` | 大于或等于 1 |
| `interval` | Float | `1.0` | 大于或等于 0 |
| `swipe_between` | Boolean | `false` | 是否在失败重试前滑动 |
| `x1`,`y1`,`x2`,`y2` | Int | 同滑动默认值 | 重试滑动坐标 |
| `duration` | Int | `300` | 重试滑动毫秒数 |
| `offset_x` | Int | `0` | 匹配中心 X 偏移，可为负数 |
| `offset_y` | Int | `0` | 匹配中心 Y 偏移，可为负数 |
| `wait_after` | Float | `0.0` | 点击后等待 |

#### 4.6.5 识别模板并连击 `find_and_multi_tap`

包含 `find_and_tap` 的全部参数，并增加：

| 参数 | 类型 | 默认值 | 校验 |
| --- | --- | --- | --- |
| `click_count` | Int | `2` | 大于或等于 1 |
| `click_interval` | Float | `0.1` | 大于或等于 0 |

同一次识别得到目标坐标后，在该坐标执行 `click_count` 次点击；相邻点击之间等待 `click_interval`。

### 4.7 模板引用

模板引用结构如下：

```json
{
  "file": "button.png",
  "threshold": 0.8,
  "screen_resolution": {
    "width": 1080,
    "height": 2400
  }
}
```

`threshold` 的有效范围为 `0.0` 至 `1.0`。`screen_resolution` 表示模板截图时的完整屏幕分辨率，不是模板图片自身尺寸。旧配置缺少该字段时，使用所属步骤的 `screen_resolution` 作为回退值。

支持的图片格式为 PNG、JPG、JPEG 和 BMP。Android 版本应保留 Windows 文件名兼容限制，确保导出的包可被桌面版重新导入。

### 4.8 模板匹配规则

匹配过程必须与当前实现保持一致：

1. 将屏幕和模板转换为灰度图。
2. 使用 `TM_CCOEFF_NORMED` 执行模板匹配。
3. 排除低于模板阈值的结果。
4. 使用以模板宽高为核的局部极大值提取独立候选。
5. Android 输入图像必须先归一化为与桌面一致的 BGR 或灰度通道；Bitmap 常见的 RGBA 数据不能直接使用 `COLOR_BGR2GRAY`。
6. 单模板内按候选中心 `(y, x)` 选择，Y 更小优先，Y 相同时 X 更小优先。
7. 多模板同时命中时再次按 `(y, x, template_index)` 选择。
8. 目标坐标为匹配区域中心加 `offset_x/offset_y`。
9. 偏移后坐标超出当前屏幕范围时，本次步骤失败且不点击。

因此彼此独立的多个目标存在时，点击顺序规则是从上到下；并排目标从左到右。同一连通的局部极大值区域内部由 `minMaxLoc` 先取最高相似度位置，空间优先级应用于这些独立候选之间。

### 4.9 识别重试流程

每次尝试必须重新截取当前屏幕。若任一模板匹配成功，立即执行点击或连击并结束步骤。

未匹配且仍有剩余次数时：

1. 记录当前尝试失败日志。
2. `swipe_between=true` 时执行配置的重试滑动。
3. 可中断地等待 `interval`。
4. 进入下一次截图和识别。

全部尝试结束仍未匹配时，返回失败“尝试 N 次后仍未识别到目标”。

### 4.10 前置依赖与失败控制

执行每轮预设时，步骤状态必须重新计算，不得沿用上一轮状态。

以下情况使步骤在本轮被视为未执行：

- 步骤被停用。
- 步骤失败且 `on_failure=continue`。
- 步骤因任一前置依赖未执行而跳过。
- 依赖 ID 不存在。

一个步骤的任一 `depends_on` 项处于未执行状态时，该步骤自动跳过，并继续传播到依赖它的后续步骤。

桌面配置加载器只校验 ID 唯一性，不校验依赖是否存在或是否位于前面。未知依赖会被运行器视为未执行；手工构造的“依赖已知后置步骤”可能提前执行。Android 应在编辑、导入和运行前统一规范化或拒绝后置依赖。这是对异常输入的有意加固，不改变桌面界面正常生成的数据。

失败行为：

| `on_failure` | 行为 |
| --- | --- |
| `stop` | 立即终止整个预设 |
| `continue` | 标记当前步骤失败并继续，依赖它的步骤自动跳过 |

当前界面只允许可能失败的识别步骤配置 `continue`，其余步骤使用 `stop`。Android 版本应保持该编辑器限制。

### 4.11 循环与停止

- `loop_count > 0`：完整执行指定轮数。
- `loop_count = 0`：无限循环，直到未处理失败或用户停止。
- 无限循环且没有启用步骤时必须立即失败，禁止空转。
- 当前桌面版在无限循环且“存在启用步骤但所有步骤都因依赖被跳过”时可能形成无等待空循环。Android 只对无限循环增加无进展检测，并以“本轮没有可执行步骤”失败；有限循环继续按桌面语义完成指定轮数，即使某轮全部跳过。
- 每轮开始时重置跳过和失败状态。
- 桌面版可中断等待并在步骤边界检查停止，但不能撤销已经发出的 ADB 命令。Android 必须在每次截图、点击和滑动前再次检查协程取消状态；已经提交给系统的单次手势只允许等待返回。
- 运行使用整次任务的预设深拷贝；运行期间编辑数据不得影响该次运行的任何后续轮次。

### 4.12 模板资源管理

必须支持：

- 从当前手机屏幕捕获完整帧并框选区域保存为模板。
- 通过系统文件选择器导入图片。
- 对已有模板重新截图。
- 删除模板，并提示引用该模板的步骤将无法识别。
- 显示模板名称、尺寸或文件大小。

同机捕获建议采用以下流程：

1. 应用确认 MediaProjection 会话有效。
2. 应用进入后台或提示用户切换到目标应用。
3. 通过通知操作或可选悬浮控件触发截图。
4. 将冻结截图带回应用内裁剪界面。
5. 用户框选、命名、确认阈值并保存。

模板裁剪坐标必须基于原始截图像素。界面缩放仅影响显示，不得改变持久化坐标。

当前桌面版从资源页重新截取模板时会覆盖图片，但不会同步更新已存在模板引用中的 `screen_resolution`；在步骤中添加没有元数据的已有图片时，则会在保存步骤时把当前设备分辨率写入引用。Android 不应复制前一种不一致行为：重新截取后必须更新所有引用该文件的分辨率，或者创建新文件并只改写当前引用。该策略需要在实现前固定并增加兼容测试。

### 4.13 运行界面与日志

运行界面至少提供：

- 当前预设名称、当前轮次、当前步骤和步骤总数。
- 运行、停止按钮。
- 前台服务持续通知；通知权限允许时提供停止动作，权限被拒绝时通过应用内入口停止。
- 按时间顺序追加的运行日志。
- 完成、失败、手动停止三种最终状态。

Android 应用启动执行后需要离开自身界面才能操作目标应用。首版建议使用短倒计时并将任务切到后台，由用户切回目标应用；通知权限允许时可通过通知停止，否则用户返回应用内停止。悬浮控制作为后续增强项。

## 5. 数据协议

### 5.1 应用配置

配置 schema 版本保持为 2。完整结构示例：

```json
{
  "version": 2,
  "selected_preset_id": "preset-id",
  "presets": [
    {
      "id": "preset-id",
      "name": "示例预设",
      "loop_count": 1,
      "steps": [
        {
          "id": "step-id",
          "name": "识别并点击",
          "kind": "find_and_tap",
          "enabled": true,
          "on_failure": "continue",
          "depends_on": [],
          "screen_resolution": {
            "width": 1080,
            "height": 2400
          },
          "params": {
            "templates": [
              {
                "file": "button.png",
                "threshold": 0.8,
                "screen_resolution": {
                  "width": 1080,
                  "height": 2400
                }
              }
            ],
            "attempts": 3,
            "interval": 1.0,
            "swipe_between": false,
            "x1": 540,
            "y1": 1800,
            "x2": 540,
            "y2": 800,
            "duration": 300,
            "offset_x": 0,
            "offset_y": 0,
            "wait_after": 0.0
          }
        }
      ]
    }
  ]
}
```

校验要求：

- 至少存在一个预设。
- 预设 ID 唯一。
- 预设名称唯一。
- 步骤 ID 在整个配置内全局唯一。
- `selected_preset_id` 无效时回退到第一个预设。
- 配置写入使用 UTF-8 和临时文件原子替换。

以上唯一性是桌面版加载阶段实际执行的结构校验。步骤种类、参数范围及依赖顺序属于编辑器和运行阶段规则，不是当前 schema 2 加载器的强校验项。Android 不得因为缺少可选字段而拒绝桌面版能够读取的历史配置。

旧版 `{support_pos, start_pos}` 配置必须继续迁移为默认刷本预设。未来提高 schema 版本时必须建立明确的 `v1 -> v2 -> vN` 迁移链，不能把所有低版本都当作旧坐标格式。

### 5.2 预设包

文件建议扩展名为 `.adb-preset.zip`，内部结构：

```text
manifest.json
assets/button.png
assets/other.jpg
```

`manifest.json`：

```json
{
  "archive_version": 1,
  "preset": {},
  "assets": [
    {
      "name": "button.png",
      "path": "assets/button.png",
      "sha256": "..."
    }
  ]
}
```

导出要求：

- 只打包当前预设引用的模板，同一文件只打包一次。
- 任一模板缺失时整体失败，不生成不完整包。
- 含坐标或模板的步骤缺少 `screen_resolution` 时整体失败。
- 包含未知步骤类型时整体失败。
- 使用临时文件创建 ZIP，完成后原子替换目标文件。

通过 SAF 导出时，应先在应用私有 staging 中完整生成并验证 ZIP，再复制到目标 URI。普通文档提供方不保证目标 URI 支持原子替换，因此“原子替换”只适用于应用私有文件或明确支持该能力的提供方；外部复制中断时必须报告失败。

Android 导入安全要求：

- 禁止 `extractAll`；按清单逐项读取。
- 拒绝重复 ZIP 成员；清单声明的资源必须拒绝路径穿越、绝对路径和非法文件名。
- 单成员解压后最大 50 MiB。
- 全包解压后最大 200 MiB。
- ZIP 成员最多 1000 个。
- 清单中的每个图片必须校验 SHA-256。
- 被预设引用的图片必须可以被 OpenCV 解码。
- 导入完成前不得修改现有预设。

桌面版从不直接解压 ZIP，因此未在清单声明的路径穿越成员会被安全忽略，而不是因名称被拒绝。Android 可以进一步拒绝这类未声明成员，但应将其视为安全加固，不是 archive version 1 的兼容性必要条件。

导入 ID 规则：

- 生成新的预设 ID。
- 为每个步骤生成新 ID。
- 使用完整映射重写 `depends_on`。
- 拒绝缺失、跨预设或指向后置步骤的依赖。

模板冲突规则：

- 文件名按不区分大小写比较。
- 同名且字节内容相同则复用现有文件。
- 同名但内容不同时生成 `_imported`、`_imported_2` 等新名称。
- 不得覆盖内容不同的现有模板。
- 发生缩放时，内容比较使用缩放并重新编码后的字节；比例为 `1.0` 时先验证图片可解码，再直接比较原始编码字节。
- 同一源文件被不同源分辨率的步骤引用时，导入可生成多个缩放变体，并分别改写引用文件名。

### 5.3 分辨率适配

定义：

```text
scaleX = targetWidth / sourceWidth
scaleY = targetHeight / sourceHeight
```

坐标换算：

```text
targetX = round(sourceX * scaleX)
targetY = round(sourceY * scaleY)
```

为与 Python 当前行为完全一致，`round` 必须使用“正好位于两个整数中间时取偶数”的 ties-to-even 规则。Kotlin `roundToInt()` 的中点规则不同，不能直接用于协议兼容换算。

绝对坐标换算后限制到 `[0, width - 1]` 或 `[0, height - 1]`。`offset_x`、`offset_y` 是有符号偏移量，只缩放，不限制正负范围。

不缩放时间、次数、阈值、布尔值和步骤 ID。

模板图片按其引用中的 `screen_resolution` 计算 X/Y 比例。任一轴缩小时，两个轴统一使用区域插值；仅当两个轴都不缩小时使用三次插值。图片宽高也使用 ties-to-even 取整并保证至少 1 像素。导入完成后步骤和模板引用的分辨率都更新为目标屏幕分辨率。

## 6. Android 目标架构

### 6.1 推荐分层

```text
app/
  ui/                 Compose 页面、导航、裁剪和选点
  presentation/       ViewModel、StateFlow、UI 状态
  domain/model/       AppConfig、Preset、Step、TemplateRef
  domain/engine/      StepEngine、StepRunner、执行报告
  automation/         Accessibility 控制、MediaProjection 截图
  vision/             OpenCV 模板加载、匹配、缩放
  data/config/        配置仓库、迁移和原子保存
  data/archive/       预设 ZIP 导入导出
  service/            AutomationForegroundService
```

### 6.2 核心接口

```kotlin
interface DeviceController {
    suspend fun captureScreen(): ScreenFrame
    suspend fun tap(x: Int, y: Int)
    suspend fun swipe(
        x1: Int,
        y1: Int,
        x2: Int,
        y2: Int,
        durationMs: Long,
    )
}

data class ScreenFrame(
    val width: Int,
    val height: Int,
    val rotation: Int,
    val bitmap: Bitmap,
    val capturedAtMs: Long,
)

interface ConfigRepository {
    suspend fun load(): AppConfig
    suspend fun save(config: AppConfig)
}

interface PresetArchiveRepository {
    suspend fun exportPreset(presetId: String, destination: Uri)
    suspend fun importPreset(source: Uri, targetResolution: Resolution): Preset
}
```

执行引擎不得直接依赖 Activity、Compose、AccessibilityService 或 MediaProjection。平台调用只能经由接口注入，以便单元测试使用 FakeDeviceController。

`tap()` 和 `swipe()` 必须将 `dispatchGesture()` 的接收结果与 `GestureResultCallback` 封装为挂起调用：系统拒绝提交时立即失败，提交成功后等待 `onCompleted` 或 `onCancelled` 才返回。后续 `wait_after` 和步骤不得在手势实际完成前开始。

`ScreenFrame.bitmap` 必须已经归一化到 Accessibility 手势坐标空间，且 `width/height` 与可提交给 `dispatchGesture()` 的坐标范围一致。MediaProjection 虚拟显示尺寸、物理屏幕、系统栏、旋转和 letterbox 可能导致截图像素与手势坐标不同，设备适配层必须维护 capture-to-gesture 变换矩阵。不得直接假设 MediaProjection Bitmap 尺寸就是点击坐标尺寸。

步骤和模板的 `screen_resolution` 记录归一化后的手势坐标空间。模板识别在归一化 Bitmap 上进行，从而保证匹配中心可以直接用于手势；如设备适配层无法生成归一化 Bitmap，则 `ScreenFrame` 必须携带显式变换矩阵，并在持久化和点击前完成双向换算。

### 6.3 线程与协程

- Compose 和 Activity 操作只在主线程执行。
- 截图、OpenCV、ZIP 和磁盘操作在 `Dispatchers.Default/IO` 执行。
- 每次运行创建独立 `CoroutineScope` 和 `Job`。
- 手动停止调用 `Job.cancel()`，所有等待使用可取消的 `delay()`。
- 每个截图、点击和滑动平台调用前调用 `ensureActive()`。
- OpenCV `Mat`、ImageReader Image 和 Bitmap 中间对象必须及时释放或复用。
- UI 通过 `StateFlow<AutomationState>` 和事件流接收状态，不直接轮询服务。

### 6.4 前台服务状态机

```text
Idle
  -> CheckingPermissions
  -> StartingCapture
  -> Countdown
  -> Running(cycle, step)
  -> Completed | Failed | Stopped
  -> Idle
```

状态约束：

- 同一时间只允许一个运行任务。
- `Running` 前冻结预设快照。
- 服务被系统重建时不得默认恢复点击，应回到安全停止状态。
- MediaProjection 会话失效时立即停止并报告原因。
- 必须始终存在可到达的停止路径；通知权限允许时使用通知动作，否则使用应用内停止入口。

## 7. Android 页面与交互

| 页面 | 核心内容 |
| --- | --- |
| 预设编排 | 预设切换、循环次数、步骤列表、运行和停止 |
| 步骤编辑 | 公共字段、动态参数、前置依赖、截图选点 |
| 模板资源 | 图片列表、导入、捕获、重新截取和删除 |
| 截图编辑 | 冻结截图、缩放、平移、框选、点选和滑动轨迹 |
| 导入预览 | 包信息、源/目标分辨率、缩放提示、冲突结果 |
| 运行日志 | 当前状态、轮次、步骤和可滚动日志 |
| 权限状态 | 无障碍、屏幕捕获、通知和系统限制 |

手机界面不应照搬桌面表格。步骤列表使用紧凑列表项展示名称、状态、类型和摘要；常用操作通过图标和长按菜单提供，拖拽手柄用于排序。

截图编辑器必须固定截图宽高比，支持双指缩放和平移。点选、框选和滑动坐标必须根据实际显示区域反算到归一化后的 `ScreenFrame` 手势坐标；状态栏、导航栏、裁切和旋转不能产生固定偏移。

## 8. 平台替换映射

| Windows 实现 | Android 替换 |
| --- | --- |
| `adb exec-out screencap -p` | MediaProjection/ImageReader |
| `adb shell input tap` | Accessibility `dispatchGesture` 单点路径 |
| `adb shell input swipe` | Accessibility `dispatchGesture` 连续路径 |
| Tk `Toplevel` | Compose Dialog 或独立页面 |
| Tk `Treeview` | LazyColumn + 拖拽排序 |
| `cv2.selectROI` | Compose Canvas 触摸框选 |
| `cv2.namedWindow` | Compose 图片编辑器 |
| `threading.Thread` | Kotlin Coroutines |
| `threading.Event` | Coroutine Job/CancellationException |
| `Queue` + 100ms 轮询 | StateFlow/SharedFlow |
| 项目目录配置文件 | 应用私有 filesDir |
| Tk 文件对话框 | Storage Access Framework |

不建议在 APK 内捆绑 Android 版 ADB 客户端并连接本机无线调试。该方案依赖开发者选项、配对和端口状态，无法作为稳定的普通用户运行模型。

## 9. 存储设计

建议应用私有目录：

```text
files/
  config/fgo_config.json
  templates/<filename>
  imports/staging/
cache/
  captures/
  archive-staging/
```

要求：

- 配置和模板默认不请求广泛存储权限。
- 导入导出只使用用户通过 SAF 授权的 URI。
- 临时截图放入缓存目录并可定期清理。
- 导入先写 staging，全部验证成功后再提交配置和模板。
- 配置写入必须使用临时文件和原子替换。
- 卸载应用会删除私有数据，应通过导出预设提供备份能力。

## 10. 性能目标

| 指标 | 目标 |
| --- | --- |
| 普通编辑操作响应 | 100 ms 内反馈 |
| 停止请求反馈 | 100 ms 内更新 UI，当前系统调用结束后停止 |
| 1080p 单模板匹配 | 中端设备建议小于 300 ms |
| 配置保存 | 小于 500 ms |
| 运行内存 | 避免同时保留多个全分辨率 Bitmap/Mat |
| 日志保留 | 内存中限制条数，完整日志按需落盘 |

识别步骤执行前应加载并缓存本步骤模板，重试时只更新屏幕帧。屏幕和模板应只转换一次灰度格式。运行结束必须释放模板 Mat 缓存。

## 11. 安全与合规

- 明确说明无障碍服务仅用于用户创建的本机自动化操作。
- 不采集、不上传屏幕内容；如未来增加上传，必须另行设计授权和隐私策略。
- 日志默认不保存截图和模板像素。
- 禁止自动操作系统权限确认、支付、密码和锁屏界面。
- Google Play 发布前必须单独评估 Accessibility API 政策；企业分发或用户侧载也应保留用途说明。
- 对目标应用的服务条款、反作弊和自动化限制不作技术绕过。

## 12. 测试计划

### 12.1 可迁移单元测试

- 配置默认值、schema 2 读写和旧格式迁移。
- 预设、步骤、分辨率和依赖序列化。
- 有限循环、无限循环、停止、失败继续和依赖传播。
- 五种步骤的参数校验和执行顺序。
- 多目标从上到下、同排从左到右选择。
- 多模板跨模板空间排序。
- 坐标、偏移和模板图片分辨率缩放。
- ZIP 哈希、路径、大小、重复成员和缺图校验。
- 导入时 ID 和依赖重映射、同名模板冲突处理。
- 步骤排序及无效前置依赖清理。

### 12.2 Android 单元测试

- ViewModel 状态转换。
- 权限状态组合。
- Coroutine 取消和可中断等待。
- 配置仓库原子提交及失败回滚。
- URI 输入输出和 ZIP staging。
- 屏幕旋转前后坐标映射。

### 12.3 仪器测试与真机测试

- 无障碍点击和不同持续时间滑动。
- MediaProjection 首次授权、拒绝、撤销和会话失效。
- 应用退到后台后持续识别目标应用。
- 通知停止动作。
- Android 11、12、13、14 及至少两个厂商系统。
- 720p、1080p、1440p 和横竖屏切换。
- 导入桌面版预设，在 Android 执行后重新导出并由桌面版读取。
- 目标不存在、模板损坏、屏幕关闭、锁屏和安全窗口。
- 30 分钟以上循环运行的内存、温度和电量表现。

## 13. 验收标准

| 编号 | 验收项 |
| --- | --- |
| A-01 | 无电脑、无 USB 连接时可在同一 Android 设备执行预设 |
| A-02 | 五种步骤行为及默认值与桌面版一致 |
| A-03 | 失败控制、依赖传播、循环和停止语义一致 |
| A-04 | 多目标点击遵循从上到下、从左到右 |
| A-05 | 可在目标应用画面上完成截图、框选、点选和滑动选择 |
| A-06 | Android 与桌面版可互相导入对方导出的预设包 |
| A-07 | 不同分辨率导入后坐标和模板按 X/Y 比例适配 |
| A-08 | 同名不同内容模板不会覆盖现有文件 |
| A-09 | 运行中可通过应用界面或通知停止 |
| A-10 | 权限被拒绝或失效时不执行盲目点击，并显示明确原因 |
| A-11 | 旋转、后台、Activity 重建不会启动重复任务 |
| A-12 | 自动化核心和数据层单元测试通过，关键流程真机测试通过 |

## 14. 建议实施阶段

### 阶段 0：权限与设备控制验证

目标是证明目标设备可以在目标应用前台时持续截图、点击和滑动。

交付物包括 MediaProjection 截图、Accessibility 手势、前台服务、通知停止和一组真机兼容性结果。未完成该阶段前不开始完整 UI。

### 阶段 1：数据与执行核心

移植模型、配置迁移、步骤注册、执行引擎、依赖、循环、停止和日志事件。建立 FakeDeviceController 单元测试。

### 阶段 2：视觉与截图编辑

接入 OpenCV Android SDK，实现模板加载、空间优先匹配、图片缩放和截图点选/框选/滑动编辑。

### 阶段 3：预设和步骤界面

完成预设管理、动态步骤编辑器、依赖选择、步骤拖拽、模板资源和运行状态页面。

### 阶段 4：导入导出与桌面兼容

实现 SAF、ZIP 安全校验、分辨率适配、模板冲突处理和桌面/Android 双向兼容测试。

### 阶段 5：稳定性与发布准备

处理后台限制、权限恢复、旋转、厂商省电策略、长时间运行、性能、隐私说明和分发方式。

## 15. 开发前必须确认的产品决策

1. 应用只供个人侧载、企业分发，还是计划上架 Google Play。
2. 是否只支持无 Root 设备；推荐默认无 Root，不依赖 Shizuku。
3. 最低 Android 版本是否可设为 Android 11。
4. 是否需要悬浮窗捕获和停止；首版可用通知与倒计时替代。
5. 是否需要自动启动指定目标应用；当前预设协议没有目标包名字段。
6. 屏幕关闭或锁屏时是立即失败，还是暂停并等待解锁。
7. 是否要求横屏和折叠屏首版可用。
8. 是否保留配置文件名和中文错误文本的完全一致性，还是只保证数据协议兼容。

## 16. 主要风险

| 风险 | 影响 | 应对 |
| --- | --- | --- |
| MediaProjection 授权和版本差异 | 截图会话无法持续 | 阶段 0 覆盖 Android 11-14 真机 |
| 厂商后台清理 | 无限循环被系统终止 | 前台服务、通知、厂商设置引导 |
| 无障碍服务断开 | 点击和滑动失败 | 每步前检查，失败时安全停止 |
| 目标应用安全窗口 | 截图黑屏 | 检测空帧并报告不支持 |
| OpenCV 全屏匹配耗电 | 发热、耗电、掉帧 | 模板缓存、灰度缓存、性能基准和频率控制 |
| 同机编辑与目标应用切换 | 截错应用画面 | 冻结截图工作流、倒计时或悬浮触发 |
| Android 与桌面协议漂移 | 无法交换预设 | 固化 schema/archive 测试向量和双向测试 |
| Play 无障碍政策 | 无法上架 | 开发前确认分发方式和政策路径 |

## 17. 完成定义

满足以下条件才视为移植完成：

- 所有第 13 节验收项通过。
- Android 数据协议与当前 schema 2、archive version 1 兼容。
- 自动化核心具备与当前 Python 测试等价的 Kotlin 单元测试。
- 至少完成 Android 11、13、14 三个版本的真机验证。
- 连续运行 30 分钟无明显内存增长、重复任务或无法停止的问题。
- 权限拒绝、截图中断和无障碍断开均安全失败，不产生不可控点击。
- Android 导出的预设包可由当前桌面版成功导入，桌面版导出的包可由 Android 成功导入。
