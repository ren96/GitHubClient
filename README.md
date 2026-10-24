# GitHub 桌面客户端

一个基于 Tkinter 的 GitHub 桌面客户端，支持仓库管理、Issue / PR 浏览与操作、Gist、下载、通知轮询、自动更新等。

## 功能

- 📁 我的仓库：分页浏览、排序、筛选、收藏、静音、右键菜单（打开本地 / VS Code / 终端 / ZIP / clone / pull）
- 🔍 搜索：仓库、代码、趋势；支持本地历史记录下拉
- 📝 Issues：列表、分页、筛选、新建、编辑、关闭/重开、评论、永久删除
- 🔀 PR：列表、详情、文件变更、Diff、Review（批准 / 请求修改 / 评论）、合并 / 关闭
- 🔔 通知：轮询、未读徽标、静音仓库
- ⭐ Starred：浏览与取消 Star
- 📝 Gists：列表、创建、编辑、删除、从剪贴板创建
- 📥 下载队列：Release 资产并发下载、暂停 / 继续 / 重试 / 定位
- 🚀 上传本地项目：自动 init / commit / push，可自动生成 `.gitignore`
- 🎨 主题：跟随系统 / 浅色 / 深色
- 🔐 登录：PAT 或 OAuth Device Flow；Token 保存在系统密钥环（不可用时回退到 `600` 权限文件）
- 🔔 托盘：最小化到托盘，桌面通知
- ⬆️ 自动更新：通过 GitHub Release 分发，支持 stable / beta 通道、下载并安装、忽略指定版本
- ⌨️ 快捷键：`Ctrl+F` 搜索 / `Ctrl+K` 命令面板 / `Ctrl+N` 新建 Issue / `Ctrl+S` 切换主题 / `Ctrl+P` 设置 / `Ctrl+U` 检查更新 / `Ctrl+Q` 退出 / `F5` 刷新 / `F1` 快捷键面板 / `Delete` 删除选中 Issue

## 安装依赖

```bash
pip install -r requirements.txt