# 🚀 云端极速上传器 (Google Drive High-Speed Uploader Client v2.0)

> **专为大容量素材（视频/设计稿/工程文件）、高频多人并发与 VPN / 弱网环境设计的跨平台桌面客户端（Windows & macOS）。**  
> 采用 Google Drive 官方 API v3 **Resumable 分块流式传输协议**，配合智能**防写锁避让引擎**与**多级目录自动归档**，轻松支持百兆至 5TB 超大素材稳定上传。

---

## 🌟 核心特性

- ⚡ **5TB 官方 Resumable 分块断点续传**：基于 Google 官方切片协议，即便遭遇网络闪断或 VPN 切换，系统自动探针恢复切片偏移，无需从头重传。
- 📁 **企业级 4 级目录自动归档**：
  `【云端根目录】 ➔ 【业务分组】 ➔ 【上传人名字】 ➔ 【当天日期 (yyyy-MM-dd)】 ➔ 【接收人/新人名字】 ➔ 【素材文件】`
  支持素材一键拖拽，后台自动建立并组织目录，告别云端文件夹混乱。
- 🛡️ **写锁冲突自动避让引擎 (Jitter Exponential Backoff)**：多人同时往同一目录上传时，针对 Google Drive 目录写冲突（HTTP 429 / 500 / 503）内置动态微抖动避让算法，彻底杜绝丢包漏传。
- 🖥️ **Windows 高分屏抗模糊 (Per-Monitor DPI v2)**：彻底消除 2K/4K 笔记本高分屏字体与控件发虚问题，极简暗黑科技美学界面。
- 🍏 **Windows & macOS 双端支持**：包含一键启动脚本、图标资源和 PyInstaller 打包规范，支持一键编译为单文件免安装程序。
- 🔐 **安全脱敏与隐私私有化**：代码与个人凭据彻底解耦，不含任何硬编码私人网盘地址，人人均可 3 分钟搭建属于自己的专属云端高速通道。

---

## 📖 第一部分：Google Apps Script 后端极速部署指南（5 分钟）

本软件客户端通过轻量级的 **Google Apps Script** 与您的 Google Drive 握手生成免密上传通道。请按照以下步骤搭建属于您自己的后端服务：

### 步骤 1：准备一个 Google 文件夹
1. 打开 [Google Drive (谷歌云端硬盘)](https://drive.google.com/)。
2. 新建一个文件夹作为上传归档的总目录（例如命名为 `素材归档总目录`）。
3. 双击进入该文件夹，观察浏览器地址栏中的 URL：
   `https://drive.google.com/drive/folders/1ABCxyz987654321`
   其中 `1ABCxyz987654321` 即为该文件夹的 **Folder ID（目录唯一标识符）**，复制备用。

### 步骤 2：创建 Apps Script 项目
1. 访问 [Google Apps Script 控制台](https://script.google.com/) 并登录您的 Google 账号。
2. 点击左上角 **【新建项目 (New Project)】**，将项目名称重命名为 `GDrive-Uploader-Backend`。

### 步骤 3：粘贴后端源码
1. 在左侧文件列表中打开 `代码.gs` (Code.gs)，清空默认代码。
2. 将本项目 [backend/Code.gs](backend/Code.gs) 中的全部代码复制并粘贴进去。
3. 找到代码第 14 行附近的：
   ```javascript
   const DEFAULT_ROOT_FOLDER_ID = "请在此处填入步骤1复制的文件夹ID";
   ```
   将步骤 1 复制的文件夹 ID 粘贴到双引号中。
4. 按 `Ctrl + S` (Mac 按 `Cmd + S`) 保存项目。

### 步骤 4：部署为 Web 应用
1. 点击编辑器右上角蓝色的 **【部署 (Deploy)】** 按钮，选择 **【新建部署 (New deployment)】**。
2. 在弹出的窗口左侧点击齿轮图标，选择类型为 **【Web 应用 (Web app)】**：
   - **说明 (Description)**：输入 `v2.0 生产通道`。
   - **Web 应用执行身份 (Execute as)**：选择 **我 (User deploying)**（代表由你的账号创建目录和接受上传）。
   - **谁可以访问 (Who has access)**：选择 **任何人 (Anyone)**（注意：必须选择任何人，客户端才能免密向该接口申请切片通道；只要不公开此 URL，他人无法知晓）。
3. 点击 **【部署 (Deploy)】**。

### 步骤 5：授权并获取专属 Web App 网址
1. 首次部署时，Google 会弹出权限提示，点击 **【审查权限 (Review permissions)】** ➔ 选择你的 Google 账号。
2. 如出现“Google 尚未验证此应用”，点击左下方的小字 **Advanced (高级)** ➔ 点击 **Go to GDrive-Uploader-Backend (unsafe / 继续前往)** ➔ 点击 **Allow (允许)**。
3. 部署成功后，窗口中会显示 **Web 应用网址 (Web app URL)**，形如：
   `https://script.google.com/macros/s/AKfycb.../exec`
4. 点击 **【复制】** 该链接，恭喜您！后端服务已搭建完毕。

---

## 💻 第二部分：客户端使用与配置

### 1. 填入专属通道网址
1. 启动客户端后，点击右上角 **【⚙ 全局设置】**。
2. 在 **Google Apps Script 部署网址** 栏中，粘贴上方步骤 5 复制的 Web App 链接。
3. 点击 **【保存设置】**（配置会自动加密缓存在本地，以后无需重复输入）。
4. 点击顶部的 **【🌐 握手测试】**，若提示 `✓ 握手成功！HTTP 200 OK`，即代表通道完全畅通！

### 2. 开始上传
1. 选择你的 **【业务分组】**（视频组 / 效果组 / 作图组 / 新人拍摄素材）。
2. 输入 **【你的名字】** 与 **【接收人/管理员姓名】**。
3. 将任意格式视频（`.mp4`、`.mov`、`.mkv`、`.ts`）或素材文件夹**直接拖拽**进软件窗口。
4. 点击 **【🚀 开始极速上传】**。
5. 上传完成后，可点击 **【📁 打开云端目录】** 一键在浏览器中直达自动创建的归档目录。

---

## 🛠️ 第三部分：开发者本地运行与独立打包

### 1. 环境依赖安装
本项目基于 Python 3.10+，使用标准库与 CustomTkinter 构建：
```bash
# 克隆仓库
git clone https://github.com/100142armin-lgtm/google-drive-uploader.git
cd google-drive-uploader

# 安装依赖
pip install -r requirements.txt
```

### 2. 本地运行调试
```bash
python app.py
```

### 3. 打包为 Windows 单文件免安装程序 (.exe)
```bash
pyinstaller --noconfirm GDriveUploader.spec
```
编译完成后，可在 `dist/` 目录下获取独立的 `GDriveUploader.exe`，不依赖本地 Python 环境，直接分发给团队员工双击使用。

### 4. macOS 客户端使用与原生打包
- **日常使用**：Mac 用户直接双击 `启动上传器.command` 即可自动检查环境并运行。
- **原生应用打包**：在 Mac 终端执行：
  ```bash
  bash 一键打包Mac原生App.sh
  ```
  将在 `dist/` 生成独立的 `云端极速上传器.app`。

---

## ❓ 第四部分：常见问题排查 (FAQ)

### Q1：国内使用需要开启科学上网 / VPN 吗？
> **是的**。因为 Google Drive API 服务器位于海外，在中国大陆境内网络下，必须开启电脑端的科学上网工具或在软件内配置本地网络代理（如 `http://127.0.0.1:7890`）。

### Q2：上传的视频为什么在 Google Drive 网页上点开前 5 秒不播放？
> **这是 Google 网页预览播放器的转码特性，原文件完全正常**：
> 1. Google Drive 网页版并不直接播放您的原始文件，而是后台自动生成类似 YouTube 的二次压缩预览流。若原视频的关键帧（GOP）间隔较长，网页流媒体播放器会自动寻道到第 1 个关键帧（常见于 3~5 秒处）开始解码，导致在线看感觉前几秒被跳过。
> 2. **验证方法**：在 Google Drive 中右键选择 **【下载】** 到本地，用 PotPlayer、VLC 或 QuickTime 打开播放，前 5 秒内容完整无缺，且文件字节大小与本地原视频 100% 一致。

### Q3：切片分块大小（Chunk Size）如何选择？
> - **4 MB（系统默认，强烈推荐）**：在绝大多数家庭宽带与 VPN 节点下容错率与稳定性最高，断线重试成本极小。
> - **2 MB**：适合弱网、不稳定或经常闪断的网络环境。
> - **8 MB / 16 MB**：适合企业千兆直连专线，可减少 HTTP 握手交互。

### Q4：如何确保我自己的 Google Drive 存储空间安全？
> 1. 只要您不把步骤 5 获取的 `Web app URL` 随意公开发在互联网论坛上，外部人员就完全无法定位并上传到您的云端目录。
> 2. 若未来人员变动需要作废通道，只需在 Google Apps Script 中点击 **【管理部署】** ➔ **【归档/删除旧版本】**，旧网址即刻永久失效。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源发布。
