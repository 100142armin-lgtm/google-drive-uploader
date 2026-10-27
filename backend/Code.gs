/**
 * Google Drive High-Speed Uploader - Backend Service (Google Apps Script)
 * 
 * 功能：
 * 1. 接收客户端握手请求，自动在 Google Drive 对应根目录下创建多级业务归档目录：
 *    【根目录】 -> 【分组 (如: 视频组)】 -> 【上传人 (你的名字)】 -> 【当天日期 (yyyy-MM-dd)】 -> 【接收人/新人名字】
 * 2. 代表部署者向 Google Drive 官方 API v3 申请免密 Resumable 分块断点续传通道（Upload URL）
 * 3. 将会话 URL 安全回传给客户端，客户端直连 Google 官方机房分块推送二进制数据，不消耗 Apps Script 中转流量
 */

// ======================== 全局配置 ========================
// 方式一：直接在下方填入您的 Google Drive 根文件夹 ID（推荐最简便做法）
// 例如文件夹链接为 https://drive.google.com/drive/folders/1ABCxyz... 则 ID 为 1ABCxyz...
const DEFAULT_ROOT_FOLDER_ID = ""; 

/**
 * 获取绑定的根目录 ID
 * 优先读取脚本属性 (Script Properties) 中的 ROOT_FOLDER_ID，其次读取上方常量
 */
function getRootFolderId() {
  const props = PropertiesService.getScriptProperties();
  const propId = props.getProperty("ROOT_FOLDER_ID");
  if (propId && propId.trim()) {
    return propId.trim();
  }
  if (DEFAULT_ROOT_FOLDER_ID && DEFAULT_ROOT_FOLDER_ID.trim()) {
    return DEFAULT_ROOT_FOLDER_ID.trim();
  }
  return "";
}

/**
 * Web App GET 接口：支持网页健康检测及备选参数请求
 */
function doGet(e) {
  try {
    const params = e && e.parameter ? e.parameter : {};
    
    // 如果没有参数，返回系统就绪健康状态
    if (!params.action && !params.fileName) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "success",
        message: "Google Drive High-Speed Uploader Backend is running! (API v3 Ready)",
        rootFolderConfigured: Boolean(getRootFolderId()),
        timestamp: new Date().toISOString()
      })).setMimeType(ContentService.MimeType.JSON);
    }
    
    // 如果带参数，处理会话申请
    const result = handlePrepareUpload(params);
    return ContentService.createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * Web App POST 接口：客户端主要握手请求入口 (支持 JSON Payload)
 */
function doPost(e) {
  try {
    let payload = {};
    if (e && e.postData && e.postData.contents) {
      try {
        payload = JSON.parse(e.postData.contents);
      } catch (jsonErr) {
        payload = e.parameter || {};
      }
    } else if (e && e.parameter) {
      payload = e.parameter;
    }

    const result = handlePrepareUpload(payload);
    return ContentService.createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  }
}

/**
 * 核心处理逻辑：创建多级目录并向 Google Drive 请求 Resumable Upload URL
 */
function handlePrepareUpload(payload) {
  const rootId = getRootFolderId();
  if (!rootId) {
    throw new Error("服务端尚未配置根目录！请在 Code.gs 中填入 DEFAULT_ROOT_FOLDER_ID，或在项目属性中配置 ROOT_FOLDER_ID。");
  }

  // 1. 获取根目录
  const rootFolder = DriveApp.getFolderById(rootId);
  let currentFolder = rootFolder;

  // 2. 多级归档目录定位与创建
  // 第 1 级：分组目录 (如：视频组、作图组)
  const group = (payload.group || payload.groupName || "").trim();
  if (group) {
    currentFolder = getOrCreateFolder(currentFolder, group);
  }

  // 第 2 级：上传人名字 (如：张三)
  const uploader = (payload.uploader || payload.uploaderName || "").trim();
  if (uploader) {
    currentFolder = getOrCreateFolder(currentFolder, uploader);
  }

  // 第 3 级：当天日期 (yyyy-MM-dd)
  const dateStr = (payload.dateStr || Utilities.formatDate(new Date(), Session.getScriptTimeZone() || "GMT+8", "yyyy-MM-dd")).trim();
  if (dateStr) {
    currentFolder = getOrCreateFolder(currentFolder, dateStr);
  }

  // 第 4 级：接收人/新人名字 (如：管理员/李四1234)
  const receiver = (payload.admin || payload.adminName || payload.receiver || payload.receiverName || "").trim();
  if (receiver) {
    currentFolder = getOrCreateFolder(currentFolder, receiver);
  }

  // 3. 向 Google Drive API v3 发起 Resumable Upload 会话初始请求
  const fileName = (payload.fileName || "unnamed_file").trim();
  const fileSize = payload.fileSize ? parseInt(payload.fileSize, 10) : 0;
  const mimeType = payload.mimeType || "application/octet-stream";

  const initUrl = "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable&supportsAllDrives=true&fields=id,name,webViewLink";
  const token = ScriptApp.getOAuthToken();

  const metadata = {
    name: fileName,
    parents: [currentFolder.getId()]
  };

  const headers = {
    "Authorization": "Bearer " + token,
    "Content-Type": "application/json; charset=UTF-8",
    "X-Upload-Content-Type": mimeType
  };
  if (fileSize > 0) {
    headers["X-Upload-Content-Length"] = String(fileSize);
  }

  const options = {
    method: "POST",
    headers: headers,
    payload: JSON.stringify(metadata),
    muteHttpExceptions: true
  };

  const resp = UrlFetchApp.fetch(initUrl, options);
  const respCode = resp.getResponseCode();

  if (respCode !== 200) {
    throw new Error("Google Drive API 返回异常 (" + respCode + "): " + resp.getContentText());
  }

  // 从响应头获取上传 URL (Location 字段)
  const respHeaders = resp.getAllHeaders();
  const uploadUrl = respHeaders["Location"] || respHeaders["location"];

  if (!uploadUrl) {
    throw new Error("未能获取 Google Drive 官方分块上传会话地址，请检查权限。");
  }

  return {
    status: "success",
    data: {
      uploadUrl: uploadUrl,
      folderUrl: currentFolder.getUrl(),
      folderId: currentFolder.getId(),
      folderName: currentFolder.getName()
    }
  };
}

/**
 * 目录查找与创建辅助函数（防止多线程争夺与重复建同名目录）
 */
function getOrCreateFolder(parent, folderName) {
  const cleanName = folderName.replace(/[\/\\\r\n\t]/g, "_").trim();
  if (!cleanName) return parent;

  const folders = parent.getFoldersByName(cleanName);
  if (folders.hasNext()) {
    return folders.next();
  }

  // 加锁防并发重复建目录
  const lock = LockService.getScriptLock();
  try {
    lock.waitLock(10000);
    // 二次确认，防止等待锁期间已被前序请求创建
    const retryFolders = parent.getFoldersByName(cleanName);
    if (retryFolders.hasNext()) {
      return retryFolders.next();
    }
    return parent.createFolder(cleanName);
  } catch (e) {
    // 锁超时兜底创建
    return parent.createFolder(cleanName);
  } finally {
    try { lock.releaseLock(); } catch (err) {}
  }
}
