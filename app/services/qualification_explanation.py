"""Explain a stored qualification without invoking analysis or changing its state."""

from app.db.models import LeadStatus


def qualification_explanation(status: LeadStatus, details: dict) -> dict[str, str]:
    assortment = details.get("assortment")
    assortment = assortment if isinstance(assortment, dict) else {}
    if status in {LeadStatus.AI_PENDING, LeadStatus.ANALYZING}:
        state, title, action = ("PENDING", "Оценка не завершена",
                                "Проверить сохранённые сигналы без GPT или запустить умную оценку вручную.")
    elif assortment.get("status") == "EXCLUDED":
        state, title, action = ("EXCLUDED", "Товар вне нашего ассортимента",
                                "Не предлагать этот товар. Если запрос включает другие позиции, уточнить их отдельно.")
    elif status == LeadStatus.NOT_LEAD:
        state, title, action = ("REJECTED", "Покупательский запрос не подтверждён",
                                "Сохранить комментарий как контекст; готового заказа он не подтверждает.")
    elif assortment.get("status") == "REVIEW":
        state, title, action = ("REVIEW", "Нужно уточнить товар",
                                "Подтвердить модель и соответствие нашему ассортименту перед предложением.")
    else:
        state, title, action = ("ASSESSED", "Оценка сохранена",
                                str(details.get("next_best_action") or details.get("recommended_action") or "Открыть карточку и проверить запрос клиента."))
    product = details.get("product_context")
    product = product if isinstance(product, dict) else {}
    source = {"COMMENT": "Товар определён из комментария клиента.",
              "PARENT_COMMENT": "Товар определён из родительского комментария.",
              "POST_CAPTION": "Товар определён из описания публикации."}.get(product.get("source"), "Товарный контекст не сохранён.")
    return {"state": state, "title": title, "action": action, "product_source": source,
            "assortment_reason": str(assortment.get("reason") or "")}
