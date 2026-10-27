# 提交信息规范

本项目采用 [Conventional Commits](https://www.conventionalcommits.org/) 的简化形式：类型与范围用英文标识，摘要和正文用中文。

## 格式

```text
<type>(<scope>): <摘要>

<正文（可选）>
```

- 摘要行不超过 50 个字符，结尾不加句号
- 正文与摘要之间空一行，每条以 `- ` 开头

## 类型（type）

| 类型 | 用于 |
| --- | --- |
| `feat` | 新增功能 |
| `fix` | 修复缺陷 |
| `refactor` | 重构，不改变外部行为 |
| `perf` | 性能优化 |
| `docs` | 文档、README |
| `test` | 测试用例与测试脚本 |
| `build` | 打包、依赖、构建配置 |
| `ci` | 持续集成配置 |
| `chore` | 杂项：忽略规则、配置、发布整理 |
| `style` | 格式调整，不影响逻辑 |

## 范围（scope）

可选，按模块或主题取一个：

`web`（前端）、`ui`（界面交互）、`steps`（步骤与执行）、`engine`（引擎）、`vision`（图像识别）、`device`（ADB）、`config`（预设配置）、`gitignore`、`release`、`deps`。

## 摘要写法

- 用祈使句描述「做了什么」：新增、移除、调整、迁移、修复
- 说明改动对象，而不是笼统的「更新一下」
- 不写日期、版本号、「可正式使用」这类无法检索的信息
- 一个提交只做一件事；混在一起的改动拆成多个提交

## 正文写法

- 列出关键改动点、影响范围，以及需要兼容或迁移的注意点
- 涉及配置格式变化时，写明旧数据如何迁移

## 破坏性变更

在类型后加 `!`，并在正文中写明迁移方式：

```text
feat(config)!: 预设存储改为 schema v3

- 旧版 `support_pos`/`start_pos` 配置在首次启动时自动迁移
```

## 示例

好的写法：

```text
feat(steps): 识别步骤支持点击坐标偏移
fix(web): 修复画布锁定后仍可框选节点的问题
docs(readme): 补充 PyInstaller 打包说明
chore(gitignore): 忽略 templates_file 目录
```

需要避免：

```text
更新一下
2026-10-16版本
修复bug
把画布的放大、缩小、自适应、锁定四个按钮的位置也放到画布顶部的位置
```

## 历史提交整理记录

2026-10-27 对仓库早期 11 条提交做了仅改描述的整理，提交内容（tree）、作者与时间戳均保持不变：

| 原描述 | 规范后 |
| --- | --- |
| gui版本，可正式使用 | `feat: 初始化 ADB 图像自动化桌面客户端` |
| 工作流HTML版本，可正式使用 | `feat(web): 新增可视化工作流画布与 Web 服务端` |
| 更新一下.gitgnore | `chore(gitignore): 改为忽略 templates_file 目录内的文件` |
| 再更新一下.gitgnore | `chore(gitignore): 恢复忽略整个 templates_file 目录` |
| 更新README.md教程 | `docs(readme): 补充 PyInstaller 打包与分发说明` |
| 取消放大缩小组件 | `feat(steps): 识别步骤支持点击坐标偏移` |
| 2026-10-16版本 | `chore(config): 更新预设配置并移除模板截图跟踪` |
| 把画布的放大、缩小、自适应、锁定四个按钮的位置也放到画布顶部的位置 | `feat(ui): 画布缩放与锁定控件迁至顶部工具栏` |
| 实现工作流节点失败时浏览器标签图标闪烁提醒 | `feat(ui): 节点失败时闪烁标签页图标提醒` |
| 首个发布github的版本 | `chore(release): 整理 GitHub 首次发布仓库` |
| 首个发布github的版本，补充文件 | `docs: 新增简体中文 README` |
