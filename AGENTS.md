# Repo Agent Rules (Codex)

## Goal
- 默认目标：最小改动解决问题，保证可复现与可验证。

## Workflow (Mandatory)
1) 先给计划（Plan），列出要跑的命令和要改的文件。
2) 再执行（Execute）。每次只做一个小步骤。
3) 每次改动后必须验证（Verify）。

## Allowed Commands (Allowlist)
- Build/Test:
  - mvn -q -DskipTests test
  - mvn -q test
  - ./gradlew test
- Git:
  - git status
  - git diff
  - git log -n 20
- Search:
  - rg "<pattern>"
  - find .

## Verification
- Java 项目：必须 `mvn -q test` 通过或明确解释为何跳过。
- 输出必须包含：命令 + exit code + 关键日志摘要。

## Safety
- 禁止删除性操作（rm -rf 等）
- 禁止访问工作区外路径
- 未经允许禁止联网
