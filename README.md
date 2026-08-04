# ADB 图像自动化控制台

通过 ADB 和 OpenCV 截取设备画面，并按预设顺序执行模板识别、点击、滑动和等待步骤。

## 启动

Windows 下在项目目录运行：

```bat
.venv\Scripts\python.exe main.py
```

服务默认监听 `http://127.0.0.1:8000` 并自动打开浏览器。开发前端时，可在另一个终端运行 `cd web && npm run dev`，Vite 会把 `/api` 与 `/ws` 代理到 Python 服务。

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

## 验证

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q main.py model_automation web_server tests
cd web
npm test
npm run build
```
