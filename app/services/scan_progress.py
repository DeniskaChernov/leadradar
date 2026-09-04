"""Live-прогресс Instagram-scan: фазы, счётчики, процент."""

from __future__ import annotations

from dataclasses import asdict, dataclass

PHASE_LABELS: dict[str, str] = {
    "idle": "Ожидание",
    "prepare": "Подготовка",
    "discover": "Поиск Reels у конкурентов",
    "comments": "Сбор комментариев",
    "finalize": "Завершение",
    "done": "Готово",
}

# Веса: комментарии обычно дольше discovery.
_PREPARE_END = 8
_DISCOVER_END = 45
_COMMENTS_END = 92
_FINALIZE_END = 99


@dataclass(slots=True)
class ScanProgress:
    phase: str = "idle"
    phase_label: str = PHASE_LABELS["idle"]
    current_handle: str | None = None
    detail: str = ""
    done: int = 0
    total: int = 0
    percent: int = 0
    competitors_checked: int = 0
    reels_found: int = 0
    comments_created: int = 0
    leads_created: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class ScanProgressTracker:
    """Mutable tracker; snapshot() отдаёт immutable копию для API."""

    def __init__(self) -> None:
        self._progress = ScanProgress()

    def reset(self) -> None:
        self._progress = ScanProgress(
            phase="prepare",
            phase_label=PHASE_LABELS["prepare"],
            detail="Запуск проверки…",
            percent=1,
        )

    def clear(self) -> None:
        self._progress = ScanProgress()

    def snapshot(self) -> ScanProgress:
        p = self._progress
        return ScanProgress(
            phase=p.phase,
            phase_label=p.phase_label,
            current_handle=p.current_handle,
            detail=p.detail,
            done=p.done,
            total=p.total,
            percent=p.percent,
            competitors_checked=p.competitors_checked,
            reels_found=p.reels_found,
            comments_created=p.comments_created,
            leads_created=p.leads_created,
        )

    def set_prepare(self, detail: str = "Подготовка очереди…") -> None:
        self._update(phase="prepare", detail=detail, done=0, total=0, percent=3)

    def set_discover(self, *, completed: int, total: int, handle: str) -> None:
        """completed = сколько конкурентов уже обработано (0…total)."""
        safe_total = max(0, total)
        safe_done = max(0, min(completed, safe_total)) if safe_total else 0
        ratio = safe_done / safe_total if safe_total else 1.0
        span = _DISCOVER_END - _PREPARE_END
        percent = _PREPARE_END + int(ratio * span)
        self._update(
            phase="discover",
            detail=f"Reels · {safe_done} из {safe_total}" if safe_total else "Reels · нет источников",
            current_handle=handle,
            done=safe_done,
            total=safe_total,
            percent=percent,
        )

    def set_comments(self, *, completed: int, total: int, handle: str) -> None:
        """completed = сколько Reel уже обработано (0…total)."""
        safe_total = max(0, total)
        safe_done = max(0, min(completed, safe_total)) if safe_total else 0
        ratio = safe_done / safe_total if safe_total else 1.0
        span = _COMMENTS_END - _DISCOVER_END
        percent = _DISCOVER_END + int(ratio * span)
        self._update(
            phase="comments",
            detail=f"Комментарии · {safe_done} из {safe_total}" if safe_total else "Комментарии · нечего загружать",
            current_handle=handle,
            done=safe_done,
            total=safe_total,
            percent=percent,
        )

    def set_finalize(self, detail: str = "Сохранение и очередь оценки…") -> None:
        self._update(
            phase="finalize",
            detail=detail,
            current_handle=None,
            done=0,
            total=0,
            percent=_FINALIZE_END,
        )

    def set_done(self) -> None:
        self._update(
            phase="done",
            detail="Проверка завершена",
            current_handle=None,
            percent=100,
        )

    def update_stats(
        self,
        *,
        competitors_checked: int | None = None,
        reels_found: int | None = None,
        comments_created: int | None = None,
        leads_created: int | None = None,
    ) -> None:
        p = self._progress
        if competitors_checked is not None:
            p.competitors_checked = competitors_checked
        if reels_found is not None:
            p.reels_found = reels_found
        if comments_created is not None:
            p.comments_created = comments_created
        if leads_created is not None:
            p.leads_created = leads_created

    def _update(
        self,
        *,
        phase: str,
        detail: str,
        percent: int,
        current_handle: str | None = None,
        done: int = 0,
        total: int = 0,
    ) -> None:
        p = self._progress
        p.phase = phase
        p.phase_label = PHASE_LABELS.get(phase, phase)
        p.detail = detail
        # Процент только растёт внутри одного цикла — без откатов назад.
        p.percent = max(p.percent, max(0, min(100, percent)))
        p.current_handle = current_handle
        p.done = done
        p.total = total
