# PromptExecutor

## 项目简介
- 轻量级本地 HTTP 服务，用于托管提示词、调用大模型对话与生图，并内置前端工作台。  
- 仅依赖 Python 标准库，在 Windows 10/11 上直接运行，无需额外安装后端框架。  
- 支持在 UI 中切换提示词、管理 API Key，查看历史输入，以及通过接口驱动多步骤产出。

## 功能特性
- 对话工作台：发送对话消息，支持开启完整 LLM 输入/输出日志（谨慎用于生产）。  
- 提示词管理：自动扫描 `prompt/` 下的 Markdown 文件，树形展示并可选取为系统提示词。  
- 多步骤执行接口：`/api/steps` + `/api/run_step` 按提示词中的 STEP 区块驱动产出，可保存步骤历史与补充上下文。  
- 生图能力：通过 `/api/image_generate` 调用第三方图片生成接口，支持火山方舟等带水印/尺寸参数的服务。  
- 配置与日志：运行时动态更新模型配置，日志写入 `logs/app.log`，滚动备份。

## 目录结构
- `main.py`：后端服务与 API 入口。  
- `web/`：静态前端（`index.html`、`app.js`、`style.css`）。  
- `prompt/`：内置提示词示例，新增 `.md` 文件即可在界面中出现。  
- `logs/`：运行日志目录（自动创建）。  
- `.env`：示例环境变量文件，请按需替换为实际密钥。

## 快速开始
1) 准备环境：安装 Python 3.10+；在 PowerShell 中进入仓库目录。  
2) （可选）创建虚拟环境：  
   ```powershell
   python -m venv venv
   .\venv\Scripts\activate
   ```  
3) 配置环境变量：复制 `.env` 或手动设置，确保使用自己的密钥与 HTTPS 接口；不要提交真实密钥。  
4) 启动服务：  
   ```powershell
   python .\main.py
   ```  
   默认监听 `http://127.0.0.1:8000`，可通过 `HOST`、`PORT` 环境变量调整。  
5) 打开浏览器：访问上述地址，点击“语言模型设置/生图模型设置”填写 Key 与模型；在提示词列表选择要使用的 Markdown 文件后即可开始对话或调用接口。

## 主要 API
- `GET /api/config`：获取当前语言模型配置。  
- `POST /api/config`：设置语言模型配置，字段可选：`api_key`、`model`、`base_url`、`prompt_path`（相对 `prompt/`）以及 `log_llm`。  
- `GET /api/prompts`：返回提示词树 `{tree, selected}`。  
- `GET /api/steps`：基于当前系统提示词返回步骤元信息；前置条件是已选择有效的提示词文件。  
- `POST /api/run_step`：执行单个步骤，示例负载：
  ```json
  {
    "step_id": "step_1",
    "mode": "generate",
    "run_input": "",
    "state": {
      "requirement": "原始需求描述",
      "step_inputs": {"step_1": "可选补充"},
      "step_outputs": {},
      "step_options": {}
    }
  }
  ```
- `POST /api/chat`：对话接口，负载 `{"messages":[{"role":"user","content":"..."}], "config":{...可选覆盖...}}`。  
- `GET /api/image_config`：获取生图配置。  
- `POST /api/image_generate`：生图接口，负载 `{"prompt":"...", "config":{"api_key":"...", "model":"...", "base_url":"https://..."}}`，返回图片 base64/URL 列表。

## 环境变量说明
- `API_KEY`：语言模型密钥（必填）。  
- `MODEL`：语言模型名称，默认 `mimo-v2-flash`。  
- `BASE_URL`：对话接口地址（必须为 `https://`）。  
- `LOG_LLM`：`true/false`，是否记录完整请求/响应。  
- `PROMPT_PATH`：相对 `prompt/` 的提示词文件路径；也可在 UI 中动态选择。  
- `SYSTEM_PROMPT_FILE`/`PROMPT_FILE`：指定绝对路径的系统提示词（覆盖 `PROMPT_PATH`）。  
- `USER_PROMPT_FILE`：可选用户提示词模板文件。  
- `IMG_API_KEY`、`IMG_MODEL`、`IMG_BASE_URL`：生图所需配置（`IMG_BASE_URL` 同样要求 `https://`）。  
- `HOST`、`PORT`：服务监听地址与端口。  
- `LOG_LEVEL`：日志级别（默认 `INFO`）。  
- `TIMEOUT_S`/`API_TIMEOUT_S`：HTTP 请求超时秒数。

## 提示词与多步骤说明
- 在 `prompt/` 中编写 Markdown，使用 `## STEP 1｜标题` 形式定义步骤；可选描述段落会被解析为选择项。  
- `/api/steps` 会读取并缓存当前提示词，`/api/run_step` 按步骤依次产出，支持“追加思考”模式与历史记录回填。  
- 需要切换提示词时，可在左侧提示词列表选择；运行中也可通过 `prompt_path` 字段覆盖。

## 日志与安全
- 日志输出到 `logs/app.log`，单文件 5MB 自动滚动。  
- 默认不打印完整 LLM 输入输出，生产环境建议保持关闭；如需排查问题可临时开启 `LOG_LLM=true`。  
- 不要在代码库提交真实密钥或敏感数据，确保外部接口使用 HTTPS 并配置合理的超时与重试（已内置）。***
