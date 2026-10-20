# 待处理事项

## README 后端启动命令

- 发现于：2026-10-20，PR #1 文档审核；代码基线 `be88904`。
- 证据：`README.md` 快速开始使用 `uv run python -m src.web`，但 `src/web/` 没有 `__main__.py`。实际 ASGI 入口为 `src.web.app:app`，`Dockerfile` 和 `scripts/start_services.sh` 使用该入口。
- 影响：按 README 启动可能因模块入口缺失失败。
- 建议：单独修正文档并验证开发启动流程；本次仅在 `AGENTS.md` 给出与实现一致的命令。
