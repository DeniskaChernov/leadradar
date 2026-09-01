"""Allowlist запись файлов проекта (approval-gated через MCP)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Явный allowlist — без произвольного доступа к ФС
ALLOWED_FILE_PREFIXES = (
    "State.md",
    "PROJECT_STATUS.md",
    "exports/",
    "docs/drafts/",
)


@dataclass(frozen=True, slots=True)
class ProjectFileWriteResult:
    relative_path: str
    bytes_written: int
    mode: str


class ProjectFileService:
    def resolve_allowed_path(self, relative_path: str) -> Path:
        cleaned = relative_path.strip().replace("\\", "/").lstrip("/")
        if not cleaned or ".." in cleaned.split("/"):
            raise ValueError("Недопустимый путь к файлу")
        if not any(
            cleaned == prefix.rstrip("/") or cleaned.startswith(prefix)
            for prefix in ALLOWED_FILE_PREFIXES
        ):
            raise ValueError(
                "Путь вне allowlist. Разрешены: State.md, PROJECT_STATUS.md, exports/, docs/drafts/"
            )
        target = (PROJECT_ROOT / cleaned).resolve()
        if PROJECT_ROOT not in target.parents and target != PROJECT_ROOT:
            raise ValueError("Путь выходит за корень проекта")
        return target

    def write_file(
        self,
        relative_path: str,
        content: str,
        *,
        mode: str = "overwrite",
    ) -> ProjectFileWriteResult:
        if mode not in {"overwrite", "append"}:
            raise ValueError("mode must be overwrite or append")
        target = self.resolve_allowed_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = content if content.endswith("\n") or not content else content + "\n"
        if mode == "append" and target.exists():
            existing = target.read_text(encoding="utf-8")
            payload = existing + payload
        target.write_text(payload, encoding="utf-8")
        return ProjectFileWriteResult(
            relative_path=str(target.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            bytes_written=len(payload.encode("utf-8")),
            mode=mode,
        )

    def read_file(self, relative_path: str) -> str:
        target = self.resolve_allowed_path(relative_path)
        if not target.is_file():
            raise ValueError("Файл не найден")
        return target.read_text(encoding="utf-8")
