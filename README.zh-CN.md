# ADB 自动化工作台

一款面向 Windows 的 Android 设备自动化工具。程序通过 ADB 获取设备截图并发送触控操作，使用 OpenCV 将屏幕内容与模板图片进行匹配。你可以在浏览器中通过可视化画布编排工作流，并按顺序、按循环执行预设。

[English documentation](README.md)

## 项目功能

- 可视化工作流画布：拖放节点、连接步骤、分组及自动布局。
- 图像识别：支持设置相似度阈值、重试次数、多模板匹配，以及失败后继续执行。
- 触控操作：坐标点击、连击、滑动、等待、执行其他预设和循环控制。
- 截图选点与框选：可在设备截图上选取模板区域、点击坐标和滑动轨迹；界面缩放预览时，保存的仍是设备原始分辨率坐标。
- 实时显示运行状态、节点结果、执行日志和设备连接情况。
- 低延迟 H.264 手机投屏：浮动窗口中的手机画面最高约 30 FPS，可自由移动、调整大小和隐藏；窗口位置与尺寸会被记住，隐藏或页面进入后台时自动停止视频流。
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
3. **添加节点。** 从左侧步骤库将步骤拖到画布，或双击步骤添加。选择画布节点后，可在右侧属性面板编辑参数。
4. **配置图像识别。** 添加模板图片并设置相似度阈值；按需设置重试次数和间隔。识别步骤失败时，可以设置为停止预设或跳到下一步。
5. **选取坐标或模板。** 打开截图选择器，可框选识别模板区域、点选坐标或拖动设置滑动轨迹。截图显示尺寸即使缩小，保存的坐标仍对应设备原始像素。
6. **设置步骤依赖。** 在画布上连接步骤，表示后续步骤依赖前置步骤。若前置步骤被停用、跳过，或失败后选择继续执行，依赖它的步骤会在本轮跳过。
7. **设置循环次数。** `1` 表示运行一轮；`0` 表示持续循环，直到出现未继续处理的失败或用户手动停止。
8. **运行并查看结果。** 点击“运行”启动预设；需要中止时点击停止。可从节点状态和日志面板查看进度及错误信息。画布工具栏提供缩放、适应视图、交互锁定和布局操作。
9. **监控手机画面。** 点击顶部工具栏的手机图标打开浮动实时投屏，画面通过低延迟 H.264 视频流传输，最高约 30 FPS。拖动标题栏移动窗口，拖动右下角调整大小，点击眼睛图标隐藏；再次点击手机图标即可重新显示。隐藏窗口或页面进入后台时视频流会自动停止，窗口会记住上次的位置和尺寸。

常用步骤包括：图像识别并点击、图像识别后连击、坐标点击、滑动、等待、执行其他预设和循环控制。具体字段会根据步骤类型显示在右侧属性面板。

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

设备触控和截图选取需要连接并授权 Android 设备，单元测试无法覆盖实际设备操作。
