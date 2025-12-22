const STORAGE_KEYS = {
  language: "chat_config_v2",
  image: "image_config_v1",
  history: "chat_input_history_v1",
};

const HISTORY_LIMIT = 100;

const state = {
  messages: [],
  promptTree: [],
  transferContent: "",
  inputHistory: [],
  historyFilter: "",
  config: {
    api_key: "",
    model: "",
    base_url: "",
    log_llm: false,
    prompt_path: "",
  },
  imageConfig: {
    api_key: "",
    model: "",
    base_url: "",
  },
};

const chatList = document.getElementById("chatList");
const chatInput = document.getElementById("chatInput");
const sendBtn = document.getElementById("sendBtn");
const clearBtn = document.getElementById("clearBtn");
const chatCount = document.getElementById("chatCount");
const statusBox = document.getElementById("status");
const promptList = document.getElementById("promptList");
const promptStatus = document.getElementById("promptStatus");
const promptTransferModal = document.getElementById("promptTransferModal");
const promptTransferList = document.getElementById("promptTransferList");
const closePromptTransferBtn = document.getElementById("closePromptTransferBtn");
const transferImageBtn = document.getElementById("transferImageBtn");
const lmConfigBtn = document.getElementById("lmConfigBtn");
const imgConfigBtn = document.getElementById("imgConfigBtn");
const lmConfigModal = document.getElementById("lmConfigModal");
const imgConfigModal = document.getElementById("imgConfigModal");
const closeLmConfigBtn = document.getElementById("closeLmConfigBtn");
const closeImgConfigBtn = document.getElementById("closeImgConfigBtn");
const apiKeyInput = document.getElementById("apiKeyInput");
const modelInput = document.getElementById("modelInput");
const baseUrlInput = document.getElementById("baseUrlInput");
const toggleKeyBtn = document.getElementById("toggleKeyBtn");
const saveConfigBtn = document.getElementById("saveConfigBtn");
const configStatus = document.getElementById("configStatus");
const toggleLogBtn = document.getElementById("toggleLogBtn");
const logStatus = document.getElementById("logStatus");
const imgApiKeyInput = document.getElementById("imgApiKeyInput");
const imgModelInput = document.getElementById("imgModelInput");
const imgBaseUrlInput = document.getElementById("imgBaseUrlInput");
const saveImgConfigBtn = document.getElementById("saveImgConfigBtn");
const imgConfigStatus = document.getElementById("imgConfigStatus");
const historySection = document.getElementById("historySection");
const historyList = document.getElementById("historyList");
const historySearch = document.getElementById("historySearch");
const historyStatus = document.getElementById("historyStatus");
const toggleHistoryBtn = document.getElementById("toggleHistoryBtn");

function setStatus(text, type = "") {
  statusBox.textContent = text || "";
  statusBox.className = `status ${type}`.trim();
}

function setConfigStatus(text, type = "") {
  configStatus.textContent = text || "";
  configStatus.className = `config-status ${type}`.trim();
}

function setImageConfigStatus(text, type = "") {
  imgConfigStatus.textContent = text || "";
  imgConfigStatus.className = `config-status ${type}`.trim();
}

function setLogStatus(text, type = "") {
  logStatus.textContent = text || "";
  logStatus.className = `config-status ${type}`.trim();
}

function setPromptStatus(text, type = "") {
  if (!promptStatus) return;
  promptStatus.textContent = text || "";
  promptStatus.className = `config-status ${type}`.trim();
}

function setHistoryStatus(text) {
  if (!historyStatus) return;
  historyStatus.textContent = text || "";
}

function updateHistoryToggleLabel(collapsed) {
  if (!toggleHistoryBtn) return;
  toggleHistoryBtn.textContent = collapsed ? "展开" : "收起";
}

function updateLogToggle() {
  if (!toggleLogBtn) return;
  toggleLogBtn.textContent = state.config.log_llm ? "关闭完整日志" : "开启完整日志";
  setLogStatus(state.config.log_llm ? "已开启" : "已关闭", state.config.log_llm ? "status--ok" : "");
}

function validateConfigInput(apiKey, model, baseUrl) {
  if (baseUrl && !baseUrl.startsWith("https://")) {
    return "BASE_URL 必须以 https:// 开头。";
  }
  if (apiKey && apiKey.length < 10) {
    return "API_KEY 格式看起来不正确。";
  }
  if (model && model.length < 2) {
    return "MODEL 格式看起来不正确。";
  }
  return "";
}

function validateImageConfig(apiKey, model, baseUrl) {
  if (baseUrl && !baseUrl.startsWith("https://")) {
    return "IMG_BASE_URL 必须以 https:// 开头。";
  }
  if (apiKey && apiKey.length < 10) {
    return "IMG_API_KEY 格式看起来不正确。";
  }
  if (model && model.length < 2) {
    return "IMG_MODEL 格式看起来不正确。";
  }
  return "";
}

function loadInputHistory() {
  try {
    const raw = localStorage.getItem(STORAGE_KEYS.history);
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const sanitized = parsed
      .filter((item) => item && typeof item.text === "string")
      .map((item) => ({
        text: item.text,
        ts: typeof item.ts === "number" ? item.ts : Date.now(),
      }));
    return sanitized.slice(0, HISTORY_LIMIT);
  } catch (error) {
    return [];
  }
}

function persistInputHistory() {
  try {
    localStorage.setItem(
      STORAGE_KEYS.history,
      JSON.stringify(state.inputHistory.slice(0, HISTORY_LIMIT))
    );
  } catch (error) {
    setHistoryStatus("无法写入本地存储。");
  }
}

function renderInputHistory() {
  if (!historyList) return;
  const filter = (state.historyFilter || "").toLowerCase();
  const filtered = state.inputHistory.filter((item) =>
    item.text.toLowerCase().includes(filter)
  );
  historyList.innerHTML = "";
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "history-empty";
    empty.textContent = state.inputHistory.length
      ? "未找到匹配的记录。"
      : "暂无记录。";
    historyList.appendChild(empty);
  } else {
    filtered.forEach((entry) => {
      const item = document.createElement("div");
      item.className = "history-item";
      const meta = document.createElement("div");
      meta.className = "history-meta";
      const badge = document.createElement("span");
      badge.className = "history-badge";
      badge.textContent = "用户输入";
      const time = document.createElement("span");
      time.textContent = new Date(entry.ts).toLocaleString();
      meta.appendChild(badge);
      meta.appendChild(time);
      item.appendChild(meta);

      const text = document.createElement("div");
      text.className = "history-text";
      text.textContent = entry.text;
      item.appendChild(text);

      const actions = document.createElement("div");
      actions.className = "history-actions";
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn btn--ghost btn--small";
      copyBtn.textContent = "复制";
      copyBtn.addEventListener("click", () => copyText(entry.text));

      const fillBtn = document.createElement("button");
      fillBtn.type = "button";
      fillBtn.className = "btn btn--ghost btn--small";
      fillBtn.textContent = "填入输入框";
      fillBtn.addEventListener("click", () => fillInputFromHistory(entry.text));

      actions.appendChild(copyBtn);
      actions.appendChild(fillBtn);
      item.appendChild(actions);

      historyList.appendChild(item);
    });
  }
  setHistoryStatus(`已保存 ${state.inputHistory.length} 条`);
}

function addUserInputToHistory(text) {
  const normalized = (text || "").trim();
  if (!normalized) return;
  state.inputHistory.unshift({ text: normalized, ts: Date.now() });
  if (state.inputHistory.length > HISTORY_LIMIT) {
    state.inputHistory.length = HISTORY_LIMIT;
  }
  persistInputHistory();
  renderInputHistory();
}

function toggleHistoryPanel() {
  if (!historySection) return;
  const collapsed = historySection.classList.toggle("history--collapsed");
  updateHistoryToggleLabel(collapsed);
}

function handleHistorySearch(event) {
  state.historyFilter = event.target.value || "";
  renderInputHistory();
}

function fillInputFromHistory(text) {
  chatInput.value = text;
  chatInput.focus();
  setStatus("已填充到输入框，可直接发送或编辑。", "status--ok");
}

function initHistoryPanel() {
  state.inputHistory = loadInputHistory();
  renderInputHistory();
  if (historySection) {
    const collapsed = historySection.classList.contains("history--collapsed");
    updateHistoryToggleLabel(collapsed);
  }
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

function loadStoredConfig(key) {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    const data = JSON.parse(raw);
    return data && typeof data === "object" ? data : null;
  } catch (error) {
    return null;
  }
}

function saveStoredConfig(key, config) {
  sessionStorage.setItem(key, JSON.stringify(config));
}

function applyLmConfigToInputs(config) {
  apiKeyInput.value = config.api_key || "";
  modelInput.value = config.model || "";
  baseUrlInput.value = config.base_url || "";
  updateLogToggle();
}

function applyImageConfigToInputs(config) {
  imgApiKeyInput.value = config.api_key || "";
  imgModelInput.value = config.model || "";
  imgBaseUrlInput.value = config.base_url || "";
}

async function loadConfig() {
  const stored = loadStoredConfig(STORAGE_KEYS.language) || {};
  try {
    const data = await getJson("/api/config");
    const merged = {
      api_key: data.api_key || "",
      model: data.model || "",
      base_url: data.base_url || "",
      log_llm: Boolean(data.log_llm),
      prompt_path: data.prompt_path || "",
    };
    if (stored.prompt_path) {
      merged.prompt_path = stored.prompt_path;
    }
    if (stored.source === "user") {
      if (stored.api_key) merged.api_key = stored.api_key;
      if (stored.model) merged.model = stored.model;
      if (stored.base_url) merged.base_url = stored.base_url;
      if (typeof stored.log_llm === "boolean") merged.log_llm = stored.log_llm;
    }
    state.config = merged;
    applyLmConfigToInputs(state.config);
    setConfigStatus(
      stored.source === "user" ? "已加载本标签页配置。" : "已加载默认配置。",
      "status--ok"
    );
  } catch (error) {
    if (Object.keys(stored).length) {
      state.config = {
        api_key: stored.api_key || "",
        model: stored.model || "",
        base_url: stored.base_url || "",
        log_llm: Boolean(stored.log_llm),
        prompt_path: stored.prompt_path || "",
      };
      applyLmConfigToInputs(state.config);
      setConfigStatus("已加载本标签页配置。", "status--ok");
    } else {
      setConfigStatus(error.message, "status--warn");
    }
  }
}

async function loadImageConfig() {
  const stored = loadStoredConfig(STORAGE_KEYS.image) || {};
  try {
    const data = await getJson("/api/image_config");
    const merged = {
      api_key: data.api_key || "",
      model: data.model || "",
      base_url: data.base_url || "",
    };
    if (stored.source === "user") {
      if (stored.api_key) merged.api_key = stored.api_key;
      if (stored.model) merged.model = stored.model;
      if (stored.base_url) merged.base_url = stored.base_url;
    }
    state.imageConfig = merged;
    applyImageConfigToInputs(state.imageConfig);
    setImageConfigStatus(
      stored.source === "user" ? "已加载本标签页配置。" : "已加载默认配置。",
      "status--ok"
    );
  } catch (error) {
    if (Object.keys(stored).length) {
      state.imageConfig = {
        api_key: stored.api_key || "",
        model: stored.model || "",
        base_url: stored.base_url || "",
      };
      applyImageConfigToInputs(state.imageConfig);
      setImageConfigStatus("已加载本标签页配置。", "status--ok");
    } else {
      setImageConfigStatus(error.message, "status--warn");
    }
  }
}

async function saveConfig() {
  const apiKey = apiKeyInput.value.trim();
  const model = modelInput.value.trim();
  const baseUrl = baseUrlInput.value.trim();
  const error = validateConfigInput(apiKey, model, baseUrl);
  if (error) {
    setConfigStatus(error, "status--warn");
    return;
  }
  setConfigStatus("正在保存配置...", "status--loading");
  saveConfigBtn.disabled = true;
  try {
    state.config.api_key = apiKey;
    state.config.model = model;
    state.config.base_url = baseUrl;
    saveStoredConfig(STORAGE_KEYS.language, {
      api_key: state.config.api_key,
      model: state.config.model,
      base_url: state.config.base_url,
      log_llm: state.config.log_llm,
      prompt_path: state.config.prompt_path,
      source: "user",
    });
    setConfigStatus("配置已保存到本标签页。", "status--ok");
  } catch (error) {
    setConfigStatus(error.message, "status--warn");
  } finally {
    saveConfigBtn.disabled = false;
  }
}

function saveImageConfig() {
  const apiKey = imgApiKeyInput.value.trim();
  const model = imgModelInput.value.trim();
  const baseUrl = imgBaseUrlInput.value.trim();
  const error = validateImageConfig(apiKey, model, baseUrl);
  if (error) {
    setImageConfigStatus(error, "status--warn");
    return;
  }
  setImageConfigStatus("正在保存配置...", "status--loading");
  saveImgConfigBtn.disabled = true;
  try {
    state.imageConfig.api_key = apiKey;
    state.imageConfig.model = model;
    state.imageConfig.base_url = baseUrl;
    saveStoredConfig(STORAGE_KEYS.image, {
      api_key: state.imageConfig.api_key,
      model: state.imageConfig.model,
      base_url: state.imageConfig.base_url,
      source: "user",
    });
    setImageConfigStatus("生图配置已保存。", "status--ok");
  } catch (error) {
    setImageConfigStatus(error.message, "status--warn");
  } finally {
    saveImgConfigBtn.disabled = false;
  }
}

function toggleLogOutput() {
  state.config.log_llm = !state.config.log_llm;
  saveStoredConfig(STORAGE_KEYS.language, {
    api_key: state.config.api_key,
    model: state.config.model,
    base_url: state.config.base_url,
    log_llm: state.config.log_llm,
    prompt_path: state.config.prompt_path,
    source: "user",
  });
  updateLogToggle();
}

function toggleApiKey() {
  if (apiKeyInput.type === "password") {
    apiKeyInput.type = "text";
    toggleKeyBtn.textContent = "隐藏";
  } else {
    apiKeyInput.type = "password";
    toggleKeyBtn.textContent = "显示";
  }
}

function openModal(modal) {
  if (!modal) return;
  modal.classList.remove("modal--hidden");
}

function closeModal(modal) {
  if (!modal) return;
  modal.classList.add("modal--hidden");
}

function getSelectedTextWithin(element) {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return "";
  const text = selection.toString().trim();
  if (!text) return "";
  if (!element) return "";
  const anchorNode = selection.anchorNode;
  const focusNode = selection.focusNode;
  if (!anchorNode || !focusNode) return "";
  if (element.contains(anchorNode) && element.contains(focusNode)) {
    return text;
  }
  return "";
}

function resolveTransferContent(content, element) {
  const selected = getSelectedTextWithin(element);
  return selected || content || "";
}

function renderPromptTree(container, nodes, selected, onSelect) {
  if (!container) return;
  container.innerHTML = "";
  const root = document.createElement("ul");
  container.appendChild(root);

  const buildNodes = (items, parent) => {
    items.forEach((item) => {
      const li = document.createElement("li");
      const row = document.createElement("div");
      row.className = "prompt-tree__item";
      if (item.type === "dir") {
        const label = document.createElement("span");
        label.className = "prompt-tree__folder";
        label.textContent = item.name;
        row.appendChild(label);
        li.appendChild(row);
        const childList = document.createElement("ul");
        buildNodes(item.children || [], childList);
        li.appendChild(childList);
      } else if (item.type === "file") {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "prompt-tree__btn";
        if (item.path === selected) {
          btn.classList.add("prompt-tree__btn--active");
        }
        btn.textContent = item.name;
        btn.dataset.path = item.path || "";
        btn.addEventListener("click", () => onSelect(item.path || ""));
        row.appendChild(btn);
        li.appendChild(row);
      }
      parent.appendChild(li);
    });
  };

  buildNodes(nodes || [], root);
}

async function loadPrompts() {
  try {
    const data = await getJson("/api/prompts");
    state.promptTree = data.tree || [];
    const selected = state.config.prompt_path || data.selected || "";
    state.config.prompt_path = selected;
    const stored = loadStoredConfig(STORAGE_KEYS.language) || {};
    saveStoredConfig(STORAGE_KEYS.language, { ...stored, prompt_path: selected });
    renderPromptTree(promptList, state.promptTree, selected, selectPromptForCurrentTab);
    setPromptStatus(selected ? "已选择提示词。" : "请选择提示词。", selected ? "status--ok" : "status--warn");
  } catch (error) {
    setPromptStatus(error.message, "status--warn");
  }
}

function selectPromptForCurrentTab(path) {
  if (!path) return;
  state.config.prompt_path = path;
  const stored = loadStoredConfig(STORAGE_KEYS.language) || {};
  saveStoredConfig(STORAGE_KEYS.language, { ...stored, prompt_path: path });
  renderPromptTree(promptList, state.promptTree, path, selectPromptForCurrentTab);
  setPromptStatus("提示词已更新。", "status--ok");
}

function openPromptTransferModal(content, element) {
  state.transferContent = resolveTransferContent(content, element);
  if (!state.transferContent) {
    setStatus("没有可发送的内容。", "status--warn");
    return;
  }
  renderPromptTree(
    promptTransferList,
    state.promptTree,
    "",
    handlePromptTransferSelect
  );
  openModal(promptTransferModal);
}

function handlePromptTransferSelect(path) {
  if (!path || !state.transferContent) return;
  const url = new URL(window.location.href);
  url.searchParams.set("prompt", path);
  url.searchParams.set("seed", state.transferContent);
  url.searchParams.set("auto", "1");
  window.open(url.toString(), "_blank");
  closeModal(promptTransferModal);
  state.transferContent = "";
}

async function handleTransferToImage() {
  if (!state.transferContent) {
    setStatus("没有可发送的内容。", "status--warn");
    return;
  }
  const config = state.imageConfig;
  if (!config.api_key || !config.model || !config.base_url) {
    setStatus("请先完善生图模型配置。", "status--warn");
    return;
  }
  setStatus("正在调用生图模型...", "status--loading");
  try {
    const payload = {
      prompt: state.transferContent,
      config: {
        api_key: config.api_key,
        model: config.model,
        base_url: config.base_url,
      },
    };
    const data = await postJson("/api/image_generate", payload);
    addMessage("assistant", data.reply || "已生成图片。", "image", data.images || []);
    setStatus("已生成图片。", "status--ok");
    closeModal(promptTransferModal);
    state.transferContent = "";
  } catch (error) {
    setStatus(error.message, "status--warn");
  }
}

function renderMessages() {
  chatList.innerHTML = "";
  state.messages.forEach((message) => {
    const bubble = document.createElement("div");
    bubble.className = "chat__bubble";
    bubble.classList.add(
      message.role === "user" ? "chat__bubble--user" : "chat__bubble--assistant"
    );
    const meta = document.createElement("div");
    meta.className = "chat__meta";
    const label =
      message.role === "user"
        ? "你"
        : message.source === "image"
        ? "生图模型"
        : "模型";
    meta.textContent = `${label} ${message.ts || ""}`.trim();
    bubble.appendChild(meta);
    if (message.content) {
      const text = document.createElement("div");
      text.className = "chat__text";
      text.textContent = message.content || "";
      bubble.appendChild(text);
    }
    if (Array.isArray(message.images) && message.images.length) {
      const images = document.createElement("div");
      images.className = "chat__images";
      message.images.forEach((img) => {
        if (!img || !img.value) return;
        const imageEl = document.createElement("img");
        imageEl.className = "chat__image";
        if (img.type === "b64") {
          const fmt = (img.format || "png").toLowerCase();
          imageEl.src = `data:image/${fmt};base64,${img.value}`;
        } else {
          imageEl.src = img.value;
        }
        imageEl.alt = "生成图片";
        images.appendChild(imageEl);
      });
      bubble.appendChild(images);
    }
    if (message.role === "assistant") {
      const actions = document.createElement("div");
      actions.className = "chat__actions chat__actions--inline";
      const copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "btn btn--ghost btn--small";
      copyBtn.textContent = "复制";
      copyBtn.addEventListener("click", () => copyText(message.content || ""));
      const transferBtn = document.createElement("button");
      transferBtn.type = "button";
      transferBtn.className = "btn btn--ghost btn--small";
      transferBtn.textContent = "发送至";
      transferBtn.addEventListener("click", () =>
        openPromptTransferModal(message.content || "", bubble)
      );
      actions.appendChild(copyBtn);
      actions.appendChild(transferBtn);
      bubble.appendChild(actions);
    }
    chatList.appendChild(bubble);
  });
  if (chatCount) {
    chatCount.textContent = `${state.messages.length} 条消息`;
  }
  chatList.scrollTop = chatList.scrollHeight;
}

function addMessage(role, content, source = "", images = []) {
  state.messages.push({
    role,
    content: content || "",
    ts: new Date().toLocaleString(),
    source,
    images: Array.isArray(images) ? images : [],
  });
  renderMessages();
}

function buildChatPayload(config) {
  return {
    messages: state.messages.map((msg) => ({
      role: msg.role,
      content: msg.content,
    })),
    config: {
      api_key: config.api_key,
      model: config.model,
      base_url: config.base_url,
      log_llm: Boolean(config.log_llm),
      prompt_path: state.config.prompt_path,
    },
  };
}

async function sendMessage(target = "language") {
  const text = chatInput.value.trim();
  if (!text) {
    setStatus("请输入内容。", "status--warn");
    return;
  }
  addUserInputToHistory(text);
  if (!state.config.prompt_path) {
    setStatus("请先选择提示词。", "status--warn");
    return;
  }
  const config = target === "image" ? state.imageConfig : state.config;
  if (!config.api_key || !config.model || !config.base_url) {
    setStatus(
      target === "image" ? "请先完善生图模型配置。" : "请先完善语言模型配置。",
      "status--warn"
    );
    return;
  }
  addMessage("user", text);
  chatInput.value = "";
  setStatus(target === "image" ? "正在调用生图模型..." : "正在生成回复...", "status--loading");
  sendBtn.disabled = true;
  try {
    const payload = buildChatPayload(config);
    const data = await postJson("/api/chat", payload);
    addMessage("assistant", data.reply || "", target === "image" ? "image" : "language");
    setStatus("已生成回复。", "status--ok");
  } catch (error) {
    setStatus(error.message, "status--warn");
  } finally {
    sendBtn.disabled = false;
  }
}

function clearChat() {
  state.messages = [];
  renderMessages();
  setStatus("已清空对话。", "status--ok");
}

function handleInputKey(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage("language");
  }
}

async function copyText(text) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    setStatus("已复制到剪贴板。", "status--ok");
  } catch (error) {
    setStatus("复制失败，请手动选择文本。", "status--warn");
  }
}

function bindModalClose(modal) {
  if (!modal) return;
  modal.addEventListener("click", (event) => {
    const target = event.target;
    if (target && target.dataset.modalClose === "true") {
      closeModal(modal);
    }
  });
}

function getQueryOverrides() {
  const params = new URLSearchParams(window.location.search);
  return {
    prompt: params.get("prompt") || "",
    seed: params.get("seed") || "",
    auto: params.get("auto") === "1",
  };
}

async function initPage() {
  const overrides = getQueryOverrides();
  initHistoryPanel();
  await loadConfig();
  await loadImageConfig();
  if (overrides.prompt) {
    state.config.prompt_path = overrides.prompt;
    const stored = loadStoredConfig(STORAGE_KEYS.language) || {};
    saveStoredConfig(STORAGE_KEYS.language, { ...stored, prompt_path: overrides.prompt });
  }
  await loadPrompts();
  renderMessages();
  if (overrides.seed) {
    chatInput.value = overrides.seed;
    if (overrides.auto) {
      sendMessage("language");
    }
  }
}

sendBtn.addEventListener("click", () => sendMessage("language"));
clearBtn.addEventListener("click", clearChat);
chatInput.addEventListener("keydown", handleInputKey);
saveConfigBtn.addEventListener("click", saveConfig);
saveImgConfigBtn.addEventListener("click", saveImageConfig);
toggleKeyBtn.addEventListener("click", toggleApiKey);
toggleLogBtn.addEventListener("click", toggleLogOutput);
if (toggleHistoryBtn) {
  toggleHistoryBtn.addEventListener("click", toggleHistoryPanel);
}
if (historySearch) {
  historySearch.addEventListener("input", handleHistorySearch);
}

lmConfigBtn.addEventListener("click", () => openModal(lmConfigModal));
imgConfigBtn.addEventListener("click", () => openModal(imgConfigModal));
closeLmConfigBtn.addEventListener("click", () => closeModal(lmConfigModal));
closeImgConfigBtn.addEventListener("click", () => closeModal(imgConfigModal));
closePromptTransferBtn.addEventListener("click", () => closeModal(promptTransferModal));
if (transferImageBtn) {
  transferImageBtn.addEventListener("click", handleTransferToImage);
}

bindModalClose(lmConfigModal);
bindModalClose(imgConfigModal);
bindModalClose(promptTransferModal);

initPage();
