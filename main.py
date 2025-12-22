# -*- coding: utf-8 -*-
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import threading
import time
import urllib.error
import urllib.request
import urllib.parse
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
PROMPT_DIR = os.path.join(BASE_DIR, "prompt")

DEFAULT_MODEL = "mimo-v2-flash"
DEFAULT_BASE_URL = "https://api.qnaigc.com/v1/chat/completions"
DEFAULT_IMAGE_ENDPOINT = "/images/generations"

LOG_DIR = os.path.join(BASE_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")
DEFAULT_SYSTEM_PROMPT_FILE = os.path.join(BASE_DIR, "prompt/需求分析.md")

MAX_BODY_BYTES = 1_000_000
MAX_REQUIREMENT_LEN = 8000
MAX_CONTEXT_LEN = 12000
MAX_OUTPUT_LEN = 20000
MAX_OPTION_LEN = 200
MAX_HISTORY_ITEMS = 30
MAX_HISTORY_IN_CONTEXT = 6
MAX_CHAT_MESSAGES = 50
RETRY_COUNT = 3
DEFAULT_TIMEOUT_SECONDS = 20

CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
PUNCTUATION_RE = re.compile(r"[\s\W_]+", re.UNICODE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\b1\d{10}\b")
TOKEN_RE = re.compile(r"\b[A-Za-z0-9_\-]{20,}\b")
KEY_RE = re.compile(r"(sk-[A-Za-z0-9]{8,})")
BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9\-_.=]{8,}")


def setup_logging():
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    if root.handlers:
        return
    os.makedirs(LOG_DIR, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
    )
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root.setLevel(level)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


setup_logging()
logger = logging.getLogger("app")


def load_env_files():
    # Load .env (and .eny if present) without overriding existing env vars.
    for filename in (".env", ".eny"):
        path = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(path):
            continue
        loaded_keys = []
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.lower().startswith("export "):
                        line = line[7:].strip()
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    if not key:
                        continue
                    if (value.startswith('"') and value.endswith('"')) or (
                        value.startswith("'") and value.endswith("'")
                    ):
                        value = value[1:-1]
                    if os.getenv(key) in (None, ""):
                        os.environ[key] = value
                        loaded_keys.append(key)
        except OSError:
            continue
        if loaded_keys:
            logger.info("已加载环境变量文件: %s (%d项)", filename, len(loaded_keys))


load_env_files()

SYSTEM_PROMPT_CACHE = {"path": None, "mtime": None, "data": None}
USER_PROMPT_CACHE = {"path": None, "mtime": None, "text": None}
SYSTEM_PROMPT_LOCK = threading.Lock()
USER_PROMPT_LOCK = threading.Lock()
STEP_HEADING_RE = re.compile(r"^#{2,6}\s*STEP\s*(\d+)\s*[｜|]\s*(.+)$", re.IGNORECASE)
OPTION_HEADING_RE = re.compile(
    r"^(?:\*\*)?(示例方向|示例|可选项|可选描述|可选)(?:\*\*)?[:：]?$"
)
BULLET_RE = re.compile(r"^\s*[-*•]\s+(.+)$")
NUMBERED_RE = re.compile(r"^\s*\d+[.)]\s+(.+)$")

CONFIG_LOCK = threading.Lock()
RUNTIME_CONFIG = {
    "api_key": "",
    "model": "",
    "base_url": "",
    "log_llm": None,
    "prompt_path": "",
}


def get_system_prompt_path():
    env_path = os.getenv("SYSTEM_PROMPT_FILE", "").strip()
    if not env_path:
        env_path = os.getenv("PROMPT_FILE", "").strip()
    if env_path:
        return env_path
    return ""


def get_prompt_root():
    return PROMPT_DIR


def normalize_prompt_path(value):
    if not isinstance(value, str):
        return ""
    cleaned = value.replace("\\", "/").strip().lstrip("/")
    return cleaned


def resolve_prompt_path(relative_path):
    relative_path = normalize_prompt_path(relative_path)
    if not relative_path:
        return ""
    root = os.path.abspath(get_prompt_root())
    full_path = os.path.abspath(os.path.join(root, relative_path))
    if not full_path.startswith(root + os.sep):
        return ""
    if not os.path.isfile(full_path):
        return ""
    return full_path


def get_selected_prompt_path():
    with CONFIG_LOCK:
        runtime_path = normalize_prompt_path(RUNTIME_CONFIG.get("prompt_path", ""))
    env_path = normalize_prompt_path(os.getenv("PROMPT_PATH", ""))
    candidate = runtime_path or env_path
    if not candidate:
        return ""
    return resolve_prompt_path(candidate)


def build_prompt_tree(base_path):
    entries = []
    try:
        with os.scandir(base_path) as iterator:
            sorted_entries = sorted(
                iterator,
                key=lambda item: (item.is_file(), item.name.lower()),
            )
            for entry in sorted_entries:
                if entry.is_dir():
                    children = build_prompt_tree(entry.path)
                    if children:
                        entries.append(
                            {
                                "name": entry.name,
                                "type": "dir",
                                "children": children,
                            }
                        )
                elif entry.is_file() and entry.name.lower().endswith(".md"):
                    rel_path = os.path.relpath(entry.path, get_prompt_root())
                    entries.append(
                        {
                            "name": entry.name,
                            "type": "file",
                            "path": normalize_prompt_path(rel_path),
                        }
                    )
    except OSError:
        return []
    return entries


def get_user_prompt_path():
    env_path = os.getenv("USER_PROMPT_FILE", "").strip()
    if env_path:
        return env_path
    fallback = os.path.join(BASE_DIR, "UserPrompt.md")
    if os.path.isfile(fallback):
        return fallback
    fallback = os.path.join(BASE_DIR, "user_prompt.md")
    if os.path.isfile(fallback):
        return fallback
    return ""


def parse_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
        return None
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
            return True
        if candidate in {"0", "false", "no", "n", "off", "disable", "disabled"}:
            return False
    return None


def get_env_int(*names, default=DEFAULT_TIMEOUT_SECONDS):
    for name in names:
        raw = os.getenv(name, "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            continue
        if value > 0:
            return value
    return default


TIMEOUT_SECONDS = get_env_int("TIMEOUT_S", "API_TIMEOUT_S")


def get_effective_config():
    with CONFIG_LOCK:
        runtime = dict(RUNTIME_CONFIG)
    api_key = runtime.get("api_key") or os.getenv("API_KEY", "").strip()
    model = runtime.get("model") or os.getenv("MODEL", "").strip() or DEFAULT_MODEL
    base_url = (
        runtime.get("base_url")
        or os.getenv("BASE_URL", "").strip()
        or DEFAULT_BASE_URL
    )
    log_llm = runtime.get("log_llm")
    if log_llm is None:
        log_llm = parse_bool(os.getenv("API_LOG_LLM", "").strip())
        if log_llm is None:
            log_llm = parse_bool(os.getenv("LOG_LLM", "").strip())
    if log_llm is None:
        log_llm = False
    prompt_path = normalize_prompt_path(runtime.get("prompt_path", "")) or normalize_prompt_path(
        os.getenv("PROMPT_PATH", "")
    )
    return {
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "log_llm": log_llm,
        "prompt_path": prompt_path,
    }


def get_effective_image_config():
    return {
        "api_key": os.getenv("IMG_API_KEY", "").strip()
        or os.getenv("OPENAI_API_KEY", "").strip(),
        "model": os.getenv("IMG_MODEL", "").strip()
        or os.getenv("OPENAI_IMAGE_MODEL", "").strip()
        or os.getenv("OPENAI_MODEL", "").strip(),
        "base_url": os.getenv("IMG_BASE_URL", "").strip()
        or os.getenv("OPENAI_BASE_URL", "").strip(),
    }


def update_runtime_config(payload):
    api_key = payload.get("api_key") if "api_key" in payload else None
    model = payload.get("model") if "model" in payload else None
    base_url = payload.get("base_url") if "base_url" in payload else None
    prompt_path = payload.get("prompt_path") if "prompt_path" in payload else None
    log_llm_provided = "log_llm" in payload
    log_llm = payload.get("log_llm") if log_llm_provided else None
    if api_key is not None:
        api_key = normalize_text(api_key, MAX_OPTION_LEN)
    if model is not None:
        model = normalize_text(model, MAX_OPTION_LEN)
    if base_url is not None:
        base_url = normalize_text(base_url, MAX_CONTEXT_LEN)
        if base_url and not base_url.startswith("https://"):
            raise ValueError("BASE_URL 必须使用 https://")
    if prompt_path is not None:
        prompt_path = normalize_prompt_path(prompt_path)
        if prompt_path and not resolve_prompt_path(prompt_path):
            raise ValueError("提示词文件不存在或无权限")
    if log_llm_provided:
        if log_llm is None or log_llm == "":
            log_llm = None
        else:
            parsed = parse_bool(log_llm)
            if parsed is None:
                raise ValueError("log_llm 必须为布尔值")
            log_llm = parsed
    with CONFIG_LOCK:
        if api_key is not None:
            RUNTIME_CONFIG["api_key"] = api_key
        if model is not None:
            RUNTIME_CONFIG["model"] = model
        if base_url is not None:
            RUNTIME_CONFIG["base_url"] = base_url
        if prompt_path is not None:
            RUNTIME_CONFIG["prompt_path"] = prompt_path
        if log_llm_provided:
            RUNTIME_CONFIG["log_llm"] = log_llm


def render_template(template, values):
    rendered = template or ""
    for key, value in values.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value or "")
    return rendered.strip()


def parse_step_blocks(text):
    steps = []
    current = None
    buffer = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = STEP_HEADING_RE.match(line)
        if match:
            if current:
                current["content"] = "\n".join(buffer).strip()
                steps.append(current)
            current = {
                "number": int(match.group(1)),
                "title": match.group(2).strip(),
            }
            buffer = []
        else:
            buffer.append(raw_line)
    if current:
        current["content"] = "\n".join(buffer).strip()
        steps.append(current)
    return steps


def summarize_step_block(content):
    for line in content.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if set(candidate) <= {"-"}:
            continue
        if candidate.startswith("**") and candidate.endswith("**") and len(candidate.strip("*")) <= 8:
            continue
        if candidate.startswith("#"):
            continue
        if len(candidate) > 120:
            candidate = candidate[:120] + "..."
        return candidate
    return ""


def safe_filename(name):
    cleaned = re.sub(r'[\\/:*?"<>|｜]', "", name).strip()
    if not cleaned:
        cleaned = "step-output"
    return f"{cleaned}.md"


def extract_doc_title(content):
    match = re.search(r"[《](.+?)[》]", content)
    if match:
        return match.group(1).strip()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            line = line.lstrip("#").strip()
        if not line:
            continue
        if "文档" in line or "说明" in line:
            return line.strip("《》")
    return ""

def extract_step_options(content):
    options = []
    capture = False
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            if capture:
                capture = False
            continue
        if OPTION_HEADING_RE.match(line):
            capture = True
            continue
        if line.startswith("#"):
            capture = False
            continue
        if capture:
            match = BULLET_RE.match(line) or NUMBERED_RE.match(line)
            if match:
                option = match.group(1).strip()
                if option:
                    options.append(option)
            else:
                capture = False
    return options


def build_step_meta(step, options, doc_title):
    number = step["number"]
    title = step["title"]
    display_title_text = title
    if doc_title and ("交付物" in title or re.search(r"D\\d+", title, re.IGNORECASE)):
        display_title_text = doc_title
        if "文档" not in display_title_text:
            display_title_text = f"{display_title_text}文档"
        if "可选" in title and "可选" not in display_title_text:
            display_title_text = f"{display_title_text}（可选）"
    display_title = f"STEP {number}｜{display_title_text}"
    block_summary = summarize_step_block(step.get("content", ""))
    question = block_summary or f"请根据提示词输出 {display_title} 的内容。"
    title_hint = title
    if number == 1 or "澄清" in title_hint or "反问" in title_hint:
        input_label = "澄清问题答案（按 Q1/Q2… 作答）"
        input_placeholder = "示例：Q1：是/否；Q2：A/B..."
        output_label = "澄清问题"
        output_placeholder = "点击“生成内容”生成澄清问题。"
    elif number == 2 or "假设" in title_hint:
        input_label = "确认后的假设清单"
        input_placeholder = "可编辑或补充假设（如无需假设可保留“无需假设”）"
        output_label = "模型建议假设"
        output_placeholder = "点击“生成内容”生成假设清单。"
    else:
        input_label = "补充说明（可选）"
        input_placeholder = "如需补充关键信息，可写在这里。"
        output_label = "生成结果"
        output_placeholder = "点击“生成内容”生成本步骤结果。"
    download_base = display_title_text or display_title
    meta = {
        "id": f"step_{number}",
        "number": number,
        "title": display_title,
        "question": question,
        "input_label": input_label,
        "input_placeholder": input_placeholder,
        "output_label": output_label,
        "output_placeholder": output_placeholder,
        "generate": True,
        "output_visible": True,
        "download_name": safe_filename(download_base),
    }
    if options:
        meta["options"] = options
    return meta


def load_system_prompt_data(path_override=None):
    path = path_override or get_system_prompt_path()
    if not path:
        path = get_selected_prompt_path()
    if not path:
        raise ValueError("未选择提示词文件")
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        raise ValueError(f"系统提示词文件不存在: {path}") from exc
    with SYSTEM_PROMPT_LOCK:
        cache = SYSTEM_PROMPT_CACHE
        if cache["path"] == path and cache["mtime"] == mtime and cache["data"]:
            return cache["data"]
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
        steps = parse_step_blocks(text)
        step_blocks = {}
        step_meta = []
        step0_block = ""
        assumption_step_id = ""
        for step in steps:
            if step["number"] == 0:
                step0_block = step.get("content", "")
                continue
            content = step.get("content", "")
            options = extract_step_options(content)
            doc_title = extract_doc_title(content)
            if not doc_title:
                doc_title = extract_doc_title(step.get("title", ""))
            meta = build_step_meta(step, options, doc_title)
            optional = "可选" in step.get("title", "")
            if optional:
                meta["optional"] = True
                meta["optional_label"] = step.get("title", "")
            step_id = meta["id"]
            if step_id in step_blocks:
                step_id = f"{step_id}_{len(step_blocks)}"
                meta["id"] = step_id
            step_blocks[step_id] = step.get("content", "")
            step_meta.append(meta)
            if not assumption_step_id and (step["number"] == 2 or "假设" in step["title"]):
                assumption_step_id = step_id
        data = {
            "base_prompt": text.strip(),
            "steps": step_meta,
            "step_blocks": step_blocks,
            "step0_block": step0_block,
            "assumption_step_id": assumption_step_id,
        }
        SYSTEM_PROMPT_CACHE.update({"path": path, "mtime": mtime, "data": data})
        logger.info("系统提示词已加载: %s (steps=%d)", path, len(step_meta))
        return data


def load_user_prompt_text():
    path = get_user_prompt_path()
    if not path:
        return ""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        logger.warning("用户提示词文件不存在: %s", path)
        return ""
    with USER_PROMPT_LOCK:
        cache = USER_PROMPT_CACHE
        if cache["path"] == path and cache["mtime"] == mtime and cache["text"] is not None:
            return cache["text"]
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read().strip()
        USER_PROMPT_CACHE.update({"path": path, "mtime": mtime, "text": text})
        if text:
            logger.info("用户提示词已加载: %s (chars=%d)", path, len(text))
        else:
            logger.info("用户提示词已加载: %s (空内容)", path)
        return text


def normalize_text(value, max_len=None):
    if not isinstance(value, str):
        return ""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = CONTROL_RE.sub("", value).strip()
    if max_len and len(value) > max_len:
        value = value[:max_len]
    return value


def normalize_for_compare(text):
    cleaned = normalize_text(text)
    cleaned = PUNCTUATION_RE.sub("", cleaned).lower()
    return cleaned


def redact_for_log(text):
    redacted = text
    redacted = BEARER_RE.sub("Bearer ***", redacted)
    redacted = KEY_RE.sub("sk-***", redacted)
    redacted = EMAIL_RE.sub("***@***", redacted)
    redacted = PHONE_RE.sub("***", redacted)
    redacted = TOKEN_RE.sub("***", redacted)
    return redacted


def build_prompt_preview(prompt, limit=80):
    cleaned = normalize_text(prompt)
    redacted = redact_for_log(cleaned)
    if len(redacted) > limit:
        return f"{redacted[:limit]}..."
    return redacted


def normalize_state(raw_state):
    if not isinstance(raw_state, dict):
        return {}
    requirement = normalize_text(raw_state.get("requirement", ""), MAX_REQUIREMENT_LEN)
    facts = normalize_text(raw_state.get("facts", ""), MAX_CONTEXT_LEN)
    raw_inputs = raw_state.get("step_inputs", {})
    raw_outputs = raw_state.get("step_outputs", {})
    raw_options = raw_state.get("step_options", {})
    raw_history = raw_state.get("step_history", {})
    step_inputs = {}
    step_outputs = {}
    step_options = {}
    step_history = {}
    if isinstance(raw_inputs, dict):
        for key, value in raw_inputs.items():
            step_inputs[str(key)] = normalize_text(value, MAX_CONTEXT_LEN)
    if isinstance(raw_outputs, dict):
        for key, value in raw_outputs.items():
            step_outputs[str(key)] = normalize_text(value, MAX_CONTEXT_LEN)
    if isinstance(raw_options, dict):
        for key, value in raw_options.items():
            items = []
            if isinstance(value, list):
                items = [normalize_text(str(item), MAX_OPTION_LEN) for item in value]
            elif isinstance(value, str):
                items = [normalize_text(value, MAX_OPTION_LEN)]
            items = [item for item in items if item]
            if items:
                step_options[str(key)] = items
    if isinstance(raw_history, dict):
        for key, entries in raw_history.items():
            if not isinstance(entries, list):
                continue
            normalized_entries = []
            for entry in entries[-MAX_HISTORY_ITEMS:]:
                if not isinstance(entry, dict):
                    continue
                item = {
                    "input": normalize_text(entry.get("input", ""), MAX_CONTEXT_LEN),
                    "output": normalize_text(entry.get("output", ""), MAX_CONTEXT_LEN),
                    "mode": normalize_text(entry.get("mode", ""), 16),
                    "ts": normalize_text(entry.get("ts", ""), 32),
                }
                if item["input"] or item["output"]:
                    normalized_entries.append(item)
            if normalized_entries:
                step_history[str(key)] = normalized_entries
    return {
        "requirement": requirement,
        "facts": facts,
        "step_inputs": step_inputs,
        "step_outputs": step_outputs,
        "step_options": step_options,
        "step_history": step_history,
    }


def normalize_messages(raw_messages):
    if not isinstance(raw_messages, list):
        return []
    normalized = []
    for item in raw_messages[-MAX_CHAT_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = normalize_text(str(item.get("role", "")), 16).lower()
        if role not in {"user", "assistant"}:
            continue
        content = normalize_text(item.get("content", ""), MAX_CONTEXT_LEN)
        if not content:
            continue
        normalized.append({"role": role, "content": content})
    return normalized


def normalize_chat_config(raw_config):
    if not isinstance(raw_config, dict):
        return {}
    api_key = normalize_text(raw_config.get("api_key", ""), MAX_CONTEXT_LEN)
    model = normalize_text(raw_config.get("model", ""), MAX_OPTION_LEN)
    base_url = normalize_text(raw_config.get("base_url", ""), MAX_CONTEXT_LEN)
    log_llm = raw_config.get("log_llm")
    prompt_path = normalize_prompt_path(raw_config.get("prompt_path", ""))
    if base_url and not base_url.startswith("https://"):
        raise ValueError("BASE_URL 必须使用 https://")
    if prompt_path and not resolve_prompt_path(prompt_path):
        raise ValueError("提示词文件不存在或无权限")
    parsed_log = parse_bool(log_llm)
    config = {}
    if api_key:
        config["api_key"] = api_key
    if model:
        config["model"] = model
    if base_url:
        config["base_url"] = base_url
    if parsed_log is not None:
        config["log_llm"] = parsed_log
    if prompt_path:
        config["prompt_path"] = prompt_path
    return config


def normalize_image_config(raw_config):
    if not isinstance(raw_config, dict):
        return {}
    api_key = normalize_text(raw_config.get("api_key", ""), MAX_CONTEXT_LEN)
    model = normalize_text(raw_config.get("model", ""), MAX_OPTION_LEN)
    base_url = normalize_text(raw_config.get("base_url", ""), MAX_CONTEXT_LEN)
    if base_url and not base_url.startswith("https://"):
        raise ValueError("IMG_BASE_URL 必须使用 https://")
    config = {}
    if api_key:
        config["api_key"] = api_key
    if model:
        config["model"] = model
    if base_url:
        config["base_url"] = base_url
    return config


def get_llm_config():
    config = get_effective_config()
    api_key = config.get("api_key", "")
    if not api_key:
        raise ValueError("缺少环境变量 API_KEY")
    model = config.get("model", "") or DEFAULT_MODEL
    base_url = config.get("base_url", "") or DEFAULT_BASE_URL
    log_llm = bool(config.get("log_llm"))
    if not base_url.startswith("https://"):
        raise ValueError("BASE_URL 必须使用 https://")
    logger.debug(
        "LLM配置检查: model=%s base_url=%s api_key_set=%s log_llm=%s",
        model,
        base_url,
        bool(api_key),
        log_llm,
    )
    return api_key, model, base_url, log_llm


def format_llm_messages(messages):
    parts = []
    for index, message in enumerate(messages or [], start=1):
        if not isinstance(message, dict):
            continue
        role = normalize_text(str(message.get("role", "")))
        content = message.get("content", "")
        content = normalize_text(str(content)) if content is not None else ""
        parts.append(f"[{index}] role={role}\n{content}")
    return "\n\n".join(parts).strip()


def log_llm_full_input(messages, tag, trace_id):
    formatted = format_llm_messages(messages)
    if formatted:
        logger.info("LLM完整输入 tag=%s trace=%s\n%s", tag, trace_id, formatted)


def log_llm_full_output(content, tag, trace_id):
    text = normalize_text(str(content)) if content is not None else ""
    logger.info("LLM完整输出 tag=%s trace=%s\n%s", tag, trace_id, text)


def call_llm(messages, temperature, tag="", trace_id=""):
    api_key, model, base_url, log_llm = get_llm_config()
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    msg_count = len(messages)
    msg_chars = sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict))
    logger.info(
        "LLM请求开始 tag=%s trace=%s model=%s msgs=%d chars=%d temp=%.2f",
        tag,
        trace_id,
        model,
        msg_count,
        msg_chars,
        temperature,
    )

    if log_llm:
        log_llm_full_input(messages, tag, trace_id)

    for attempt in range(RETRY_COUNT):
        attempt_start = time.monotonic()
        request = urllib.request.Request(base_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
            result = json.loads(body)
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            content = normalize_text(content, MAX_OUTPUT_LEN)
            if not content:
                raise ValueError("模型返回内容为空")
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.info(
                "LLM请求成功 tag=%s trace=%s attempt=%d elapsed_ms=%.0f resp_chars=%d",
                tag,
                trace_id,
                attempt + 1,
                elapsed_ms,
                len(content),
            )
            if log_llm:
                log_llm_full_output(content, tag, trace_id)
            return content
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.warning(
                "LLM请求HTTP错误 tag=%s trace=%s attempt=%d status=%s elapsed_ms=%.0f",
                tag,
                trace_id,
                attempt + 1,
                exc.code,
                elapsed_ms,
            )
            if retryable and attempt < RETRY_COUNT - 1:
                time.sleep(1.5 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.warning(
                "LLM请求失败 tag=%s trace=%s attempt=%d elapsed_ms=%.0f",
                tag,
                trace_id,
                attempt + 1,
                elapsed_ms,
            )
            if attempt < RETRY_COUNT - 1:
                time.sleep(1.5 ** attempt)
                continue
            raise


def call_llm_with_config(messages, temperature, config, tag="", trace_id=""):
    api_key = config.get("api_key", "")
    model = config.get("model", "") or DEFAULT_MODEL
    base_url = config.get("base_url", "") or DEFAULT_BASE_URL
    log_llm = bool(config.get("log_llm"))
    if not api_key:
        raise ValueError("缺少环境变量 API_KEY")
    if not base_url.startswith("https://"):
        raise ValueError("BASE_URL 必须使用 https://")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    msg_count = len(messages)
    msg_chars = sum(len(str(item.get("content", ""))) for item in messages if isinstance(item, dict))
    logger.info(
        "LLM请求开始 tag=%s trace=%s model=%s msgs=%d chars=%d temp=%.2f",
        tag,
        trace_id,
        model,
        msg_count,
        msg_chars,
        temperature,
    )

    if log_llm:
        log_llm_full_input(messages, tag, trace_id)

    for attempt in range(RETRY_COUNT):
        attempt_start = time.monotonic()
        request = urllib.request.Request(base_url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
            result = json.loads(body)
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            content = normalize_text(content, MAX_OUTPUT_LEN)
            if not content:
                raise ValueError("模型返回内容为空")
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.info(
                "LLM请求成功 tag=%s trace=%s attempt=%d elapsed_ms=%.0f resp_chars=%d",
                tag,
                trace_id,
                attempt + 1,
                elapsed_ms,
                len(content),
            )
            if log_llm:
                log_llm_full_output(content, tag, trace_id)
            return content
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.warning(
                "LLM请求HTTP错误 tag=%s trace=%s attempt=%d status=%s elapsed_ms=%.0f",
                tag,
                trace_id,
                attempt + 1,
                exc.code,
                elapsed_ms,
            )
            if retryable and attempt < RETRY_COUNT - 1:
                time.sleep(1.5 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.warning(
                "LLM请求失败 tag=%s trace=%s attempt=%d elapsed_ms=%.0f",
                tag,
                trace_id,
                attempt + 1,
                elapsed_ms,
            )
            if attempt < RETRY_COUNT - 1:
                time.sleep(1.5 ** attempt)
                continue
            raise


def build_image_url(base_url):
    cleaned = (base_url or "").rstrip("/")
    if cleaned.endswith(DEFAULT_IMAGE_ENDPOINT):
        return cleaned
    return f"{cleaned}{DEFAULT_IMAGE_ENDPOINT}"


def build_image_payload(prompt, model, base_url):
    payload = {"model": model, "prompt": prompt}
    if "volces" in (base_url or "").lower():
        payload["size"] = "2K"
        payload["watermark"] = False
    return payload


def summarize_image_result(result, images):
    summary = {
        "images": len(images),
        "types": {},
        "output_format": "",
        "data_items": 0,
        "total_tokens": None,
    }
    if isinstance(result, dict):
        summary["output_format"] = str(result.get("output_format", "") or "")
        data = result.get("data")
        if isinstance(data, list):
            summary["data_items"] = len(data)
        usage = result.get("usage")
        if isinstance(usage, dict):
            summary["total_tokens"] = usage.get("total_tokens")
    type_counts = {}
    for item in images:
        if not isinstance(item, dict):
            continue
        image_type = item.get("type", "unknown")
        type_counts[image_type] = type_counts.get(image_type, 0) + 1
    summary["types"] = type_counts
    return summary


def call_image_generation(prompt, config, trace_id=""):
    api_key = config.get("api_key", "")
    model = config.get("model", "")
    base_url = config.get("base_url", "")
    if not api_key:
        raise ValueError("缺少环境变量 IMG_API_KEY")
    if not base_url.startswith("https://"):
        raise ValueError("IMG_BASE_URL 必须使用 https://")
    if not model:
        raise ValueError("缺少 IMG_MODEL")
    url = build_image_url(base_url)
    payload = build_image_payload(prompt, model, base_url)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    provider = "volces" if "volces" in base_url.lower() else "generic"
    parsed_url = urllib.parse.urlparse(url)
    prompt_preview = build_prompt_preview(prompt, limit=80)
    logger.info(
        "生图请求开始 trace=%s provider=%s host=%s model=%s chars=%d size=%s watermark=%s prompt_preview=%s",
        trace_id,
        provider,
        parsed_url.netloc,
        model,
        len(prompt),
        payload.get("size"),
        payload.get("watermark"),
        prompt_preview,
    )
    for attempt in range(RETRY_COUNT):
        attempt_start = time.monotonic()
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
            result = json.loads(body)
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.info(
                "生图请求成功 trace=%s attempt=%d elapsed_ms=%.0f",
                trace_id,
                attempt + 1,
                elapsed_ms,
            )
            return result
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {429, 500, 502, 503, 504}
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.warning(
                "生图请求HTTP错误 trace=%s attempt=%d status=%s elapsed_ms=%.0f",
                trace_id,
                attempt + 1,
                exc.code,
                elapsed_ms,
            )
            if retryable and attempt < RETRY_COUNT - 1:
                time.sleep(1.5 ** attempt)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError):
            elapsed_ms = (time.monotonic() - attempt_start) * 1000
            logger.warning(
                "生图请求失败 trace=%s attempt=%d elapsed_ms=%.0f",
                trace_id,
                attempt + 1,
                elapsed_ms,
            )
            if attempt < RETRY_COUNT - 1:
                time.sleep(1.5 ** attempt)
                continue
            raise


def parse_image_response(result):
    images = []
    if isinstance(result, dict):
        output_format = str(result.get("output_format", "png") or "png").lower()
        data = result.get("data")
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                if item.get("url"):
                    images.append(
                        {
                            "type": "url",
                            "value": str(item.get("url")),
                            "format": output_format,
                        }
                    )
                elif item.get("b64_json"):
                    images.append(
                        {
                            "type": "b64",
                            "value": str(item.get("b64_json")),
                            "format": output_format,
                        }
                    )
    return images


def build_facts_user_prompt(requirement, step0_block, user_prompt_template):
    default_instructions = (
        "任务：仅提取用户明确写出的事实，禁止推断或补全。\n"
        "输出格式（内部）：\n"
        "- 系统目标：...\n"
        "- 涉及物品类型：...\n"
        "- 使用角色：...\n"
        "- 已明确的核心关注点：..."
    )
    template_values = {
        "requirement": requirement,
        "facts": "",
        "context": "",
        "input": "",
        "assumptions": "",
        "options": "",
        "step_title": "STEP 0",
        "step_id": "step_0",
        "step_number": "0",
        "step_question": "",
        "step_block": "",
        "step_instruction": "",
    }
    rendered_user_prompt = render_template(user_prompt_template, template_values)
    rendered = render_template(step0_block, template_values)
    parts = []
    if rendered_user_prompt:
        parts.append(rendered_user_prompt)
    parts.append(rendered or default_instructions)
    if "原始需求描述" not in rendered and "{{requirement}}" not in user_prompt_template:
        parts.append(f"原始需求描述：\n{requirement}")
    parts.append("输出要求：只输出事实提取结果，不要其他说明。")
    return "\n\n".join(parts)


def ensure_facts(state, prompt_data, user_prompt_template, trace_id=""):
    facts = state.get("facts", "")
    if facts:
        return facts, False
    requirement = state.get("requirement", "")
    if not requirement:
        return "", False
    system = prompt_data.get("base_prompt", "")
    user = build_facts_user_prompt(
        requirement, prompt_data.get("step0_block", ""), user_prompt_template
    )
    facts = call_llm(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        tag="STEP0_FACTS",
        trace_id=trace_id,
    )
    return facts, True


def build_context_for_step(state, steps, current_step_id):
    parts = [f"原始需求描述：\n{state.get('requirement', '')}"]
    facts = state.get("facts", "")
    if facts:
        parts.append(f"内部事实提取（系统态）：\n{facts}")
    history = state.get("step_history", {})
    for step in steps:
        step_id = step["id"]
        if step_id == current_step_id:
            break
        entries = history.get(step_id, []) if isinstance(history, dict) else []
        if not entries:
            output = state.get("step_outputs", {}).get(step_id, "")
            if output:
                parts.append(f"{step['title']} 输出：\n{output}")
            user_input = state.get("step_inputs", {}).get(step_id, "")
            if user_input:
                parts.append(f"{step['title']} 用户补充：\n{user_input}")
        if entries:
            slice_entries = entries[-MAX_HISTORY_IN_CONTEXT:]
            history_lines = []
            for entry in slice_entries:
                if not isinstance(entry, dict):
                    continue
                mode = entry.get("mode", "")
                ts = entry.get("ts", "")
                prefix = f"[{mode} {ts}]".strip()
                input_text = entry.get("input", "")
                output_text = entry.get("output", "")
                if input_text:
                    history_lines.append(f"{prefix} 输入：{input_text}")
                if output_text:
                    history_lines.append(f"{prefix} 输出：{output_text}")
            if history_lines:
                parts.append(f"{step['title']} 历史记录：\n" + "\n".join(history_lines))
        options = state.get("step_options", {}).get(step_id, [])
        if options:
            options_text = "\n".join(f"- {item}" for item in options)
            parts.append(f"{step['title']} 可选描述选择：\n{options_text}")
    return "\n\n".join(parts)


def build_step_user_prompt(
    step_meta,
    step_block,
    context,
    user_input,
    assumptions,
    requirement,
    facts,
    selected_options,
    user_prompt_template,
    current_output,
    mode,
):
    options_text = ""
    if selected_options:
        options_text = "\n".join(f"- {item}" for item in selected_options)
    current_output = normalize_text(current_output, MAX_CONTEXT_LEN)
    template_values = {
        "context": context,
        "input": user_input,
        "assumptions": assumptions,
        "requirement": requirement,
        "facts": facts,
        "options": options_text,
        "current_output": current_output,
        "step_title": step_meta.get("title", ""),
        "step_id": step_meta.get("id", ""),
        "step_number": str(step_meta.get("number", "")),
        "step_question": step_meta.get("question", ""),
    }
    rendered_block = render_template(step_block, template_values)
    template_values["step_block"] = rendered_block
    template_values["step_instruction"] = rendered_block
    rendered_template = render_template(user_prompt_template, template_values)
    template_has_context = "{{context}}" in user_prompt_template
    template_has_input = "{{input}}" in user_prompt_template
    template_has_assumptions = "{{assumptions}}" in user_prompt_template
    template_has_options = "{{options}}" in user_prompt_template
    template_has_step_block = (
        "{{step_block}}" in user_prompt_template
        or "{{step_instruction}}" in user_prompt_template
    )
    template_has_step_title = (
        "{{step_title}}" in user_prompt_template
        or "{{step_id}}" in user_prompt_template
        or "{{step_number}}" in user_prompt_template
    )
    template_has_current_output = (
        "{{current_output}}" in user_prompt_template
        or "{{current_output}}" in step_block
    )
    has_context = template_has_context or "{{context}}" in step_block
    has_input = template_has_input or "{{input}}" in step_block
    has_assumptions = template_has_assumptions or "{{assumptions}}" in step_block
    has_options = template_has_options or "{{options}}" in step_block
    parts = []
    if rendered_template:
        parts.append(rendered_template)
    if not template_has_step_title:
        parts.append(f"当前执行：{step_meta['title']}")
    if mode == "append":
        parts.append("当前为追加思考模式：请基于已有结果补充，不要重复已有内容。")
        parts.append("必须新增至少1条不同内容；如无法新增，请仅输出：无新增内容。")
    parts.append("请严格遵守系统提示词中的流程与约束，仅输出本步骤结果。")
    if rendered_block and not template_has_step_block:
        parts.append(f"步骤说明（摘自提示词）：\n{rendered_block}")
    if context and not has_context:
        parts.append(f"已有信息：\n{context}")
    if user_input and not has_input:
        parts.append(f"用户补充：\n{user_input}")
    if assumptions and not has_assumptions:
        parts.append(f"当前假设：\n{assumptions}")
    if options_text and not has_options:
        parts.append(f"可选描述选择：\n{options_text}")
    if current_output and mode == "append" and not template_has_current_output:
        parts.append(f"已有结果：\n{current_output}")
    if mode == "append":
        parts.append("输出要求：中文，只输出新增补充内容，不要重复已有结果。")
    else:
        parts.append("输出要求：中文，只输出本步骤内容，不要其他说明。")
    return "\n\n".join(parts)


def get_assumptions_text(state, prompt_data):
    step_id = prompt_data.get("assumption_step_id")
    if not step_id:
        return ""
    return (
        state.get("step_inputs", {}).get(step_id, "")
        or state.get("step_outputs", {}).get(step_id, "")
    )


def generate_step_output(
    step_id,
    state,
    prompt_data,
    user_prompt_template,
    current_output,
    mode,
    trace_id="",
):
    steps = prompt_data.get("steps", [])
    step_meta = next((step for step in steps if step["id"] == step_id), None)
    if not step_meta:
        raise ValueError("步骤无效")
    context = build_context_for_step(state, steps, step_id)
    user_input = state.get("step_inputs", {}).get(step_id, "")
    assumptions = get_assumptions_text(state, prompt_data)
    selected_options = state.get("step_options", {}).get(step_id, [])
    step_block = prompt_data.get("step_blocks", {}).get(step_id, "")
    user = build_step_user_prompt(
        step_meta,
        step_block,
        context,
        user_input,
        assumptions,
        state.get("requirement", ""),
        state.get("facts", ""),
        selected_options,
        user_prompt_template,
        current_output,
        mode,
    )
    system = prompt_data.get("base_prompt", "")
    temperature = 0.2 if step_meta["number"] in {1, 2} else 0.3
    return call_llm(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        tag=f"STEP{step_meta['number']}_OUTPUT",
        trace_id=trace_id,
    )


class RequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/prompts":
            return self.handle_prompts()
        if path == "/api/image_config":
            return self.handle_image_config_get()
        if path == "/api/steps":
            return self.handle_steps()
        if path == "/api/config":
            return self.handle_config_get()
        if path in {"", "/"}:
            return self.serve_file("index.html", "text/html; charset=utf-8")
        if path == "/app.js":
            return self.serve_file("app.js", "text/javascript; charset=utf-8")
        if path == "/style.css":
            return self.serve_file("style.css", "text/css; charset=utf-8")
        if not path.startswith("/api/"):
            return self.serve_file("index.html", "text/html; charset=utf-8")
        self.send_error(404, "Not Found")

    def do_POST(self):
        if self.path == "/api/config":
            return self.handle_config_set()
        if self.path == "/api/image_generate":
            return self.handle_image_generate()
        if self.path == "/api/chat":
            return self.handle_chat()
        if self.path == "/api/run_step":
            return self.handle_run_step()
        self.send_error(404, "Not Found")

    def handle_steps(self):
        try:
            prompt_data = load_system_prompt_data()
            steps = [
                {
                    "id": "input",
                    "title": "需求输入",
                    "question": "请粘贴或输入原始需求描述。",
                    "input_label": "原始需求描述",
                    "input_placeholder": "请尽量完整描述业务背景、目标与边界。",
                    "output_visible": False,
                    "generate": False,
                }
            ]
            steps.extend(prompt_data.get("steps", []))
            response = {
                "steps": steps,
                "assumption_step_id": prompt_data.get("assumption_step_id", ""),
            }
            return self.send_json(response)
        except ValueError as exc:
            logger.warning("步骤配置加载失败: %s", exc)
            return self.send_json({"error": str(exc)}, status=500)

    def handle_config_get(self):
        try:
            config = get_effective_config()
            return self.send_json(config)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, status=400)

    def handle_image_config_get(self):
        config = get_effective_image_config()
        return self.send_json(config)

    def handle_prompts(self):
        try:
            root = get_prompt_root()
            if not os.path.isdir(root):
                return self.send_json({"error": "prompt 目录不存在"}, status=400)
            tree = build_prompt_tree(root)
            selected = normalize_prompt_path(get_effective_config().get("prompt_path", ""))
            return self.send_json({"tree": tree, "selected": selected})
        except Exception:
            logger.exception("提示词列表加载失败")
            return self.send_json({"error": "提示词列表加载失败"}, status=500)

    def handle_config_set(self):
        try:
            payload = self.read_json()
            update_runtime_config(payload)
            config = get_effective_config()
            logger.info(
                "配置已更新 api_key_set=%s model=%s base_url=%s log_llm=%s",
                bool(config.get("api_key")),
                config.get("model", ""),
                config.get("base_url", ""),
                bool(config.get("log_llm")),
            )
            return self.send_json(config)
        except ValueError as exc:
            logger.warning("配置更新失败: %s", exc)
            return self.send_json({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("配置更新异常")
            return self.send_json({"error": "配置更新失败"}, status=500)

    def handle_run_step(self):
        try:
            payload = self.read_json()
            step_id = normalize_text(payload.get("step_id", ""), 64)
            if not step_id:
                return self.send_json({"error": "缺少步骤标识"}, status=400)
            mode = normalize_text(payload.get("mode", ""), 32).lower()
            if mode not in {"append", "regenerate", "generate"}:
                mode = "regenerate"
            run_input = normalize_text(payload.get("run_input", ""), MAX_CONTEXT_LEN)
            state = normalize_state(payload.get("state", {}))
            trace_id = uuid.uuid4().hex[:12]
            step_input_len = len(state.get("step_inputs", {}).get(step_id, ""))
            output_count = sum(1 for value in state.get("step_outputs", {}).values() if value)
            option_count = len(state.get("step_options", {}).get(step_id, []))
            logger.info(
                "步骤请求开始 trace=%s step=%s mode=%s req_len=%d input_len=%d outputs=%d options=%d",
                trace_id,
                step_id,
                mode,
                len(state.get("requirement", "")),
                step_input_len,
                output_count,
                option_count,
            )
            if step_id == "input":
                return self.send_json({"error": "该步骤无需生成"}, status=400)
            if not state.get("requirement"):
                return self.send_json({"error": "请先填写原始需求描述"}, status=400)
            prompt_data = load_system_prompt_data()
            user_prompt = load_user_prompt_text()
            valid_steps = {step["id"] for step in prompt_data.get("steps", [])}
            if step_id not in valid_steps:
                return self.send_json({"error": "步骤无效"}, status=400)
            if mode == "append" and not state.get("step_outputs", {}).get(step_id, ""):
                return self.send_json({"error": "请先生成本步骤内容，再进行追加思考"}, status=400)
            facts, updated = ensure_facts(
                state, prompt_data, user_prompt, trace_id=trace_id
            )
            if facts:
                state["facts"] = facts
            current_output = state.get("step_outputs", {}).get(step_id, "")
            output = generate_step_output(
                step_id,
                state,
                prompt_data,
                user_prompt,
                current_output,
                mode,
                trace_id=trace_id,
            )
            if mode == "append" and current_output:
                existing_norm = normalize_for_compare(current_output)
                output_norm = normalize_for_compare(output)
                if not output_norm or output_norm in existing_norm or output_norm == existing_norm:
                    output = "无新增内容"
            history = state.get("step_history", {})
            if not isinstance(history, dict):
                history = {}
            entry = {
                "input": run_input or state.get("step_inputs", {}).get(step_id, ""),
                "output": output,
                "mode": mode,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            existing = history.get(step_id, [])
            if not isinstance(existing, list):
                existing = []
            existing.append(entry)
            if len(existing) > MAX_HISTORY_ITEMS:
                existing = existing[-MAX_HISTORY_ITEMS:]
            history[step_id] = existing
            state["step_history"] = history
            response = {"output": output, "step_history": history}
            if updated:
                response["facts"] = facts
            logger.info(
                "步骤请求完成 trace=%s step=%s mode=%s output_len=%d facts_updated=%s",
                trace_id,
                step_id,
                mode,
                len(output),
                updated,
            )
            return self.send_json(response)
        except ValueError as exc:
            logger.warning("步骤请求校验失败: %s", exc)
            return self.send_json({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("步骤请求异常")
            return self.send_json({"error": "模型调用失败，请检查配置或稍后重试"}, status=500)

    def handle_chat(self):
        try:
            payload = self.read_json()
            messages = normalize_messages(payload.get("messages", []))
            if not messages:
                return self.send_json({"error": "对话内容为空"}, status=400)
            config_override = normalize_chat_config(payload.get("config", {}))
            base_config = get_effective_config()
            chat_config = {
                "api_key": config_override.get("api_key") or base_config.get("api_key", ""),
                "model": config_override.get("model") or base_config.get("model", ""),
                "base_url": config_override.get("base_url") or base_config.get("base_url", ""),
                "log_llm": config_override.get("log_llm")
                if "log_llm" in config_override
                else base_config.get("log_llm", False),
            }
            prompt_path = config_override.get("prompt_path") or base_config.get("prompt_path", "")
            prompt_full = resolve_prompt_path(prompt_path) if prompt_path else get_selected_prompt_path()
            if not prompt_full:
                return self.send_json({"error": "未选择提示词文件"}, status=400)
            prompt_data = load_system_prompt_data(prompt_full)
            system_prompt = prompt_data.get("base_prompt", "")
            if not system_prompt:
                return self.send_json({"error": "系统提示词为空"}, status=500)
            trace_id = uuid.uuid4().hex[:12]
            logger.info(
                "对话请求开始 trace=%s msgs=%d chars=%d",
                trace_id,
                len(messages),
                sum(len(item.get("content", "")) for item in messages),
            )
            reply = call_llm_with_config(
                [{"role": "system", "content": system_prompt}] + messages,
                temperature=0.3,
                config=chat_config,
                tag="CHAT",
                trace_id=trace_id,
            )
            logger.info(
                "对话请求完成 trace=%s reply_len=%d",
                trace_id,
                len(reply or ""),
            )
            return self.send_json({"reply": reply})
        except ValueError as exc:
            logger.warning("对话请求校验失败: %s", exc)
            return self.send_json({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("对话请求异常")
            return self.send_json({"error": "模型调用失败，请检查配置或稍后重试"}, status=500)

    def handle_image_generate(self):
        try:
            payload = self.read_json()
            prompt = normalize_text(payload.get("prompt", ""), MAX_CONTEXT_LEN)
            if not prompt:
                return self.send_json({"error": "提示词为空"}, status=400)
            config_override = normalize_image_config(payload.get("config", {}))
            base_config = get_effective_image_config()
            image_config = {
                "api_key": config_override.get("api_key") or base_config.get("api_key", ""),
                "model": config_override.get("model") or base_config.get("model", ""),
                "base_url": config_override.get("base_url") or base_config.get("base_url", ""),
            }
            trace_id = uuid.uuid4().hex[:12]
            result = call_image_generation(prompt, image_config, trace_id=trace_id)
            images = parse_image_response(result)
            summary = summarize_image_result(result, images)
            logger.info("生图响应摘要 trace=%s summary=%s", trace_id, summary)
            reply = (
                f"已生成 {len(images)} 张图片。"
                if images
                else "未返回图片数据。"
            )
            return self.send_json({"reply": reply, "images": images})
        except ValueError as exc:
            logger.warning("生图请求校验失败: %s", exc)
            return self.send_json({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("生图请求异常")
            return self.send_json({"error": "生图调用失败，请检查配置或稍后重试"}, status=500)

    def serve_file(self, filename, content_type):
        path = os.path.join(WEB_DIR, filename)
        if not os.path.isfile(path):
            self.send_error(404, "Not Found")
            return
        with open(path, "rb") as handle:
            data = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("请求体为空")
        if length > MAX_BODY_BYTES:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("JSON 格式错误") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON 必须为对象")
        return payload

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.info("HTTP %s - %s", self.address_string(), format % args)


def run_server():
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"服务已启动: http://{host}:{port}")
    logger.info("服务启动 host=%s port=%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    run_server()
