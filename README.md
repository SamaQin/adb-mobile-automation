# ADB 图像自动化控制台

通过 ADB 和 OpenCV 截取设备画面，并按预设顺序执行模板识别、点击、滑动和等待步骤。

## 启动

Windows 下在项目目录运行：

```bat
.venv\Scripts\python.exe main.py
```

服务默认监听 `http://127.0.0.1:8001` 并自动打开浏览器（可用 `--port 8000` 或 `--no-browser` 覆盖）。开发前端时，可在另一个终端运行 `cd web && npm run dev`，Vite 会把 `/api` 与 `/ws` 代理到 Python 服务。

如果需要重建环境：

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
cd web
npm install
npm run build
```

手机需启用 USB 调试并授权当前电脑。控制台会优先使用项目内的 `adb.exe`，否则使用 `PATH` 中的 `adb`。

## 使用

1. 连接设备并在顶部栏点击“检查设备”。
2. 从左侧步骤库拖入或双击添加节点，通过画布连线设置前置依赖。
3. 在右侧属性面板编辑识别点击、识别连击、坐标点击、滑动或等待步骤。
4. 编辑坐标点击步骤时，可打开设备截图查看实时坐标并单击选取位置。
5. 编辑滑动步骤时，可在设备截图上按住鼠标拖动，自动填写起点、终点和方向。
6. 识别点击和识别连击支持设置点击位置的 `X/Y` 偏移；连击可设置次数和间隔。
7. 对识别步骤，可将“执行失败时”设为“跳到下一步”。
8. 可为步骤关联顺序在前的步骤：前置步骤本轮未执行时，本步骤自动跳过；每轮循环都会重置状态重新判断。
9. 设置预设循环次数；`0` 表示无限循环，直到步骤失败或手动停止。
10. 使用上移/下移或“按布局重排”调整执行顺序，选择预设后点击“运行”。

配置继续写入 `config.json`，截图模板写入 `templates_file/`，以兼容已有用户数据。旧版仅包含 `support_pos` 和 `start_pos` 的配置会在首次启动时自动迁移并保留原流程。

截图交互窗口会根据手机截图与电脑屏幕尺寸自动等比缩小；模板区域、点击位置和滑动轨迹都会换算回手机原始分辨率坐标。

## 打包发布

项目使用 PyInstaller 打包为免安装的单目录程序（`ADB-Automation.spec`），前端静态资源、`adb.exe` 及 ADB 运行库都会一并打入。

### 准备工作（仅首次）

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install pyinstaller
cd web
npm install
```

### 打包步骤

```bat
REM 1. 构建前端（产物输出到 web\dist）
cd web
npm run build
cd ..

REM 2. 执行 PyInstaller 打包（按 ADB-Automation.spec）
.venv\Scripts\pyinstaller.exe --noconfirm ADB-Automation.spec
```

打包完成后，可执行文件在：

```text
dist\ADB-Automation\ADB-Automation.exe
```

### 分发与运行

- 把 `dist\ADB-Automation\` 整个文件夹拷到目标机器即可运行，无需安装 Python 或 Node.js。
- 双击 `ADB-Automation.exe` 启动，服务默认监听 `http://127.0.0.1:8001` 并自动打开浏览器；需要改端口或不开浏览器时，在命令行运行：
  ```bat
  ADB-Automation.exe --port 8080 --no-browser
  ```
- 用户数据（`config.json`、`templates_file\`）会在 exe 所在目录首次启动时自动创建，重装/升级前备份这两个即可。
- 每次修改前端代码后需要重新打包时，重复“打包步骤”中的两步即可；只改 Python 代码则只需第 2 步。

### 常见问题

- 打包后启动失败：多为 `web\dist` 不是最新，先执行 `npm run build` 再打包。
- 端口被占用：换 `--port` 启动。
- 目标机器无 ADB 驱动：程序已内置 `adb.exe`，但需在系统里装好手机对应厂商的 USB 驱动，并开启 USB 调试授权。

## 验证

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q main.py model_automation web_server tests
cd web
npm test
npm run build
```
