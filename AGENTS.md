# AGENTS.md

This repository uses Codex as its primary AI agent and runs mainly on **Windows 10/11 environments**.
This document defines the core rules governing how agents interact with the project.

---

## 1. Project Context

This is a multi-language, production-grade engineering platform with the following primary stacks:

- **Java** — Spring Boot microservices, Maven multi-module build (JDK 17+)
- **Python** — Model inference, data pipelines, tooling (Python 3.10+)
- **PostgreSQL** — Analytics and event storage
- **Kafka** — Streaming and data pipelines
- **AI & Video** — ONNX Runtime, YOLO, PaddleOCR, MediaMTX, RTSP/WebRTC

Primary objectives:

- Real-time video and data analytics
- High‑stability inference services
- Secure operations and automated deployments

System priorities:

1. Security
2. Correctness
3. Stability
4. Performance
5. Code elegance

---

## 2. Windows Environment Baseline

All agent commands MUST target Windows-native environments.

Use:

- PowerShell (`powershell.exe` or `pwsh`)
- Windows filesystem paths (e.g. `D:\projects\vision-mind\`)

Avoid assumptions:

- No Bash or Linux shell by default
- No `/opt` or `/usr` style Unix paths
- No direct calls to Unix-only tools (`sed`, `awk`, `cut`, etc)

Acceptable tooling:

- Search: `findstr`, PowerShell `Select-String`
- File scan: `Get-ChildItem`
- Archives: `tar` (Win10+), `7z`

WSL2 may be used only for direct research commands (e.g. reading docs) — never for builds or package installs.

---

## 3. Build & Execution

### Java

Build:
```powershell
mvn clean package -DskipTests
```

Run:
```powershell
java -jar target\*.jar
```

---

### Python

Virtual environment:
```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

Run:
```powershell
python main.py
```

---

### AI / ONNX

Inference testing:
```powershell
python test_infer.py
```

CUDA/GPU assumed available when configured explicitly on host systems.

---

## 4. Database Standards

- PostgreSQL is the authoritative database.
- SQL MUST be ANSI‑compliant.
- Table existence must never be assumed.
- Performance analysis should use:

```sql
EXPLAIN ANALYZE
```

Connection sample:
```powershell
psql -h localhost -p 5432 -U postgres -d app_db
```

---

## 5. Coding Standards

Languages:

- Java ≥ 17
- Python ≥ 3.10

Agents MUST:

- Respect existing formatting/lint policies.
- Avoid manual reformatting unless explicitly requested.

Large refactors are prohibited without prior human authorization.

---

## 6. Git Protocol

- Default branch: **main**
- Generate **minimal, focused diffs**
- Do not rewrite commit history
- Do not perform mass file renames
- Do not touch unrelated files

---

## 7. Security & Compliance (Highest Priority)

Agents are bound by the following:

- Never hardcode credentials
- Never log secrets or personal data
- Strict validation on all user input
- Enforce file upload containment (no traversal or overwrite)
- All network calls MUST define timeouts and retries
- Explicit TLS enforcement for any remote connections

Security risk detection must be reported with remediation notes.

---

## 8. Agent Behavior Contract

Agents MUST:

- Ask for clarification when instructions are ambiguous.
- Explain reasoning ONLY for debugging or architectural analysis.
- Propose minimal impact solutions first.
- Honor all Windows environment constraints.

Agents MUST NOT:

- Assume Linux or container-only environments
- Add dependencies without explicit approval
- Perform uncontrolled refactors
- Run destructive commands without user confirmation

---

## 9. Workflow Integration

### Optional Governance Flow

Advanced work may follow the structured lifecycle:

```
/spec → /plan → /do
```

Rules:

- **/spec** → Create or update documentation only.
- **/plan** → Produce an implementation plan without code changes.
- **/do** → Execute approved implementation tasks.

Workflow is **opt‑in only** and only activates when explicitly requested.

---

## 10. Documentation Strategy

This document contains only invariant environment rules.

Domain or task-specific documentation MUST live under:

- `/docs/agent-tasks`
- `/docs/ops`
- `/docs/security`
- `/docs/workflows`

Agents load documents strictly on-demand.

---

## END OF AGENTS.md
