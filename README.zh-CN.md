# ADB 自动化工作台

一款面向 Windows 的 Android 设备自动化工具。程序通过 ADB 获取设备截图并发送触控操作，使用 OpenCV 将屏幕内容与模板图片进行匹配。你可以在浏览器中通过可视化画布编排工作流，并按顺序、按循环执行预设。

[English documentation](README.md) · [优化记录与验证范围](docs/optimization-summary.md)

## 项目功能

- 可视化工作流画布：拖放节点、连接步骤、分组及自动布局。
- 图像识别：支持设置相似度阈值、重试次数、多模板匹配、限制搜索区域，以及失败后继续执行。模板解码和灰度结果有界缓存，同一次截图的灰度结果可供多个模板复用。
- 触控操作：坐标点击、连击、滑动、等待、执行其他预设和循环控制。
- 截图选点与框选：可在设备截图上选取模板区域、点击坐标和滑动轨迹；界面缩放预览时，保存的仍是设备原始分辨率坐标。
- 实时显示运行状态、节点结果、执行日志和设备连接情况。执行引擎通过结构化事件报告状态，刷新页面或断线重连后可恢复当前节点结果，重播日志会去重。
- 低延迟 H.264 手机投屏：支持 WebCodecs 的浏览器直接解码压缩视频，只有兼容 JPEG 客户端订阅时后端才解码转码；浏览器不支持或解码失败时自动回退 JPEG。浮动窗口中的手机画面最高约 30 FPS，可自由移动、调整大小和隐藏；窗口位置与尺寸会被记住，隐藏或页面进入后台时自动停止视频流。
- 配置和模板图片保存在程序目录附近，便于备份和迁移。

## 环境要求

从源码运行需要：

- Windows 10 或更高版本。
- Python 3.12。
- Node.js 和 npm（仅在构建或开发前端时需要）。
- 已开启 USB 调试并授权当前电脑的 Android 设备。

仓库根目录提供 `adb.exe` 及其 Windows 运行库。程序会优先使用仓库内的 ADB；找不到时才尝试使用系统 `PATH` 中的 `adb`。部分设备还需要安装厂商提供的 Windows USB 驱动。

实时投屏使用仓库内置的 [scrcpy](https://github.com/Genymobile/scrcpy) 服务端（`vendor/scrcpy-server-v5.0.1`，Apache License 2.0），并通过 PyAV 在本地解码 H.264，无需另行安装 scrcpy。来源与校验值见 `vendor/README.md`。

## 从源码部署与启动

请在 Windows PowerShell 或命令提示符中，从仓库根目录执行以下命令。

### 1. 创建 Python 环境并安装后端依赖

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 2. 安装依赖并构建网页前端

首次部署或修改前端后需要构建前端：

```powershell
cd web
npm install
npm run build
cd ..
```

### 3. 连接设备并启动

在手机上开启 USB 调试，连接电脑，并在手机提示时确认 USB 调试授权。然后在仓库根目录启动：

```powershell
.venv\Scripts\python.exe main.py
```

服务默认监听 `http://127.0.0.1:8001`，并自动打开浏览器。指定端口或关闭自动打开浏览器：

```powershell
.venv\Scripts\python.exe main.py --port 8080 --no-browser
```

随后手动访问 `http://127.0.0.1:8080`。服务默认仅监听本机，适合本地使用。

### 前端开发模式

在第一个终端从仓库根目录启动后端：

```powershell
.venv\Scripts\python.exe main.py --port 8000 --no-browser
```

然后在第二个终端启动 Vite：

```powershell
cd web
npm run dev
```

使用 Vite 终端中显示的本地地址访问。开发代理会将 API 和 WebSocket 请求转发到 `http://127.0.0.1:8000`。按 `Ctrl+C` 可分别停止前后端进程。

## 使用教程

1. **连接设备。** 手机通过 USB 连接电脑，开启 USB 调试并接受授权，在工作台顶部点击“检查设备”。
2. **选择预设。** 选择已有预设，或创建一个新预设作为工作流。
3. **添加节点。** 点击左侧步骤卡片，或将步骤拖到画布。搜索支持“找图”“延时”等用途词；空画布也提供常用步骤入口。新节点会出现在当前视口中，右侧自动展开参数面板。
4. **配置图像识别。** 添加模板图片并设置相似度阈值；按需设置重试次数和间隔。启用“限定搜索区域”后，可在截图中框选搜索范围，也可填写原始设备像素坐标及宽高；区域必须完整位于屏幕内。默认关闭时搜索全屏。识别步骤失败时，可以设置为停止预设或跳到下一步。
5. **选取坐标或模板。** 打开截图选择器，可框选识别模板区域、点选坐标或拖动设置滑动轨迹。截图显示尺寸即使缩小，保存的坐标仍对应设备原始像素。
6. **设置步骤依赖。** 在画布上连接步骤，表示后续步骤依赖前置步骤。若前置步骤被停用、跳过，或失败后选择继续执行，依赖它的步骤会在本轮跳过。
7. **设置循环次数。** `1` 表示运行一轮；`0` 表示持续循环，直到出现未继续处理的失败或用户手动停止。
8. **运行并查看结果。** 点击“运行”启动预设；需要中止时点击停止。顶部状态栏显示当前步骤、保存状态和服务连接情况，可一键定位运行或失败步骤。运行中仍可选择节点查看参数和结果，编辑会锁定。日志面板支持定位步骤和回到最新日志；查看旧日志时保持阅读位置。画布工具栏提供缩放、适应视图、交互锁定和布局操作。
9. **监控手机画面。** 点击顶部工具栏的手机图标打开浮动实时投屏，画面通过低延迟 H.264 视频流传输，最高约 30 FPS。拖动标题栏移动窗口，拖动右下角调整大小，点击眼睛图标隐藏；再次点击手机图标即可重新显示。隐藏窗口或页面进入后台时视频流会自动停止，窗口会记住上次的位置和尺寸。

常用步骤包括：图像识别并点击、图像识别后连击、坐标点击、滑动、等待、执行其他预设和循环控制。识别参数按目标、成功后动作、重试和高级偏移分组；非法数字会在字段旁提示，不会写入流程。删除步骤后可用 Ctrl+Z 撤销；右上角“使用帮助”或 F1 可查看连线含义和快捷键。拖动节点只改变位置，不改变执行顺序。

## 配置与数据备份

首次运行时，程序会在仓库根目录创建 `config.json` 和 `templates_file/`。打包版本则在可执行文件所在目录创建这些数据。更换或升级程序前，请备份这两项。不要将打包版放在 `C:\Program Files` 等受限目录，因为程序需要在数据目录写入文件。

配置加载器会自动迁移受支持的旧格式配置。手动编辑配置前建议先备份。

## 打包为 Windows 分发版

PyInstaller 配置会生成包含 Python 运行时、网页静态资源、ADB 和相关 DLL 的单目录程序。请在 Windows 上完成构建。

### 1. 安装构建依赖并生成网页资源

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller
cd web
npm install
npm run build
cd ..
```

### 2. 执行打包

```powershell
.venv\Scripts\pyinstaller.exe --noconfirm ADB-Automation.spec
```

可执行文件生成在 `dist\ADB-Automation\ADB-Automation.exe`。分发时必须复制整个 `dist\ADB-Automation\` 文件夹，不能只复制 EXE。目标电脑无需安装 Python 或 Node.js，但可能仍需安装 Android 设备对应的 USB 驱动。

如需查看打包版启动日志，可从终端运行 EXE。可通过 `--port PORT` 更换端口，通过 `--no-browser` 关闭自动打开浏览器。

## 无线连接手机

点击顶部 Wi-Fi 图标“无线连接与设备管理”。手机和运行本程序的电脑需要处于同一局域网；ADB 命令从后端电脑发出。

- **手机有无线调试配对页面：** 开启“开发者选项 → 无线调试”，首次连接在“配对”页填写手机 IP、配对弹窗中的端口和六位码。配对成功后切回“连接”，填写无线调试主页面显示的连接端口。配对端口与连接端口通常不同。
- **手机只有无线调试开关，或 5555 拒绝连接：** 先用 USB 连接电脑并在手机上允许 USB 调试授权。在“连接”页展开“只有无线调试开关？先通过 USB 启用”，点击“通过 USB 开启无线 ADB”，再手动连接手机 IP 的 `5555` 端口。无线连接成功后可拔下 USB。
- **管理设备：** 列表可刷新、选择当前设备或断开指定无线设备。选定后，截图、工作流与实时投屏使用同一个设备；断开后不会自动切换到另一台手机。运行流程期间只能查看和刷新，停止后才能改设备。

连接面板仅在浏览器本地记住成功连接的 IP 和端口，不保存配对码、不自动连接。后端重启后可在列表重新选择设备；手机重启、关闭无线调试或更换网络后可能需要重新启用或配对。IPv4/IPv6 地址均可用，端口范围为 1–65535。

红魔等只有开关的系统可优先尝试 USB 启用方式。如果已授权 USB 仍无法开启，需检查系统是否限制 ADB TCP/IP，或电脑与手机之间是否启用了 AP 隔离。不要把 ADB 端口映射到公网。

## 常见问题

- **浏览器无法连接：** 确认后端已经运行，访问启动命令指定的端口，并检查端口是否已被其他程序占用。
- **无法检测到设备：** 检查 USB 调试开关、手机上的授权提示和 Windows USB 驱动，并确认 ADB 能检测到设备。
- **打包版页面缺失或未更新：** 重新在 `web/` 目录执行 `npm run build`，再重新打包。
- **模板识别不到：** 确认模板对应当前设备画面，并检查相似度阈值和重试设置。
- **配置无法保存：** 将程序移动到当前用户有写入权限的目录。

## 测试与检查

在仓库根目录运行：

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q main.py model_automation web_server tests
cd web
npm test
npm run build
```

浏览器验收使用独立的假设备和临时配置。在一个终端从仓库根目录启动测试服务：

```powershell
.venv\Scripts\python.exe -m uvicorn tests.e2e_web_app:app --host 127.0.0.1 --port 8002
```

另一个终端进入 `web`，执行：

```powershell
$env:PLAYWRIGHT_BASE_URL = 'http://127.0.0.1:8002'
npm run test:e2e
npm run test:usability
npm run test:wireless
npm run test:performance
npm run test:runtime
npm run test:runtime-performance
npm run test:stream
```

需要已安装 Playwright Chromium，或设置 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 指向本机 Edge/Chrome。功能验收会修改测试服务的临时预设，因此不要指向日常使用的服务。性能脚本在浏览器中注入 100/500 节点配置，拦截配置写入请求，检查小窗口控件可达性、连接线稳定性、预设切换、缩放及拖动，并输出 JSON 测量结果。结果受电脑和浏览器负载影响，下一帧回调时间不等同于稳定帧率。`test:runtime-performance` 在浏览器内注入运行事件和日志，检查大流程增量更新、满容量日志跟随、历史阅读位置、折叠面板开销和最终状态；`test:runtime` 验证运行期间刷新和 WebSocket 重连后的状态恢复；`test:stream` 用本地 PyAV 生成 H.264 并在浏览器解码，验证分包、分辨率变化和停止释放，无需设备或测试服务（需要仓库 Python 环境及支持 WebCodecs 的浏览器）。

设备触控和截图选取需要连接并授权 Android 设备，单元测试无法覆盖实际设备操作。
