import type { AttachmentAdapter, CompleteAttachment, PendingAttachment } from "@assistant-ui/react";

export const MAX_ATTACH_BYTES = 25 * 1024 * 1024;
export const MAX_ATTACH_SIZE_LABEL = "25MB";


const ALLOWED_EXTS = new Set([
  ".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp3", ".wav", ".m4a", ".ogg", ".mp4", ".webm", ".mov",
  ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml", ".xml", ".html", ".css", ".log",
  ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".zip",
]);

const BLOCKED_EXTS = new Set([
  ".exe", ".dmg", ".pkg", ".sh", ".bat", ".cmd", ".ps1", ".tar", ".gz", ".7z", ".rar",
  ".docm", ".xlsm", ".pptm",
]);

const ALLOWED_MIME = new Set([
  "application/pdf", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation",
  "application/zip", "application/x-zip-compressed",
  "text/plain", "text/markdown", "text/csv", "text/tab-separated-values", "application/json",
  "application/x-ndjson", "application/yaml", "text/yaml", "application/xml", "text/xml", "text/html", "text/css",
]);

export const ATTACH_ACCEPT = [
  "image/*", "audio/*", "video/*",
  ...ALLOWED_EXTS,
  ...ALLOWED_MIME,
].join(",");


const getExtension = (name: string) => {
  const idx = name.lastIndexOf(".");
  return idx === -1 ? "" : name.slice(idx).toLowerCase();
}

const isAllowedFile = (file: File) => {
  const ext = getExtension(file.name);
  const mimeType = file.type.toLowerCase();

  if (BLOCKED_EXTS.has(ext)) return false;
  if (ALLOWED_EXTS.has(ext)) return true;
  if (mimeType.startsWith("image/")) return true;
  if (mimeType.startsWith("audio/")) return true;
  if (mimeType.startsWith("video/")) return true;

  return ALLOWED_MIME.has(mimeType);
};

const createdId = () => 
  globalThis.crypto?.randomUUID?.() ?? 
  `att_${Date.now()}_${Math.random().toString(36).slice(2)}`;

const attachmentTypeFor = (file: File): PendingAttachment["type"] => {
  const ext = getExtension(file.name);
  const mimeType = file.type.toLowerCase();

  if (mimeType.startsWith("image/")) return "image";
  if ([".png", ".jpg", ".jpeg", ".webp", ".gif"].includes(ext)) {
    return "image";
  }

  if (
    [
      ".txt", ".md", ".csv", ".tsv", ".json", ".jsonl", ".yaml", ".yml",
      ".xml", ".html", ".css", ".log", ".pdf", ".doc", ".docx", ".xls",
      ".xlsx", ".ppt", ".pptx",
    ].includes(ext)
  ) {
    return "document";
  }

  return "file";
};

export const uiOnlyAttachmentAdapter: AttachmentAdapter = {
  accept: ATTACH_ACCEPT,

  async add({ file }): Promise<PendingAttachment> {

    if (file.size > MAX_ATTACH_BYTES) {
      throw new Error(`ファイルサイズは${MAX_ATTACH_SIZE_LABEL}以下にしてください。`);
    }

    if (!isAllowedFile(file)) {
      throw new Error("supported file are 'image/sound/movie, text, pdf/office, zip' file.");
    }

    return {
      id: createdId(),
      type: attachmentTypeFor(file),
      name: file.name,
      contentType: file.type || undefined,
      file,
      status: { type: "requires-action", reason: "composer-send" },
    };
  },

  async remove() {},

  async send(attachment): Promise<CompleteAttachment> {
    return {
      ...attachment,
      status: { type: "complete" },
      content: [],
    };
  },
};

