(() => {
  if (window.lucide) {
    try {
      window.lucide.createIcons({ attrs: { 'aria-hidden': 'true', 'stroke-width': 1.9 } });
      document.documentElement.classList.add('icons-ready');
    } catch (_) {}
  }

  const tg = window.Telegram?.WebApp;
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      document.documentElement.classList.add('inside-telegram');
      if (tg.colorScheme) document.documentElement.dataset.telegramTheme = tg.colorScheme;
      if (typeof tg.disableVerticalSwipes === 'function') tg.disableVerticalSwipes();
      if (typeof tg.setHeaderColor === 'function') tg.setHeaderColor('#f4f7ff');
      if (typeof tg.setBackgroundColor === 'function') tg.setBackgroundColor('#f4f7ff');
      const activePage = document.body.dataset.page || '/';
      if (tg.BackButton && activePage !== '/') {
        tg.BackButton.show();
        tg.BackButton.onClick(() => {
          if (window.history.length > 1) window.history.back();
          else tg.close();
        });
      }
    } catch (_) {}
  }

  const formatExportPreview = (data) => [
    `Recipe: ${data.recipe_slug || '—'}`,
    `Matched: ${data.total_matched ?? '—'} · eligible: ${data.eligible_count ?? '—'}`,
    `Dry-run: ${data.dry_run ? 'yes' : 'no'}`,
    `Privacy hashes: ${(data.sample_privacy_hashes || []).join(', ') || '—'}`,
  ].join('\n');

  const formatAgentAnswer = (data) => [
    `grounded: ${data.grounded}`,
    `mode: ${data.synthesis_mode}`,
    `evidence_ids: ${(data.evidence_ids || []).join(', ') || '—'}`,
    `tools: ${(data.tool_calls || []).map((item) => `${item.tool_name}:${item.success ? 'ok' : 'fail'}`).join(' · ') || '—'}`,
    '',
    data.answer || '—',
  ].join('\n');

  const escapeHtml = (value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');

  const renderAgentAnswer = (container, data) => {
    if (!container) return;
    container.hidden = false;
    container.innerHTML = '';
    const grounded = Boolean(data.grounded);
    const head = document.createElement('div');
    head.className = `agent-result-head ${grounded ? 'ok' : 'warn'}`;
    head.innerHTML = `<span class="tag ${grounded ? 'success' : 'neutral'}">${grounded ? 'Grounded' : 'Не grounded'}</span><small>${data.synthesis_mode || 'offline'}</small>`;
    container.appendChild(head);
    const body = document.createElement('div');
    body.className = 'agent-result-body';
    body.textContent = data.answer || '—';
    container.appendChild(body);
    const meta = document.createElement('div');
    meta.className = 'agent-result-meta';
    const tools = (data.tool_calls || [])
      .map((item) => `${item.tool_name}:${item.success ? 'ok' : 'fail'}`)
      .join(' · ') || '—';
    meta.innerHTML = `<span><b>Tools</b> ${tools}</span><span><b>Evidence</b> ${(data.evidence_ids || []).join(', ') || '—'}</span>`;
    container.appendChild(meta);
    if (getAgentContactId() && data.answer && String(data.answer).trim()) {
      const actions = document.createElement('div');
      actions.className = 'agent-result-actions';
      actions.innerHTML = '<button type="button" class="btn ghost tiny" data-agent-save-note>В заметку</button>';
      container.appendChild(actions);
    }
  };

  const readAgentContext = (extra = {}) => {
    const ctx = { ...extra };
    const node = document.querySelector('[data-agent-context]')
      || document.querySelector('[data-agent-chat-root]');
    if (node?.dataset.leadId) ctx.lead_id = Number(node.dataset.leadId);
    if (node?.dataset.contactId) ctx.contact_id = Number(node.dataset.contactId);
    const params = new URLSearchParams(window.location.search);
    if (params.get('lead_id')) ctx.lead_id = Number(params.get('lead_id'));
    if (params.get('contact_id')) ctx.contact_id = Number(params.get('contact_id'));
    if (ctx.lead_id != null && !Number.isFinite(ctx.lead_id)) delete ctx.lead_id;
    if (ctx.contact_id != null && !Number.isFinite(ctx.contact_id)) delete ctx.contact_id;
    return ctx;
  };

  const getAgentContactId = () => readAgentContext().contact_id;

  const saveAgentAnswerToNote = async (text, button) => {
    const contactId = getAgentContactId();
    if (!contactId) {
      toast('Нужен контекст клиента (lead или contact)', true);
      return;
    }
    const trimmed = String(text || '').trim();
    if (!trimmed) {
      toast('Нечего сохранять', true);
      return;
    }
    setLoading(button, true);
    try {
      await api(`/api/contacts/${contactId}/notes`, {
        method: 'POST',
        body: JSON.stringify({ text: `AI: ${trimmed}` }),
      });
      toast('Сохранено в заметку');
    } catch (error) {
      toast(error.message, true);
    } finally {
      setLoading(button, false);
    }
  };

  const runAgentQuery = async (form, submitButton) => {
    const targetSelector = form.dataset.agentTarget || '#agent-query-result';
    const output = document.querySelector(targetSelector);
    const plainOutput = output?.matches('pre.agent-result') ? output : null;
    setLoading(submitButton, true);
    try {
      const payload = {
        ...readAgentContext(),
        ...formPayload(form, submitButton),
      };
      const data = await api('/api/agent/query', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (output?.classList.contains('agent-result-rich')) {
        renderAgentAnswer(output, data);
      } else if (plainOutput) {
        plainOutput.hidden = false;
        plainOutput.textContent = formatAgentAnswer(data);
      }
      const useful = Boolean(data.answer && data.answer.trim());
      toast(
        data.grounded ? 'Ответ grounded' : (useful ? 'Ответ получен' : 'Tool вернул ошибку'),
        !data.grounded && !useful,
      );
      return data;
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Ошибка запроса';
      if (output?.classList.contains('agent-result-rich')) {
        output.hidden = false;
        output.innerHTML = `<div class="agent-result-head warn"><span class="tag neutral">Ошибка</span></div><div class="agent-result-body">${escapeHtml(message)}</div>`;
      } else if (plainOutput) {
        plainOutput.hidden = false;
        plainOutput.textContent = message;
      }
      toast(message, true);
      throw error;
    } finally {
      setLoading(submitButton, false);
    }
  };

  const openAgentQuickModal = () => {
    const root = document.getElementById('agent-quick');
    if (!root) return;
    const cancel = root.querySelector('[data-agent-quick-cancel]');
    const previouslyFocused = document.activeElement;
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('is-open'));
    const close = () => {
      root.classList.remove('is-open');
      document.removeEventListener('keydown', onKeydown);
      root.removeEventListener('click', onBackdrop);
      cancel.onclick = null;
      setTimeout(() => {
        root.hidden = true;
        if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
      }, 180);
    };
    const onKeydown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
      }
    };
    const onBackdrop = (event) => {
      if (event.target === root) close();
    };
    cancel.onclick = close;
    root.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKeydown);
    const input = root.querySelector('input[name="query"]');
    if (input instanceof HTMLInputElement) input.focus();
  };

  const toast = (message, bad = false, options = {}) => {
    const el = document.getElementById('toast');
    if (!el) return;
    const text = el.querySelector('[data-toast-message]');
    if (text) text.textContent = message;
    else el.textContent = message;
    el.className = `toast show ${bad ? 'bad' : ''}`;
    el.querySelector('i')?.getAnimations().forEach((animation) => animation.cancel());
    const undoBtn = el.querySelector('[data-toast-undo]');
    if (undoBtn instanceof HTMLButtonElement) {
      const undoAction = options.undo;
      undoBtn.hidden = !undoAction;
      undoBtn.onclick = undoAction
        ? (event) => {
          event.preventDefault();
          event.stopPropagation();
          undoAction();
        }
        : null;
    }
    clearTimeout(window.__lrToastTimer);
    const duration = options.duration || (options.undo ? 8000 : 3200);
    window.__lrToastTimer = setTimeout(() => {
      el.className = 'toast';
      if (undoBtn instanceof HTMLButtonElement) {
        undoBtn.hidden = true;
        undoBtn.onclick = null;
      }
    }, duration);
    return duration;
  };

  const readResponse = async (response) => {
    const type = response.headers.get('content-type') || '';
    if (type.includes('application/json')) return response.json();
    return { ok: response.ok, detail: await response.text() };
  };

  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || '';

  const api = async (url, options = {}) => {
    const method = (options.method || 'GET').toUpperCase();
    const headers = { ...(options.headers || {}) };
    const fetchOptions = {
      credentials: 'same-origin',
      method,
      ...options,
    };
    if (method === 'GET' || method === 'HEAD') {
      delete fetchOptions.body;
    } else if (!(options.body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
    }
    if (csrfToken && !headers['X-CSRF-Token']) headers['X-CSRF-Token'] = csrfToken;
    fetchOptions.headers = headers;
    const response = await fetch(url, fetchOptions);
    const data = await readResponse(response);
    if (!response.ok) {
      if (response.status === 429) {
        const retryAfter = Number(response.headers.get('Retry-After') || data.retry_after || 30);
        throw new Error(`Слишком много запросов к AI. Подождите ${retryAfter} сек.`);
      }
      throw new Error(data.detail || data.message || 'Не удалось выполнить действие');
    }
    return data;
  };

  const confirmAction = (title, text, options = {}) => new Promise((resolve) => {
    const root = document.getElementById('confirm');
    if (!root) return resolve(window.confirm(text));
    const previouslyFocused = document.activeElement;
    const danger = Boolean(options.danger);
    root.hidden = false;
    root.classList.toggle('is-danger', danger);
    requestAnimationFrame(() => root.classList.add('is-open'));
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-text').textContent = text;
    const ok = root.querySelector('[data-confirm-ok]');
    const cancel = root.querySelector('[data-confirm-cancel]');
    const okDefault = ok.dataset.defaultLabel || ok.textContent || 'Продолжить';
    ok.dataset.defaultLabel = okDefault;
    ok.textContent = danger ? (options.okLabel || 'Да, подтверждаю') : (options.okLabel || okDefault);
    ok.classList.toggle('danger', danger);
    ok.classList.toggle('primary', !danger);
    const onKeydown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        done(false);
      }
      if (event.key === 'Tab') {
        const focusable = [...root.querySelectorAll('button:not(:disabled),a[href]')];
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    const done = (value) => {
      root.classList.remove('is-open');
      root.classList.remove('is-danger');
      ok.onclick = null;
      cancel.onclick = null;
      document.removeEventListener('keydown', onKeydown);
      setTimeout(() => {
        root.hidden = true;
        ok.textContent = ok.dataset.defaultLabel || 'Продолжить';
        ok.classList.remove('danger');
        ok.classList.add('primary');
        if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
        resolve(value);
      }, 180);
    };
    ok.onclick = () => done(true);
    cancel.onclick = () => done(false);
    document.addEventListener('keydown', onKeydown);
    cancel.focus();
  });

  const enhanceNavigation = () => {
    const toggle = document.querySelector('[data-more-toggle]');
    const menu = document.getElementById('more-navigation');
    const close = () => {
      menu?.classList.remove('is-open');
      toggle?.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('more-navigation-open');
    };
    // На десктопе раскрыть «Ещё», если активен пункт системы
    if (menu?.querySelector('.nav.active') && window.matchMedia('(min-width: 721px)').matches) {
      menu.classList.add('is-open');
      toggle?.setAttribute('aria-expanded', 'true');
    }
    toggle?.addEventListener('click', () => {
      const opening = toggle.getAttribute('aria-expanded') !== 'true';
      menu?.classList.toggle('is-open', opening);
      toggle.setAttribute('aria-expanded', String(opening));
      document.body.classList.toggle('more-navigation-open', opening);
      if (opening) requestAnimationFrame(() => menu?.querySelector('a')?.focus());
    });
    document.querySelector('[data-more-close]')?.addEventListener('click', close);
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && document.body.classList.contains('more-navigation-open')) {
        close();
        toggle?.focus();
      }
    });
  };

  const enhanceMotion = () => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    // Канбан не участвует: translateY/scale ломает выравнивание колонок и даёт наложение.
    const elements = document.querySelectorAll(
      '[data-motion-root]:not([data-kanban-board]) > *, .cards > *, .task-list-page > *, .catalog-grid > *, .lead-layout > .panel, .stage-actions > .stage-btn, .funnel-track-step, .quick-actions > *, .metrics > *, .deal-grid > *'
    );
    if (!elements.length) return;
    document.documentElement.classList.add('motion-ready');
    elements.forEach((element, index) => {
      element.dataset.reveal = '';
      element.style.setProperty('--reveal-delay', `${Math.min(index % 8, 7) * 45}ms`);
    });
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.01, rootMargin: '0px 0px -8px' });
    elements.forEach((element) => observer.observe(element));
    // Сразу показать уже видимые блоки — иначе opacity:0 до первого callback IO.
    requestAnimationFrame(() => {
      const vh = window.innerHeight || document.documentElement.clientHeight;
      elements.forEach((element) => {
        if (element.classList.contains('is-visible')) return;
        const rect = element.getBoundingClientRect();
        if (rect.bottom > 0 && rect.top < vh) {
          element.classList.add('is-visible');
          observer.unobserve(element);
        }
      });
    });
  };

  const restoreViewState = () => {
    const key = sessionStorage.getItem('lr:focus');
    const y = Number(sessionStorage.getItem('lr:scroll-y') || 0);
    const kanbanX = Number(sessionStorage.getItem('lr:kanban-x') || 0);
    sessionStorage.removeItem('lr:focus');
    sessionStorage.removeItem('lr:scroll-y');
    sessionStorage.removeItem('lr:kanban-x');
    const apply = () => {
      if (y) window.scrollTo({ top: y, behavior: 'instant' });
      const kanban = document.querySelector('[data-kanban-board]');
      if (kanban && kanbanX) kanban.scrollLeft = kanbanX;
      if (!key) return;
      const el = document.querySelector(key);
      if (!el) return;
      el.scrollIntoView({ block: 'nearest', behavior: 'instant' });
      if (typeof el.focus === 'function') {
        try {
          el.focus({ preventScroll: true });
        } catch {
          el.focus();
        }
      }
    };
    requestAnimationFrame(apply);
  };

  const enhanceKanbanEventTips = () => {
    document.querySelectorAll('[data-kanban-event-tip]').forEach((trigger) => {
      const card = trigger.closest('.kanban-card');
      const panel = card?.querySelector('.kanban-event-tip-panel');
      if (!(panel instanceof HTMLElement)) return;
      const close = () => {
        panel.hidden = true;
        trigger.setAttribute('aria-expanded', 'false');
        card?.classList.remove('is-tip-open');
      };
      const open = () => {
        document.querySelectorAll('.kanban-card.is-tip-open').forEach((other) => {
          if (other === card) return;
          other.classList.remove('is-tip-open');
          other.querySelector('.kanban-event-tip-panel')?.setAttribute('hidden', '');
          other.querySelector('[data-kanban-event-tip]')?.setAttribute('aria-expanded', 'false');
        });
        panel.hidden = false;
        trigger.setAttribute('aria-expanded', 'true');
        card?.classList.add('is-tip-open');
      };
      trigger.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (panel.hidden) open();
        else close();
      });
      card?.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') close();
      });
    });
    document.addEventListener('click', (event) => {
      if (event.target.closest('[data-kanban-event-tip], .kanban-event-tip-panel')) return;
      document.querySelectorAll('.kanban-card.is-tip-open').forEach((card) => {
        card.classList.remove('is-tip-open');
        card.querySelector('.kanban-event-tip-panel')?.setAttribute('hidden', '');
        card.querySelector('[data-kanban-event-tip]')?.setAttribute('aria-expanded', 'false');
      });
    });
  };

  const enhanceKanbanMobile = () => {
    const board = document.querySelector('[data-kanban-board]');
    const nav = document.querySelector('[data-kanban-mobile-nav]');
    if (!(board instanceof HTMLElement) || !(nav instanceof HTMLElement)) return;
    const cols = [...board.querySelectorAll('.kanban-col')];
    const pills = [...nav.querySelectorAll('[data-kanban-col]')];
    if (!cols.length || !pills.length) return;
    const mobileQuery = window.matchMedia('(max-width: 720px)');
    const syncNav = () => {
      nav.hidden = !mobileQuery.matches;
      if (!mobileQuery.matches) return;
      const center = board.scrollLeft + board.clientWidth / 2;
      let active = 0;
      cols.forEach((col, index) => {
        const left = col.offsetLeft;
        const right = left + col.offsetWidth;
        if (center >= left && center < right) active = index;
      });
      pills.forEach((pill, index) => {
        pill.classList.toggle('is-active', index === active);
      });
    };
    pills.forEach((pill) => {
      pill.addEventListener('click', (event) => {
        event.preventDefault();
        const index = Number(pill.dataset.kanbanCol || 0);
        const col = cols[index];
        if (!col) return;
        col.scrollIntoView({ behavior: 'smooth', inline: 'start', block: 'nearest' });
        pills.forEach((item, pillIndex) => {
          item.classList.toggle('is-active', pillIndex === index);
        });
      });
    });
    board.addEventListener('scroll', syncNav, { passive: true });
    mobileQuery.addEventListener('change', syncNav);
    syncNav();
  };

  const enhanceKanbanDragDrop = () => {
    const board = document.querySelector('[data-kanban-board]');
    if (!(board instanceof HTMLElement)) return;
    const desktopQuery = window.matchMedia('(min-width: 721px)');
    if (!desktopQuery.matches) return;

    let draggedCard = null;
    let fromStage = '';
    let dropInFlight = false;

    const clearDropTargets = () => {
      board.querySelectorAll('.kanban-col.is-drop-target').forEach((col) => {
        col.classList.remove('is-drop-target');
      });
    };

    const CLOSED_STAGES = new Set(['WON', 'LOST']);
    const colStages = (col) =>
      String(col.dataset.kanbanStages || col.dataset.kanbanStage || '')
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
    const dropStatusOf = (col) =>
      String(col.dataset.kanbanDropStatus || '').trim().toUpperCase();

    board.querySelectorAll('[data-kanban-drag-handle]').forEach((handle) => {
      handle.addEventListener('dragstart', (event) => {
        const card = handle.closest('[data-lead-card]');
        if (!(card instanceof HTMLElement)) return;
        const stage = card.dataset.leadStage || '';
        if (CLOSED_STAGES.has(stage) || dropInFlight) {
          event.preventDefault();
          return;
        }
        draggedCard = card;
        fromStage = stage;
        card.classList.add('is-dragging');
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', card.dataset.leadCard || '');
      });
      handle.addEventListener('dragend', () => {
        draggedCard?.classList.remove('is-dragging');
        draggedCard = null;
        fromStage = '';
        clearDropTargets();
      });
    });

    board.querySelectorAll('[data-kanban-drop]').forEach((stack) => {
      const col = stack.closest('[data-kanban-stage]');
      if (!(col instanceof HTMLElement)) return;
      const targetStage = dropStatusOf(col);
      if (!targetStage || CLOSED_STAGES.has(targetStage)) return;

      stack.addEventListener('dragover', (event) => {
        if (!draggedCard || dropInFlight || !targetStage) return;
        if (colStages(col).includes(fromStage)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        col.classList.add('is-drop-target');
      });

      stack.addEventListener('dragleave', (event) => {
        if (stack.contains(event.relatedTarget)) return;
        col.classList.remove('is-drop-target');
      });

      stack.addEventListener('drop', async (event) => {
        event.preventDefault();
        col.classList.remove('is-drop-target');
        if (dropInFlight || !draggedCard || !targetStage) return;
        if (colStages(col).includes(fromStage)) return;
        const leadId = draggedCard.dataset.leadCard;
        if (!leadId) return;
        dropInFlight = true;
        board.classList.add('is-loading');
        try {
          const data = await api(`/api/leads/${leadId}/stage`, {
            method: 'POST',
            body: JSON.stringify({ status: targetStage }),
          });
          toast(data.message || 'Стадия обновлена');
          reloadSoon(450, `[data-lead-card="${leadId}"]`);
        } catch (error) {
          dropInFlight = false;
          toast(error.message, true);
          board.classList.remove('is-loading');
        }
      });
    });
  };

  const scanVertical = () => {
    const raw = (document.body.dataset.scanVertical || 'FURNITURE').trim().toUpperCase();
    return raw === 'ARTIFICIAL_RATTAN' ? 'ARTIFICIAL_RATTAN' : 'FURNITURE';
  };

  const withScanVertical = (url) => {
    if (/[?&]vertical=/.test(url)) return url;
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}vertical=${encodeURIComponent(scanVertical())}`;
  };


  const enhanceHotWorkspace = () => {
    const root = document.querySelector('[data-hot-workspace]');
    if (!(root instanceof HTMLElement)) return;
    const draftEl = root.querySelector('[data-hot-draft-text]');
    const badge = root.querySelector('[data-hot-draft-badge]');
    const prepareBtn = root.querySelector('[data-hot-prepare]');
    const copyBtn = root.querySelector('[data-hot-copy]');
    const sentBtn = root.querySelector('[data-hot-sent]');
    const syncActionButtons = () => {
      const text = draftEl instanceof HTMLTextAreaElement ? draftEl.value.trim() : '';
      const hasText = Boolean(text);
      if (copyBtn instanceof HTMLButtonElement) copyBtn.disabled = !hasText;
      if (sentBtn instanceof HTMLButtonElement) {
        const alreadySent = badge && badge.textContent === 'Отправлено';
        sentBtn.disabled = !hasText || Boolean(alreadySent);
      }
    };
    const setDraft = (detail) => {
      const draft = detail && detail.draft;
      if (draftEl instanceof HTMLTextAreaElement) {
        draftEl.value = draft && draft.message ? draft.message : '';
      }
      if (badge) {
        if (draft && draft.sent_at) badge.textContent = 'Отправлено';
        else if (draft && draft.message) badge.textContent = 'Готов';
        else badge.textContent = 'Нет текста';
        badge.className = `tag ${draft && draft.message ? 'success' : 'muted-tag'}`;
      }
      syncActionButtons();
    };
    if (draftEl instanceof HTMLTextAreaElement) {
      draftEl.addEventListener('input', syncActionButtons);
      syncActionButtons();
    }
    prepareBtn?.addEventListener('click', async () => {
      const leadId = prepareBtn.getAttribute('data-lead-id');
      if (!leadId) return;
      setLoading(prepareBtn, true);
      try {
        const data = await api(`/api/hot/${leadId}/prepare`, {
          method: 'POST',
          body: JSON.stringify({}),
        });
        setDraft(data.detail);
        toast(data.message || 'Текст готов');
      } catch (error) {
        toast(error.message, true);
      } finally {
        setLoading(prepareBtn, false);
      }
    });
    copyBtn?.addEventListener('click', async () => {
      const text = draftEl instanceof HTMLTextAreaElement ? draftEl.value.trim() : '';
      if (!text) return;
      try {
        await navigator.clipboard.writeText(text);
        toast('Текст скопирован');
      } catch (_error) {
        draftEl.focus();
        draftEl.select();
        toast('Выделите текст и скопируйте вручную (Ctrl+C)', true);
      }
    });
    sentBtn?.addEventListener('click', async () => {
      const leadId = sentBtn.getAttribute('data-lead-id');
      if (!leadId) return;
      const message = draftEl instanceof HTMLTextAreaElement ? draftEl.value.trim() : '';
      if (!message) {
        toast('Вставьте или подготовьте текст перед отметкой', true);
        return;
      }
      const ok = await confirmAction(
        'Отметить отправку?',
        'Лид перейдёт по воронке до «Предложение отправлено». Нажимайте только после реальной отправки в Instagram.'
      );
      if (!ok) return;
      setLoading(sentBtn, true);
      try {
        const data = await api(`/api/hot/${leadId}/sent`, {
          method: 'POST',
          body: JSON.stringify({ message }),
        });
        setDraft(data.detail);
        const nextUrl = data.next_url
          || (data.detail && data.detail.next_lead_id
            ? `/hot?vertical=${encodeURIComponent(root.getAttribute('data-hot-vertical') || 'FURNITURE')}&lead_id=${data.detail.next_lead_id}`
            : `/hot?vertical=${encodeURIComponent(root.getAttribute('data-hot-vertical') || 'FURNITURE')}`);
        toast(data.detail && data.detail.next_lead_id
          ? `${data.message || 'Отмечено'} · следующий HOT`
          : `${data.message || 'Отмечено'} · очередь пуста`);
        window.location.assign(nextUrl);
      } catch (error) {
        toast(error.message, true);
        setLoading(sentBtn, false);
      }
    });
  };

  const enhanceEconomicsBudgetSim = () => {
    const root = document.querySelector('[data-economics-budget-sim]');
    if (!(root instanceof HTMLElement)) return;
    const slider = root.querySelector('[data-budget-sim-slider]');
    if (!(slider instanceof HTMLInputElement)) return;
    let timer = 0;
    const refresh = async () => {
      const credits = slider.value;
      const valueEl = root.querySelector('[data-budget-sim-value]');
      if (valueEl) valueEl.textContent = credits;
      try {
        const preview = await api(
          withScanVertical(`/api/scan/preview?max_credits=${encodeURIComponent(credits)}`),
          { method: 'GET' },
        );
        const maxEl = root.querySelector('[data-budget-sim-max]');
        const monthlyEl = root.querySelector('[data-budget-sim-monthly]');
        const dailyEl = root.querySelector('[data-budget-sim-daily]');
        const planEl = root.querySelector('[data-budget-sim-plan]');
        const clampEl = root.querySelector('[data-budget-sim-clamp]');
        const clampValue = root.querySelector('[data-budget-sim-clamp-value]');
        if (maxEl) maxEl.textContent = `${preview.effective_max_credits} credits`;
        if (monthlyEl && preview.monthly_remaining != null) {
          monthlyEl.textContent = String(preview.monthly_remaining);
        }
        if (dailyEl && preview.daily_remaining != null) {
          dailyEl.textContent = String(preview.daily_remaining);
        }
        if (planEl) {
          planEl.textContent = `План: ~${preview.estimated_competitors_reachable || 0} конкурентов · `
            + `~${preview.estimated_comment_pages || 0} стр.`
            + (preview.expected_min_units != null ? ` · мин. ${preview.expected_min_units} credits` : '');
        }
        if (clampEl) {
          clampEl.hidden = !preview.clamped;
          if (clampValue) clampValue.textContent = String(preview.effective_max_credits);
        }
      } catch (_error) {
        /* offline preview недоступен */
      }
    };
    slider.addEventListener('input', () => {
      clearTimeout(timer);
      timer = window.setTimeout(refresh, 180);
    });
    refresh();
  };

  const initKanbanLoadingState = () => {
    const board = document.querySelector('[data-kanban-board]');
    if (!(board instanceof HTMLElement)) return;
    if (sessionStorage.getItem('lr:kanban-loading') === '1') {
      sessionStorage.removeItem('lr:kanban-loading');
      board.classList.add('is-loading');
      window.setTimeout(() => board.classList.remove('is-loading'), 420);
    }
  };

  const enhanceTables = () => {
    document.querySelectorAll('.table-wrap').forEach((wrapper, index) => {
      const table = wrapper.querySelector('table');
      if (!table || wrapper.dataset.tableEnhanced === '1') return;
      wrapper.dataset.tableEnhanced = '1';
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role', 'region');
      const title = wrapper.closest('.panel')?.querySelector('h2')?.textContent?.trim() || 'Данные';
      const hint = document.createElement('p');
      hint.className = 'table-scroll-hint';
      hint.id = `table-scroll-hint-${index}`;
      hint.textContent = 'Прокрутите таблицу по горизонтали, чтобы увидеть все столбцы';
      wrapper.setAttribute('aria-label', `Таблица «${title}»`);
      wrapper.setAttribute('aria-describedby', hint.id);
      wrapper.insertAdjacentElement('beforebegin', hint);
      const refresh = () => {
        const scrollable = wrapper.scrollWidth > wrapper.clientWidth + 1;
        wrapper.classList.toggle('is-scrollable', scrollable);
        hint.hidden = !scrollable;
      };
      refresh();
      if (window.ResizeObserver) new ResizeObserver(refresh).observe(wrapper);
    });
  };

  const enhanceClickableRows = () => {
    document.querySelectorAll('tr.clickable[data-href]').forEach((row) => {
      row.tabIndex = 0;
      row.setAttribute('role', 'link');
      if (!row.hasAttribute('aria-label')) {
        const label = row.querySelector('a')?.textContent?.trim() || row.textContent.trim();
        row.setAttribute('aria-label', `Открыть: ${label}`);
      }
    });
  };

  const enhanceCompetitorBulkSelection = () => {
    const picks = () => [...document.querySelectorAll('[data-competitor-pick]')];
    if (!picks().length) return;
    const sync = () => {
      const selected = picks().filter((input) => input.checked);
      const count = document.querySelector('[data-competitor-bulk-count]');
      if (count) count.textContent = `Выбрано: ${selected.length}`;
      document.querySelectorAll('[data-competitor-bulk]').forEach((button) => {
        button.disabled = selected.length === 0;
      });
      const master = document.querySelector('[data-competitor-select-all]');
      if (master) {
        const all = picks();
        master.checked = all.length > 0 && selected.length === all.length;
        master.indeterminate = selected.length > 0 && selected.length < all.length;
      }
    };
    document.addEventListener('change', (event) => {
      if (event.target.matches('[data-competitor-select-all]')) {
        picks().forEach((input) => {
          input.checked = event.target.checked;
        });
        sync();
        return;
      }
      if (event.target.matches('[data-competitor-pick]')) sync();
    });
    sync();
  };

  const enhanceGlobalSearchShortcut = () => {
    document.addEventListener('keydown', (event) => {
      if (event.key !== '/' || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target;
      if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target?.isContentEditable) return;
      const searchInput = document.querySelector(
        '.filters input[name="q"], .contacts-filters input[name="q"], .tasks-filters input[name="q"], .deals-filters input[name="q"], .radar-filters input[name="q"]',
      );
      if (!(searchInput instanceof HTMLInputElement)) return;
      event.preventDefault();
      searchInput.focus();
      searchInput.select();
    });
  };

  enhanceNavigation();
  enhanceTables();
  enhanceClickableRows();
  enhanceCompetitorBulkSelection();
  enhanceGlobalSearchShortcut();
  enhanceMotion();
  enhanceKanbanEventTips();
  enhanceKanbanMobile();
  enhanceKanbanDragDrop();
  enhanceEconomicsBudgetSim();
  enhanceHotWorkspace();
  initKanbanLoadingState();
  restoreViewState();

  const flashStageSuccess = (element) => {
    if (!element) return;
    element.classList.add('stage-success');
  };

  const focusKeyForElement = (el) => {
    if (!(el instanceof HTMLElement)) return '';
    if (el.id) return `#${CSS.escape(el.id)}`;
    if (el.dataset.leadAction && el.dataset.leadId) {
      return `[data-lead-action="${el.dataset.leadAction}"][data-lead-id="${el.dataset.leadId}"]`;
    }
    if (el.dataset.stage && el.dataset.leadId) {
      return `[data-stage="${el.dataset.stage}"][data-lead-id="${el.dataset.leadId}"]`;
    }
    if (el.dataset.apiAction) {
      return `[data-api-action="${CSS.escape(el.dataset.apiAction)}"]`;
    }
    if (el.dataset.taskComplete) {
      return `[data-task-complete="${CSS.escape(el.dataset.taskComplete)}"]`;
    }
    const form = el.closest('form[data-api-form]');
    if (form?.id) return `#${CSS.escape(form.id)}`;
    if (form) {
      const panel = form.closest('[id]');
      if (panel?.id) return `#${CSS.escape(panel.id)}`;
    }
    const funnel = document.getElementById('funnel');
    return funnel ? '#funnel' : '';
  };

  let lastActionEl = null;

  const reloadSoon = (delay = 450, focusSelector = '') => {
    sessionStorage.setItem('lr:scroll-y', String(window.scrollY));
    const kanban = document.querySelector('[data-kanban-board]');
    if (kanban instanceof HTMLElement) {
      sessionStorage.setItem('lr:kanban-x', String(kanban.scrollLeft));
      sessionStorage.setItem('lr:kanban-loading', '1');
    }
    let focus = focusSelector;
    if (!focus) {
      const active = document.activeElement;
      focus = focusKeyForElement(active instanceof HTMLElement ? active : null)
        || focusKeyForElement(lastActionEl);
    }
    if (focus) sessionStorage.setItem('lr:focus', focus);
    setTimeout(() => location.reload(), delay);
  };

  const setLoading = (element, loading) => {
    if (!element) return;
    element.disabled = loading;
    element.classList.toggle('is-loading', loading);
    element.setAttribute('aria-busy', String(loading));
  };

  const readScanBudgetSelection = (root = document) => {
    const selected = root.querySelector('input[name="scan_budget"]:checked')
      || root.querySelector('input[name="scan_budget_quick"]:checked');
    if (!selected) return null;
    if (selected.value === 'custom') {
      const custom = root.querySelector('[data-custom-scan-budget]')
        || root.querySelector('[data-custom-scan-budget-quick]');
      return custom?.value || null;
    }
    return selected.value;
  };

  const formatScanPreviewMeta = (preview) => {
    if (!preview.is_live) {
      return {
        meta: 'Offline-режим: credits не расходуются.',
        plan: '',
        block: '',
      };
    }
    const requested = preview.requested_credits;
    const effective = preview.effective_max_credits;
    let meta = `Макс. на scan: ${effective} credits · `
      + `месяц: ${preview.used_this_month}/${preview.monthly_hard_limit ?? '—'} · `
      + `сегодня: ${preview.daily_remaining}`;
    if (preview.clamped) {
      meta += ` · запрос ${requested} урезан до ${effective}`;
    }
    const plan = `План: ~${preview.estimated_competitors_reachable || 0} конкурентов · `
      + `~${preview.estimated_comment_pages || 0} стр. комментариев`
      + (preview.expected_min_units != null ? ` · минимум ${preview.expected_min_units} credits` : '');
    const block = Array.isArray(preview.blocking_reasons) && preview.blocking_reasons.length
      ? preview.blocking_reasons.join(' ')
      : '';
    return { meta, plan, block };
  };

  const syncScanButtonsFromPreview = (preview) => {
    if (!preview) return;
    const scanAllowed = Boolean(preview.search_enabled)
      && (!preview.is_live || (preview.live_enabled && preview.can_start));
    document.querySelectorAll('[data-scan], [data-scan-quick-go]').forEach((btn) => {
      if (!(btn instanceof HTMLButtonElement)) return;
      if (btn.dataset.scanBusy === '1') return;
      btn.disabled = !scanAllowed;
    });
  };

  const refreshScanBudgetPreview = async (root = document) => {
    const credits = readScanBudgetSelection(root);
    if (!credits) return null;
    try {
      const preview = await api(
        withScanVertical(`/api/scan/preview?max_credits=${encodeURIComponent(credits)}`),
        { method: 'GET' },
      );
      const maxEl = root.querySelector('[data-budget-max]');
      const monthlyEl = root.querySelector('[data-budget-monthly]');
      const dailyEl = root.querySelector('[data-budget-daily]');
      const planEl = root.querySelector('[data-budget-plan]');
      const clampEl = root.querySelector('[data-budget-clamp]');
      const clampValue = root.querySelector('[data-budget-clamp-value]');
      if (maxEl) maxEl.textContent = `${preview.effective_max_credits} credits`;
      if (monthlyEl && preview.monthly_remaining != null) {
        monthlyEl.textContent = String(preview.monthly_remaining);
      }
      if (dailyEl && preview.daily_remaining != null) {
        dailyEl.textContent = String(preview.daily_remaining);
      }
      if (planEl) {
        planEl.textContent = `План: ~${preview.estimated_competitors_reachable || 0} конкурентов · `
          + `~${preview.estimated_comment_pages || 0} стр. комментариев`
          + (preview.expected_min_units != null ? ` · минимум ${preview.expected_min_units} credits` : '');
      }
      if (clampEl) {
        clampEl.hidden = !preview.clamped;
        if (clampValue) clampValue.textContent = String(preview.effective_max_credits);
      }
      const meta = root.querySelector('[data-scan-quick-meta]');
      const planQuick = root.querySelector('[data-scan-quick-plan]');
      const blockQuick = root.querySelector('[data-scan-quick-block]');
      if (meta || planQuick || blockQuick) {
        const formatted = formatScanPreviewMeta(preview);
        if (meta) {
          meta.textContent = formatted.meta;
          meta.hidden = false;
        }
        if (planQuick) {
          planQuick.textContent = formatted.plan;
          planQuick.hidden = !formatted.plan;
        }
        if (blockQuick) {
          blockQuick.textContent = formatted.block;
          blockQuick.hidden = !formatted.block;
        }
      }
      syncScanButtonsFromPreview(preview);
      return preview;
    } catch (_error) {
      return null;
    }
  };

  const openScanQuickModal = () => new Promise((resolve) => {
    const root = document.getElementById('scan-quick');
    if (!root) return resolve(null);
    const cancel = root.querySelector('[data-scan-quick-cancel]');
    const go = root.querySelector('[data-scan-quick-go]');
    const previouslyFocused = document.activeElement;
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('is-open'));
    refreshScanBudgetPreview(root);
    const onChange = () => refreshScanBudgetPreview(root);
    root.addEventListener('change', onChange);
    root.addEventListener('input', onChange);
    const close = (value) => {
      root.classList.remove('is-open');
      root.removeEventListener('change', onChange);
      root.removeEventListener('input', onChange);
      cancel.onclick = null;
      go.onclick = null;
      document.removeEventListener('keydown', onKeydown);
      setTimeout(() => {
        root.hidden = true;
        if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
        resolve(value);
      }, 180);
    };
    const onKeydown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close(null);
      }
    };
    cancel.onclick = () => close(null);
    go.onclick = () => close(readScanBudgetSelection(root));
    document.addEventListener('keydown', onKeydown);
    requestAnimationFrame(() => cancel.focus());
  });

  const runScan = async (triggerButton, requestedCredits = null) => {
    const old = triggerButton?.textContent || 'Проверить сейчас';
    if (triggerButton) {
      triggerButton.disabled = true;
      triggerButton.textContent = 'Проверяю лимиты…';
    }
    try {
      let credits = requestedCredits;
      if (credits == null) credits = readScanBudgetSelection(document);
      const previewUrl = withScanVertical(
        credits
          ? `/api/scan/preview?max_credits=${encodeURIComponent(credits)}`
          : '/api/scan/preview'
      );
      const preview = await api(previewUrl, { method: 'GET' });
      if (!preview.search_enabled) {
        throw new Error('Поиск лидов временно приостановлен. Credits не расходуются.');
      }
      let confirmLive = false;
      if (preview.is_live) {
        if (!preview.live_enabled) {
          throw new Error('Live-запросы выключены. Credits не будут потрачены.');
        }
        if (!preview.can_start) {
          throw new Error((preview.blocking_reasons || []).join(' ') || 'Бюджет проверки недоступен.');
        }
        const hardCap = Number(preview.effective_max_credits || 0);
        const monthlyUsed = Number(preview.used_this_month || 0);
        const monthlyHard = Number(preview.monthly_hard_limit || 0);
        const balance = preview.credits_remaining == null
          ? 'не подтверждён'
          : `${Number(preview.credits_remaining).toLocaleString('ru-RU')} credits`;
        const months = preview.package_months_remaining_estimate == null
          ? 'неизвестен'
          : `~${preview.package_months_remaining_estimate} месяца`;
        const proceed = await confirmAction(
          'Найти лидов?',
          `Максимум на запуск: ${hardCap} credits. `
          + `Использовано за месяц: ${monthlyUsed}/${monthlyHard}. Остаток: ${balance}. Запас: ${months}.`
        );
        if (!proceed) return;
        confirmLive = true;
        credits = Number(preview.requested_credits);
      }
      if (triggerButton) triggerButton.textContent = 'Запускаю…';
      const data = await api('/api/scan', {
        method: 'POST',
        body: JSON.stringify({
          confirm_live: confirmLive,
          max_credits: credits ? Number(credits) : 0,
          vertical: scanVertical(),
        }),
      });
      toast(data.message || 'Поиск запущен');
      if (data.ok) {
        try {
          sessionStorage.setItem('lr:find-leads-pending-results', '1');
        } catch (_error) {
          /* ignore */
        }
        const onRadar = (document.body.dataset.page || '').startsWith('/radar');
        if (onRadar) {
          startRadarPolling();
        } else {
          setTimeout(() => { window.location.href = findLeadsResultsUrl(); }, 1200);
        }
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (triggerButton) {
        triggerButton.disabled = false;
        triggerButton.textContent = old;
      }
    }
  };

  const formPayload = (form, submitter) => {
    const result = {};
    for (const [key, value] of new FormData(form).entries()) result[key] = value;
    if (submitter?.name) result[submitter.name] = submitter.value;
    return result;
  };

  const authenticateTelegram = async () => {
    const status = document.getElementById('auth-status');
    if (!status) return;
    const initData = tg?.initData || '';
    if (!initData) {
      status.textContent = 'Откройте Lead Radar кнопкой внутри Telegram-бота. В обычном браузере Telegram не передаёт данные для входа.';
      status.classList.add('bad');
      return;
    }
    status.textContent = 'Проверяем доступ…';
    status.classList.remove('bad');
    try {
      await api('/api/auth/telegram', { method: 'POST', body: JSON.stringify({ initData }) });
      status.textContent = 'Готово. Открываем Lead Radar…';
      location.href = '/';
    } catch (error) {
      status.textContent = error.message;
      status.classList.add('bad');
    }
  };

  if (document.body.dataset.authPage === '1') authenticateTelegram();

  document.addEventListener('submit', async (event) => {
    const agentForm = event.target.closest('[data-agent-query]');
    if (agentForm) {
      event.preventDefault();
      const submit = agentForm.querySelector('[type="submit"]');
      try {
        await runAgentQuery(agentForm, submit);
      } catch (_) {
        /* toast уже показан в runAgentQuery */
      }
      return;
    }

    const form = event.target.closest('[data-api-form]');
    if (!form) return;
    event.preventDefault();
    if (event.submitter?.dataset.confirm) {
      const proceed = await confirmAction(
        event.submitter.dataset.confirmTitle || 'Подтвердите действие',
        event.submitter.dataset.confirm,
        { danger: event.submitter.dataset.confirmDanger === '1' }
      );
      if (!proceed) return;
    }
    const submit = event.submitter || form.querySelector('[type="submit"]');
    setLoading(submit, true);
    try {
      const multipart = form.enctype === 'multipart/form-data';
      const body = multipart ? new FormData(form) : formPayload(form, event.submitter);
      if (multipart && event.submitter?.name) {
        body.set(event.submitter.name, event.submitter.value);
      }
      const rawMethod = (form.getAttribute('method') || 'post').trim().toLowerCase();
      const method = rawMethod === 'get' ? 'POST' : rawMethod.toUpperCase();
      const data = await api(form.action, {
        method,
        body: multipart ? body : JSON.stringify(body),
      });
      toast(data.message || 'Сохранено');
      if (form.dataset.output) {
        const output = document.querySelector(form.dataset.output);
        if (output) {
          const rows = (data.changes || []).map((item) => {
            const protectedText = item.protected_fields?.length
              ? `; защищены: ${item.protected_fields.join(', ')}`
              : '';
            return `${item.status} ${item.canonical_key}: ${(item.fields || []).join(', ') || 'без изменений'}${protectedText}`;
          });
          output.textContent = [
            data.applied ? 'Изменения применены атомарно.' : 'Предпросмотр: база не изменена.',
            `Строк: ${data.rows}; новых: ${data.created}; обновлений: ${data.updated}; без изменений: ${data.unchanged}`,
            ...rows,
          ].join('\n');
          output.hidden = false;
        }
      }
      if (form.dataset.reset === '1') form.reset();
      if (form.dataset.reload === '1') {
        lastActionEl = event.submitter || form;
        reloadSoon(450, focusKeyForElement(lastActionEl));
      }
    } catch (error) {
      toast(error.message, true);
    } finally {
      setLoading(submit, false);
    }
  });

  document.addEventListener('click', async (event) => {
    const tracked = event.target.closest(
      '[data-lead-action],[data-stage],[data-api-action],[data-lead-bulk],[data-competitor-bulk],[data-task-complete],[data-lead-followup],[data-discovery-import],[data-competitor-import]'
    );
    if (tracked) lastActionEl = tracked;
    const button = event.target.closest('.btn');
    if (button && !button.disabled) {
      const bounds = button.getBoundingClientRect();
      button.style.setProperty('--ripple-x', `${event.clientX - bounds.left}px`);
      button.style.setProperty('--ripple-y', `${event.clientY - bounds.top}px`);
      button.classList.remove('is-rippling');
      requestAnimationFrame(() => button.classList.add('is-rippling'));
      setTimeout(() => button.classList.remove('is-rippling'), 550);
    }
    const logout = event.target.closest('[data-logout]');
    if (logout) {
      try {
        await api('/logout', { method: 'POST', body: '{}' });
      } finally {
        location.href = '/auth';
      }
      return;
    }

    const competitorImport = event.target.closest('[data-competitor-import]');
    if (competitorImport) {
      const input = document.getElementById('competitor-import-file');
      const file = input?.files?.[0];
      if (!file) {
        toast('Сначала выберите CSV или XLSX файл', true);
        return;
      }
      const old = competitorImport.textContent;
      competitorImport.disabled = true;
      competitorImport.textContent = 'Импортирую…';
      try {
        const response = await fetch(`/api/competitors/import?filename=${encodeURIComponent(file.name)}`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/octet-stream',
            ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
          },
          body: file,
        });
        const data = await readResponse(response);
        if (!response.ok) throw new Error(data.detail || 'Не удалось импортировать файл');
        toast(data.message || 'Импорт завершён');
        reloadSoon(900);
      } catch (error) {
        toast(error.message, true);
        competitorImport.disabled = false;
        competitorImport.textContent = old;
      }
      return;
    }

    const discoveryImport = event.target.closest('[data-discovery-import]');
    if (discoveryImport) {
      const input = document.getElementById('discovery-file');
      const file = input?.files?.[0];
      if (!file) {
        toast('Сначала выберите CSV или XLSX файл', true);
        return;
      }
      const old = discoveryImport.textContent;
      discoveryImport.disabled = true;
      discoveryImport.textContent = 'Импортирую…';
      try {
        const response = await fetch(`/api/discovery/import?filename=${encodeURIComponent(file.name)}`, {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'Content-Type': 'application/octet-stream',
            ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
          },
          body: file,
        });
        const data = await readResponse(response);
        if (!response.ok) throw new Error(data.detail || 'Не удалось импортировать файл');
        toast(data.message || 'Импорт завершён');
        reloadSoon(900);
      } catch (error) {
        toast(error.message, true);
        discoveryImport.disabled = false;
        discoveryImport.textContent = old;
      }
      return;
    }

    const retryAuth = event.target.closest('[data-auth-retry]');
    if (retryAuth) {
      authenticateTelegram();
      return;
    }

    const agentOpen = event.target.closest('[data-agent-open]');
    if (agentOpen) {
      event.preventDefault();
      openAgentQuickModal();
      return;
    }

    const agentSaveNote = event.target.closest('[data-agent-save-note]');
    if (agentSaveNote) {
      event.preventDefault();
      const bubble = agentSaveNote.closest('.agent-chat-msg, .agent-result-rich')?.querySelector('.agent-chat-bubble, .agent-result-body');
      await saveAgentAnswerToNote(bubble?.textContent || '', agentSaveNote);
      return;
    }

    const agentPreset = event.target.closest('[data-agent-preset]');
    if (agentPreset) {
      event.preventDefault();
      let payload = {};
      try {
        payload = JSON.parse(agentPreset.dataset.agentPreset || '{}');
      } catch (_) {
        return;
      }
      payload = { ...readAgentContext(), ...payload };
      if (agentPreset.dataset.agentNeedsLead === '1' && !payload.lead_id) {
        toast('Откройте /agent?lead_id=… или карточку лида', true);
        return;
      }
      const form = agentPreset.closest('[data-agent-query]')
        || document.querySelector('#agent-quick [data-agent-query]')
        || document.querySelector('[data-agent-chat-form]');
      if (!form) return;
      if (form.matches('[data-agent-chat-form]')) {
        const textarea = form.querySelector('textarea[name="query"]');
        if (textarea instanceof HTMLTextAreaElement) {
          textarea.value = String(payload.query || '');
          textarea.focus();
        }
        if (payload.lead_id) form.dataset.pendingLeadId = String(payload.lead_id);
        if (payload.contact_id) form.dataset.pendingContactId = String(payload.contact_id);
        form.requestSubmit();
        return;
      }
      Object.entries(payload).forEach(([key, value]) => {
        let field = form.querySelector(`[name="${key}"]`);
        if (!field && (key === 'lead_id' || key === 'contact_id')) {
          field = document.createElement('input');
          field.type = 'hidden';
          field.name = key;
          form.appendChild(field);
        }
        if (field instanceof HTMLInputElement) field.value = String(value);
      });
      const submit = form.querySelector('[type="submit"]');
      runAgentQuery(form, submit).catch(() => {});
      return;
    }

    const scan = event.target.closest('[data-scan]');
    if (scan) {
      event.preventDefault();
      const hasPicker = document.querySelector('input[name="scan_budget"]');
      if (!hasPicker) {
        openScanQuickModal().then((picked) => {
          if (picked == null) return;
          runScan(scan, picked);
        });
        return;
      }
      runScan(scan);
      return;
    }

    const action = event.target.closest('[data-api-action]');
    if (action) {
      if (action.dataset.confirm) {
        const proceed = await confirmAction(
          action.dataset.confirmTitle || 'Подтвердите действие',
          action.dataset.confirm,
          { danger: action.dataset.confirmDanger === '1' }
        );
        if (!proceed) return;
      }
      setLoading(action, true);
      try {
        const payload = action.dataset.payload ? JSON.parse(action.dataset.payload) : {};
        const data = await api(action.dataset.apiAction, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (action.dataset.resultTarget) {
          const target = document.querySelector(action.dataset.resultTarget);
          if (target) {
            target.hidden = false;
            target.textContent = formatExportPreview(data);
          }
          toast('Dry-run preview готов');
          setLoading(action, false);
          return;
        }
        toast(data.message || 'Готово');
        if (action.dataset.asyncRetry === '1') {
          if (typeof startRadarPolling === 'function') startRadarPolling();
          setLoading(action, false);
          return;
        }
        if (action.dataset.reload === '1') reloadSoon(450, focusKeyForElement(action));
        else setLoading(action, false);
      } catch (error) {
        toast(error.message, true);
        setLoading(action, false);
      }
      return;
    }

    const leadBulk = event.target.closest('[data-lead-bulk]');
    if (leadBulk) {
      event.preventDefault();
      event.stopPropagation();
      const action = leadBulk.dataset.leadBulk;
      let leadIds = [];
      try {
        leadIds = JSON.parse(leadBulk.dataset.leadIds || '[]');
      } catch {
        toast('Некорректный список лидов', true);
        return;
      }
      if (!leadIds.length) return;
      if (leadBulk.dataset.confirm) {
        const proceed = await confirmAction(
          leadBulk.dataset.confirmTitle || 'Массовое действие',
          leadBulk.dataset.confirm,
          { danger: leadBulk.dataset.confirmDanger === '1' }
        );
        if (!proceed) return;
      }
      setLoading(leadBulk, true);
      try {
        const data = await api('/api/leads/bulk-action', {
          method: 'POST',
          body: JSON.stringify({ action, lead_ids: leadIds }),
        });
        toast(data.message || 'Готово');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        setLoading(leadBulk, false);
      }
      return;
    }

    const competitorBulk = event.target.closest('[data-competitor-bulk]');
    if (competitorBulk) {
      event.preventDefault();
      event.stopPropagation();
      const ids = [...document.querySelectorAll('[data-competitor-pick]:checked')]
        .map((input) => Number(input.value))
        .filter((id) => Number.isFinite(id) && id > 0);
      if (!ids.length) {
        toast('Выберите хотя бы одну компанию', true);
        return;
      }
      const resume = competitorBulk.dataset.competitorBulk === 'resume';
      if (competitorBulk.dataset.confirm) {
        const proceed = await confirmAction(
          competitorBulk.dataset.confirmTitle || 'Массовое действие',
          competitorBulk.dataset.confirm,
          { danger: competitorBulk.dataset.confirmDanger === '1' }
        );
        if (!proceed) return;
      }
      setLoading(competitorBulk, true);
      try {
        const data = await api('/api/competitors/bulk-active', {
          method: 'POST',
          body: JSON.stringify({ competitor_ids: ids, active: resume }),
        });
        toast(data.message || 'Готово');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        setLoading(competitorBulk, false);
      }
      return;
    }

    const leadFollowup = event.target.closest('[data-lead-followup]');
    if (leadFollowup) {
      event.preventDefault();
      event.stopPropagation();
      const id = leadFollowup.dataset.leadFollowup;
      setLoading(leadFollowup, true);
      try {
        const data = await api(`/api/leads/${id}/follow-up`, {
          method: 'POST',
          body: JSON.stringify({ hours: 24 }),
        });
        toast(data.message || 'Напоминание создано');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        setLoading(leadFollowup, false);
      }
      return;
    }

    const leadAction = event.target.closest('[data-lead-action]');
    if (leadAction) {
      event.preventDefault();
      event.stopPropagation();
      const id = leadAction.dataset.leadId;
      const type = leadAction.dataset.leadAction;
      if (type === 'not-lead') {
        const proceed = await confirmAction(
          'Точно не лид?',
          'Это сохранится как обратная связь для будущего скоринга. Сам клиент и его история из базы не удалятся.',
          { danger: true }
        );
        if (!proceed) return;
      }
      setLoading(leadAction, true);
      try {
        const data = await api(`/api/leads/${id}/${type}`, { method: 'POST', body: '{}' });
        if (type === 'not-lead') {
          let undone = false;
          let reloadTimer = 0;
          toast(data.message || 'Отмечено как не лид', false, {
            undo: async () => {
              undone = true;
              clearTimeout(reloadTimer);
              setLoading(leadAction, true);
              try {
                const reopened = await api(`/api/leads/${id}/reopen`, { method: 'POST', body: '{}' });
                toast(reopened.message || 'Лид возвращён в работу');
                reloadSoon(300, focusKeyForElement(leadAction));
              } catch (undoError) {
                toast(undoError.message, true);
                setLoading(leadAction, false);
              }
            },
            duration: 8000,
          });
          flashStageSuccess(leadAction);
          reloadTimer = window.setTimeout(() => {
            if (!undone) reloadSoon(0, focusKeyForElement(leadAction));
          }, 8000);
          setLoading(leadAction, false);
          return;
        }
        toast(data.message || 'Лид обновлён');
        flashStageSuccess(leadAction);
        reloadSoon(450, focusKeyForElement(leadAction));
      } catch (error) {
        toast(error.message, true);
        setLoading(leadAction, false);
      }
      return;
    }

    const stage = event.target.closest('[data-stage]');
    if (stage) {
      event.preventDefault();
      event.stopPropagation();
      setLoading(stage, true);
      try {
        const data = await api(`/api/leads/${stage.dataset.leadId}/stage`, {
          method: 'POST',
          body: JSON.stringify({ status: stage.dataset.stage }),
        });
        toast(data.message || 'Стадия обновлена');
        flashStageSuccess(stage);
        reloadSoon(650, focusKeyForElement(stage));
      } catch (error) {
        toast(error.message, true);
        setLoading(stage, false);
      }
      return;
    }

    const task = event.target.closest('[data-task-complete]');
    if (task) {
      setLoading(task, true);
      try {
        const data = await api(`/api/tasks/${task.dataset.taskComplete}/complete`, {
          method: 'POST',
          body: '{}',
        });
        toast(data.message || 'Задача выполнена');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        setLoading(task, false);
      }
      return;
    }

    const row = event.target.closest('tr.clickable');
    if (row && !event.target.closest('a,button,input,select,textarea,label')) {
      location.href = row.dataset.href;
    }
  });

  document.addEventListener('keydown', (event) => {
    const row = event.target.closest?.('tr.clickable[data-href]');
    if (!row || !['Enter', ' '].includes(event.key)) return;
    event.preventDefault();
    location.href = row.dataset.href;
  });

  const playChangeAlert = () => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) return;
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.value = 880;
      gain.gain.value = 0.07;
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.18);
      osc.onended = () => { ctx.close(); };
    } catch (_error) {
      /* без звука */
    }
  };

  const knownFeedIds = new Set(
    [...document.querySelectorAll('[data-feed-id]')].map((node) => node.dataset.feedId).filter(Boolean),
  );
  let feedAlertsPrimed = knownFeedIds.size > 0;

  const notifyNewRadarChanges = (feed) => {
    const fresh = (feed.changes || []).filter((change) => {
      const key = `change-${change.id}`;
      return !knownFeedIds.has(key);
    });
    (feed.changes || []).forEach((change) => knownFeedIds.add(`change-${change.id}`));
    (feed.hot_leads || []).forEach((hot) => knownFeedIds.add(`hot-${hot.lead_id}`));
    if (!feedAlertsPrimed) {
      feedAlertsPrimed = true;
      return;
    }
    fresh.forEach((change) => {
      const label = change.primary_type_label || change.primary_type || 'изменение';
      toast(`@${change.username}: ${label} · ${change.summary}`);
      playChangeAlert();
    });
  };

  const renderRadarFeed = (feed) => {
    const list = document.querySelector('[data-radar-feed-list]');
    if (!list || !feed) return;
    const parts = [];
    (feed.changes || []).forEach((change) => {
      parts.push(
        `<a class="attention-item change-alert" href="/contacts/${change.contact_id}#significant-changes" data-feed-id="change-${change.id}">`
        + '<span class="attention-icon change">↑</span>'
        + `<div><b>@${escapeHtml(change.username)} · ${escapeHtml(change.primary_type_label || change.primary_type)}</b>`
        + `<p>${escapeHtml(change.summary)}</p>`
        + `<small>${change.previous_priority} → ${change.current_priority}</small></div><span>→</span></a>`
      );
    });
    (feed.hot_leads || []).forEach((hot) => {
      parts.push(
        `<a class="attention-item" href="/leads/${hot.lead_id}" data-feed-id="hot-${hot.lead_id}">`
        + `<span class="attention-icon hot">${hot.score}</span>`
        + `<div><b>@${escapeHtml(hot.username)}</b>`
        + `<p>${escapeHtml(hot.comment_preview)}</p>`
        + `<small>@${escapeHtml(hot.competitor)}</small></div><span>→</span></a>`
      );
    });
    if (!parts.length) {
      parts.push(
        '<div class="empty-box" data-radar-feed-empty>'
        + '<span class="empty-icon" aria-hidden="true"><i data-lucide="bell"></i></span>'
        + '<b>Пока спокойно</b><span>Изменения и HOT появятся после проверки Instagram и оценки комментариев.</span></div>'
      );
    }
    list.innerHTML = parts.join('');
    if (window.lucide?.createIcons) window.lucide.createIcons();
    const badge = document.querySelector('[data-radar-queue-badge]');
    if (badge) {
      const queueTotal = Number(feed.ai_pending || 0) + Number(feed.analyzing || 0);
      badge.textContent = queueTotal > 0 ? `Оценка: ${queueTotal}` : 'Оценка готова';
      badge.classList.toggle('warning', queueTotal > 0);
      badge.classList.toggle('success', queueTotal === 0);
    }
  };

  const applyGptQueueChip = (payload) => {
    const chip = document.querySelector('[data-gpt-queue]');
    if (!chip) return;
    const total = Number(payload.gpt_queue_total != null
      ? payload.gpt_queue_total
      : (Number(payload.ai_pending || 0) + Number(payload.analyzing || 0)));
    const count = chip.querySelector('[data-gpt-queue-count]');
    const label = chip.querySelector('[data-gpt-queue-label]');
    chip.hidden = total <= 0;
    if (count) count.textContent = String(total);
    if (label) {
      label.textContent = Number(payload.analyzing || 0) > 0 ? 'GPT…' : 'GPT';
    }
    chip.classList.toggle('is-busy', total > 0);
  };

  const applyScanProgress = (payload) => {
    applyGptQueueChip(payload);
    const progress = payload.progress || payload.scan_progress || {};
    const cycleRunning = Boolean(payload.cycle_running);
    const analysisBusy = Number(payload.analysis_queue || 0) > 0
      || Number(payload.analysis_in_flight || 0) > 0;
    const busy = cycleRunning || analysisBusy;
    const percent = Number(progress.percent || 0);
    const phase = String(progress.phase || 'idle');
    const phaseLabel = progress.phase_label || '';
    const detail = progress.detail || '';
    const handle = progress.current_handle ? `@${progress.current_handle}` : '';
    const runningDetail = [detail, handle].filter(Boolean).join(' · ')
      || (phase === 'comments'
        ? 'Сбор комментариев…'
        : phase === 'discover'
          ? 'Поиск Reels…'
          : phase === 'prepare'
            ? 'Подготовка…'
            : phase === 'finalize'
              ? 'Завершение…'
              : 'Идёт работа…');

    const statusPill = document.querySelector('[data-live-status-pill]');
    if (statusPill) {
      statusPill.classList.remove('busy', 'ok', 'error', 'safe', 'paused');
      if (payload.last_error && !cycleRunning) {
        statusPill.classList.add('error');
        statusPill.textContent = 'Есть ошибка';
      } else if (cycleRunning) {
        statusPill.classList.add('busy');
        statusPill.textContent = `Проверяем… ${percent}%`;
      } else if (analysisBusy) {
        statusPill.classList.add('busy');
        statusPill.textContent = 'Оценка сигналов…';
      } else {
        statusPill.classList.add('ok');
        statusPill.textContent = 'Готов · проверка не запущена';
      }
    }

    const banner = document.querySelector('[data-scan-progress-banner]');
    if (banner) {
      banner.hidden = !cycleRunning;
      const title = banner.querySelector('[data-scan-banner-title]');
      const detailEl = banner.querySelector('[data-scan-banner-detail]');
      const fill = banner.querySelector('[data-scan-banner-fill]');
      const pct = banner.querySelector('[data-scan-banner-percent]');
      const bar = banner.querySelector('[role="progressbar"]');
      if (cycleRunning) {
        if (title) title.textContent = phaseLabel || 'Идёт проверка Instagram';
        if (detailEl) detailEl.textContent = runningDetail;
        if (fill) fill.style.width = `${percent}%`;
        if (pct) pct.textContent = `${percent}%`;
        if (bar) bar.setAttribute('aria-valuenow', String(percent));
      }
    }

    const sideTitle = document.querySelector('[data-scan-side-title]');
    const sideDetail = document.querySelector('[data-scan-side-detail]');
    const sidePulse = document.querySelector('[data-scan-side-pulse]');
    if (sideTitle && sideDetail) {
      if (cycleRunning) {
        sideTitle.textContent = 'Идёт проверка';
        sideDetail.textContent = `${percent}% · ${phaseLabel || 'Instagram'}${handle ? ` · ${handle}` : ''}`;
        if (sidePulse) {
          sidePulse.classList.add('busy');
          sidePulse.classList.remove('bad');
        }
      } else if (payload.last_error) {
        sideTitle.textContent = 'Нужна проверка';
        sideDetail.textContent = String(payload.last_error).slice(0, 80);
        if (sidePulse) {
          sidePulse.classList.add('bad');
          sidePulse.classList.remove('busy');
        }
      } else if (analysisBusy) {
        sideTitle.textContent = 'Оценка сигналов';
        sideDetail.textContent = `В работе: ${payload.analysis_in_flight || 0} · очередь: ${payload.analysis_queue || 0}`;
        if (sidePulse) {
          sidePulse.classList.add('busy');
          sidePulse.classList.remove('bad');
        }
      } else {
        sideTitle.textContent = 'Готов к запуску';
        sideDetail.textContent = 'Поиск не запущен · нажмите «Найти лидов»';
        if (sidePulse) {
          sidePulse.classList.remove('busy', 'bad');
        }
      }
    }

    const live = document.querySelector('[data-radar-live]');
    if (live) {
      live.hidden = !busy;
      const title = live.querySelector('[data-radar-live-title]');
      const detailEl = live.querySelector('[data-radar-live-detail]');
      const pct = live.querySelector('[data-radar-live-percent]');
      const block = live.querySelector('[data-scan-progress-block]');
      if (cycleRunning) {
        if (title) title.textContent = phaseLabel || 'Идёт проверка Instagram';
        if (detailEl) detailEl.textContent = runningDetail;
        if (pct) {
          pct.hidden = false;
          pct.textContent = `${percent}%`;
        }
        if (block) {
          block.hidden = false;
          const fill = block.querySelector('[data-scan-progress-fill]');
          const bar = block.querySelector('[data-scan-progress-bar]');
          const phaseEl = block.querySelector('[data-scan-progress-phase]');
          const handleEl = block.querySelector('[data-scan-progress-handle]');
          if (fill) fill.style.width = `${percent}%`;
          if (bar) bar.setAttribute('aria-valuenow', String(percent));
          if (phaseEl) phaseEl.textContent = phaseLabel || 'Проверка';
          if (handleEl) handleEl.textContent = handle;
          const setStat = (sel, value) => {
            const el = block.querySelector(sel);
            if (el) el.textContent = String(value ?? 0);
          };
          setStat('[data-scan-stat-competitors]', progress.competitors_checked);
          setStat('[data-scan-stat-reels]', progress.reels_found);
          setStat('[data-scan-stat-comments]', progress.comments_created);
          setStat('[data-scan-stat-leads]', progress.leads_created);
        }
      } else if (Number(payload.analysis_in_flight || 0) > 0) {
        if (title) title.textContent = 'Идёт умная оценка';
        if (detailEl) {
          detailEl.textContent = `В работе: ${payload.analysis_in_flight}, в очереди: ${payload.analysis_queue || 0}`;
        }
        if (pct) pct.hidden = true;
        if (block) block.hidden = true;
      } else if (Number(payload.analysis_queue || 0) > 0) {
        if (title) title.textContent = 'Очередь оценки';
        if (detailEl) detailEl.textContent = `Ждут: ${payload.analysis_queue}`;
        if (pct) pct.hidden = true;
        if (block) block.hidden = true;
      }
    }

    document.querySelectorAll('[data-scan]').forEach((btn) => {
      if (!(btn instanceof HTMLButtonElement)) return;
      if (cycleRunning) {
        if (!btn.dataset.scanBusy) {
          btn.dataset.scanBusy = '1';
          btn.dataset.wasDisabled = btn.disabled ? '1' : '0';
          btn.dataset.scanLabel = btn.textContent || '';
        }
        btn.disabled = true;
        btn.textContent = `Проверка ${percent}%`;
      } else if (btn.dataset.scanBusy) {
        btn.textContent = btn.dataset.scanLabel || btn.textContent;
        delete btn.dataset.scanBusy;
        delete btn.dataset.scanLabel;
        delete btn.dataset.wasDisabled;
        btn.disabled = false;
      }
    });
    if (!cycleRunning) {
      const budgetRoot = document.querySelector('.radar-budget-card, #scan-quick');
      if (budgetRoot) refreshScanBudgetPreview(budgetRoot);
    }

    return busy;
  };

  const updateRadarLiveBanner = (payload) => {
    applyScanProgress(payload);
  };

  let radarPollTimer = null;
  let radarPollBusy = false;
  let scanProgressTimer = null;
  let scanProgressBusy = false;
  let cycleWasRunning = false;
  let scanSummaryShownForCycle = false;
  // Нельзя брать busy из DOM-баннера: AI_PENDING в HTML ≠ pipeline queue →
  // busy→idle на каждом poll давал бесконечный location.reload().
  let radarWasBusy = false;
  let radarQuietReloadScheduled = false;

  const showScanSummary = (payload) => {
    if (scanSummaryShownForCycle) return;
    scanSummaryShownForCycle = true;
    const stats = payload.last_stats || {};
    const progress = payload.progress || payload.scan_progress || {};
    const competitors = Number(stats.competitors_checked ?? progress.competitors_checked ?? 0);
    const reels = Number(stats.reels_found ?? progress.reels_found ?? 0);
    const comments = Number(stats.comments_created ?? progress.comments_created ?? 0);
    const leads = Number(stats.leads_created ?? progress.leads_created ?? 0);
    const errors = Number(stats.errors ?? 0);
    const budgetStop = Number(stats.budget_stops ?? 0) > 0;

    toast(
      payload.last_error
        ? `Поиск остановился · ${String(payload.last_error).slice(0, 80)}`
        : `Поиск завершён · ${leads} лидов · ${comments} сигналов · ${competitors} источников`,
      Boolean(payload.last_error)
    );

    const root = document.getElementById('scan-summary');
    if (!root) {
      if ((document.body.dataset.page || '').startsWith('/radar')) reloadSoon(800);
      return;
    }
    const setText = (sel, value) => {
      const el = root.querySelector(sel);
      if (el) el.textContent = String(value);
    };
    setText('[data-scan-sum-competitors]', competitors);
    setText('[data-scan-sum-reels]', reels);
    setText('[data-scan-sum-comments]', comments);
    setText('[data-scan-sum-leads]', leads);
    setText('[data-scan-sum-errors]', errors);
    setText('[data-scan-sum-budget]', budgetStop ? 'достигнут' : 'ок');
    const subtitle = root.querySelector('[data-scan-summary-subtitle]');
    if (subtitle) {
      subtitle.textContent = payload.last_error
        ? `Завершено с ошибкой: ${String(payload.last_error).slice(0, 120)}`
        : `Найдено потенциальных клиентов: ${leads}. Фактический расход может быть меньше максимума.`;
    }

    const previouslyFocused = document.activeElement;
    const ok = root.querySelector('[data-scan-summary-ok]');
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('is-open'));
    const close = () => {
      root.classList.remove('is-open');
      document.removeEventListener('keydown', onKeydown);
      root.removeEventListener('click', onBackdrop);
      if (ok) ok.onclick = null;
      setTimeout(() => {
        root.hidden = true;
        if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
        if ((document.body.dataset.page || '').startsWith('/radar')) {
          const next = findLeadsResultsUrl();
          setTimeout(() => { window.location.href = next; }, 400);
        } else {
          reloadSoon(400);
        }
      }, 180);
    };
    const onKeydown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close();
      }
    };
    const onBackdrop = (event) => {
      if (event.target === root) close();
    };
    if (ok) ok.onclick = close;
    root.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKeydown);
    if (ok instanceof HTMLElement) ok.focus();
  };

  const noteCycleTransition = (payload) => {
    const running = Boolean(payload.cycle_running);
    if (running) scanSummaryShownForCycle = false;
    if (cycleWasRunning && !running) showScanSummary(payload);
    cycleWasRunning = running;
  };

  const pollRadarFeed = async () => {
    if (radarPollBusy) return;
    radarPollBusy = true;
    try {
      const feed = await api(withScanVertical('/api/radar/feed?limit=8'), { method: 'GET' });
      notifyNewRadarChanges(feed);
      renderRadarFeed(feed);
      updateRadarLiveBanner(feed);
      noteCycleTransition(feed);
      const stillBusy = feed.cycle_running
        || Number(feed.analysis_queue || 0) > 0
        || Number(feed.analysis_in_flight || 0) > 0;
      // Один reload после реального busy→idle (скан/очередь GPT), без цикла.
      if (radarWasBusy && !stillBusy && !radarQuietReloadScheduled) {
        const summary = document.getElementById('scan-summary');
        if (!summary || summary.hidden) {
          radarQuietReloadScheduled = true;
          reloadSoon(800);
        }
      }
      if (stillBusy) radarQuietReloadScheduled = false;
      radarWasBusy = stillBusy;
    } catch (_error) {
      /* тихий poll */
    } finally {
      radarPollBusy = false;
    }
  };

  const pollScanProgress = async () => {
    if (scanProgressBusy) return;
    if ((document.body.dataset.page || '').startsWith('/radar')) return;
    scanProgressBusy = true;
    try {
      const payload = await api('/api/scan/progress', { method: 'GET' });
      applyScanProgress(payload);
      noteCycleTransition(payload);
      radarWasBusy = Boolean(payload.cycle_running)
        || Number(payload.analysis_queue || 0) > 0
        || Number(payload.analysis_in_flight || 0) > 0;
    } catch (_error) {
      /* тихий poll */
    } finally {
      scanProgressBusy = false;
    }
  };

  const startRadarPolling = () => {
    if (!(document.body.dataset.page || '').startsWith('/radar')) return;
    pollRadarFeed();
    if (radarPollTimer) clearInterval(radarPollTimer);
    radarPollTimer = setInterval(pollRadarFeed, 2000);
  };

  const startGlobalScanProgressPolling = () => {
    pollScanProgress();
    if (scanProgressTimer) clearInterval(scanProgressTimer);
    scanProgressTimer = setInterval(pollScanProgress, 2000);
  };

  if ((document.body.dataset.page || '').startsWith('/radar')) {
    startRadarPolling();
    const budgetRoot = document.querySelector('.radar-budget-card');
    if (budgetRoot) refreshScanBudgetPreview(budgetRoot);
  } else {
    startGlobalScanProgressPolling();
  }

  const onScanBudgetInput = (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (
      target.name === 'scan_budget'
      || target.name === 'scan_budget_quick'
      || target.matches('[data-custom-scan-budget], [data-custom-scan-budget-quick]')
    ) {
      const root = target.closest('.radar-budget-card, #scan-quick') || document;
      refreshScanBudgetPreview(root);
    }
  };
  document.addEventListener('change', onScanBudgetInput);
  document.addEventListener('input', onScanBudgetInput);

  const chatRoot = document.querySelector('[data-agent-chat-root]');
  if (chatRoot) {
    const messagesEl = chatRoot.querySelector('[data-agent-messages]');
    const emptyEl = chatRoot.querySelector('[data-agent-empty]');
    const typingEl = chatRoot.querySelector('[data-agent-typing]');
    const sessionList = chatRoot.querySelector('[data-agent-session-list]');
    const sessionInput = chatRoot.querySelector('[data-agent-session-id]');
    const form = chatRoot.querySelector('[data-agent-chat-form]');
    let activeSessionId = sessionInput?.value || '';

    const emptyTemplate = emptyEl ? emptyEl.outerHTML : '';

    const setTyping = (visible) => {
      if (!typingEl) return;
      typingEl.hidden = !visible;
      typingEl.setAttribute('aria-hidden', String(!visible));
    };

    const renderMessages = (rows) => {
      if (!messagesEl) return;
      const list = rows || [];
      if (!list.length) {
        messagesEl.innerHTML = emptyTemplate;
        return;
      }
      messagesEl.innerHTML = list.map((msg, index) => {
        const role = msg.role === 'user' ? 'user' : 'assistant';
        let extra = '';
        if (msg.pending_status === 'pending' && msg.pending_action) {
          extra = `<div class="agent-chat-approve"><button type="button" class="btn success tiny" data-agent-approve="${msg.id}">Подтвердить</button></div>`;
        }
        if (role === 'assistant' && msg.content && getAgentContactId()) {
          extra = `<div class="agent-chat-actions"><button type="button" class="btn ghost tiny" data-agent-save-note>В заметку</button></div>${extra}`;
        }
        const delay = Math.min(index, 6) * 40;
        return `<article class="agent-chat-msg ${role} msg-enter" style="--msg-delay:${delay}ms"><div class="agent-chat-bubble">${escapeHtml(msg.content || '')}</div>${extra}</article>`;
      }).join('');
      messagesEl.scrollTop = messagesEl.scrollHeight;
    };

    const loadSessions = async () => {
      const data = await api('/api/agent/sessions', { method: 'GET' });
      if (!sessionList) return;
      const sessions = data.sessions || [];
      if (!sessions.length) {
        sessionList.innerHTML = '<p class="agent-session-empty muted">Нет сессий — начните новый чат</p>';
        return;
      }
      sessionList.innerHTML = sessions.map((s) => (
        `<button type="button" class="agent-session-item${String(s.id) === String(activeSessionId) ? ' active' : ''}" data-session-id="${s.id}">${escapeHtml(s.title || ('Чат #' + s.id))}</button>`
      )).join('');
    };

    const loadMessages = async (sessionId) => {
      if (!sessionId) return;
      const data = await api(`/api/agent/sessions/${sessionId}/messages`, { method: 'GET' });
      renderMessages(data.messages || []);
    };

    sessionList?.addEventListener('click', async (event) => {
      const btn = event.target.closest('[data-session-id]');
      if (!btn) return;
      activeSessionId = btn.getAttribute('data-session-id') || '';
      if (sessionInput) sessionInput.value = activeSessionId;
      await loadSessions();
      await loadMessages(activeSessionId);
    });

    chatRoot.querySelector('[data-agent-new-session]')?.addEventListener('click', async () => {
      const created = await api('/api/agent/sessions', { method: 'POST', body: JSON.stringify({ title: 'Новый чат' }) });
      activeSessionId = String(created.session_id);
      if (sessionInput) sessionInput.value = activeSessionId;
      await loadSessions();
      renderMessages([]);
    });

    messagesEl?.addEventListener('click', async (event) => {
      const saveBtn = event.target.closest('[data-agent-save-note]');
      if (saveBtn) {
        const bubble = saveBtn.closest('.agent-chat-msg, .agent-result-rich')?.querySelector('.agent-chat-bubble, .agent-result-body');
        await saveAgentAnswerToNote(bubble?.textContent || '', saveBtn);
        return;
      }
      const btn = event.target.closest('[data-agent-approve]');
      if (!btn) return;
      const messageId = btn.getAttribute('data-agent-approve');
      setLoading(btn, true);
      try {
        const result = await api('/api/agent/approve', {
          method: 'POST',
          body: JSON.stringify({ message_id: Number(messageId) }),
        });
        toast(result.ok ? 'Действие выполнено' : 'Ошибка выполнения', !result.ok);
        await loadMessages(activeSessionId);
      } catch (error) {
        toast(error.message, true);
      } finally {
        setLoading(btn, false);
      }
    });

    form?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const submit = form.querySelector('[type="submit"]');
      const query = form.querySelector('textarea[name="query"]');
      if (!(query instanceof HTMLTextAreaElement) || !query.value.trim()) return;
      setLoading(submit, true);
      setTyping(true);
      try {
        const payload = {
          query: query.value.trim(),
          ...readAgentContext(),
        };
        if (form.dataset.pendingLeadId) {
          payload.lead_id = Number(form.dataset.pendingLeadId);
          delete form.dataset.pendingLeadId;
        }
        if (form.dataset.pendingContactId) {
          payload.contact_id = Number(form.dataset.pendingContactId);
          delete form.dataset.pendingContactId;
        }
        if (activeSessionId) payload.session_id = Number(activeSessionId);
        const data = await api('/api/agent/chat', { method: 'POST', body: JSON.stringify(payload) });
        activeSessionId = String(data.session_id);
        if (sessionInput) sessionInput.value = activeSessionId;
        query.value = '';
        await loadSessions();
        await loadMessages(activeSessionId);
        toast(data.pending_action ? 'Нужно подтверждение' : (data.grounded ? 'Grounded ответ' : 'Ответ получен'));
      } catch (error) {
        toast(error.message, true);
      } finally {
        setTyping(false);
        setLoading(submit, false);
      }
    });

    form?.querySelector('textarea[name="query"]')?.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' || event.shiftKey) return;
      event.preventDefault();
      form.requestSubmit();
    });

    (async () => {
      try {
        await loadSessions();
        if (!activeSessionId) {
          const created = await api('/api/agent/sessions', { method: 'POST', body: JSON.stringify({ title: 'Lead Radar AI' }) });
          activeSessionId = String(created.session_id);
          if (sessionInput) sessionInput.value = activeSessionId;
          await loadSessions();
        } else {
          await loadMessages(activeSessionId);
        }
      } catch (error) {
        toast(error instanceof Error ? error.message : 'Не удалось загрузить чат', true);
      }
    })();
  }

  const refreshNavUsage = async () => {
    const root = document.querySelector('[data-nav-usage]');
    if (!(root instanceof HTMLElement)) return;
    try {
      const preview = await api(withScanVertical('/api/scan/preview'), { method: 'GET' });
      const used = Number(preview.used_this_month || 0);
      const limit = preview.monthly_hard_limit;
      const text = root.querySelector('[data-nav-usage-text]');
      const fill = root.querySelector('[data-nav-usage-fill]');
      const bar = root.querySelector('[data-nav-usage-bar]');
      const usedLabel = used.toLocaleString('ru-RU');
      if (text) {
        text.textContent = limit != null
          ? `${usedLabel} / ${Number(limit).toLocaleString('ru-RU')} credits`
          : `${usedLabel} credits за месяц`;
      }
      const pct = limit ? Math.max(0, Math.min(100, Math.round((used / Number(limit)) * 100))) : 0;
      if (fill instanceof HTMLElement) fill.style.width = `${pct}%`;
      if (bar instanceof HTMLElement) bar.setAttribute('aria-valuenow', String(pct));
    } catch (_error) {
      /* usage preview недоступен — не подставляем fake */
    }
  };

  const refreshNavHotBadge = async () => {
    const badge = document.querySelector('[data-nav-hot-badge]');
    if (!(badge instanceof HTMLElement)) return;
    try {
      const feed = await api(withScanVertical('/api/radar/feed?limit=1'), { method: 'GET' });
      const hot = Number((feed.overview && feed.overview.hot) || (feed.hot_leads || []).length || 0);
      if (hot > 0) {
        badge.hidden = false;
        badge.textContent = hot > 99 ? '99+' : String(hot);
      } else {
        badge.hidden = true;
      }
    } catch (_error) {
      badge.hidden = true;
    }
  };

  const closeLeadExplain = () => {
    const root = document.getElementById('lead-explain');
    if (!(root instanceof HTMLElement)) return;
    root.classList.remove('is-open');
    setTimeout(() => { root.hidden = true; }, 180);
  };

  const showLeadExplain = async (leadId) => {
    const root = document.getElementById('lead-explain');
    if (!(root instanceof HTMLElement)) return;
    const body = root.querySelector('[data-lead-explain-body]');
    const subtitle = root.querySelector('[data-lead-explain-subtitle]');
    const openLink = root.querySelector('[data-lead-explain-open]');
    if (body) body.innerHTML = '<p class="muted">Загружаю grounded explain…</p>';
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('is-open'));
    try {
      const data = await api(`/api/leads/${leadId}/explain`, { method: 'GET' });
      if (subtitle) {
        subtitle.textContent = `@${data.username || '—'} · score ${data.score}/100 · только данные из БД`;
      }
      if (openLink instanceof HTMLAnchorElement) {
        openLink.href = `/leads/${leadId}#ai-evidence`;
      }
      const contributions = (data.contributions || [])
        .map((item) => `<li><b>+${escapeHtml(String(item.score))}</b> ${escapeHtml(item.label || item.key)}</li>`)
        .join('');
      const evidence = (data.evidence || [])
        .map((item) => `<li>${escapeHtml(String(item))}</li>`)
        .join('');
      const evidenceIds = (data.evidence_ids || []).length
        ? `<p class="muted">Evidence IDs: ${(data.evidence_ids || []).map((id) => escapeHtml(String(id))).join(', ')}</p>`
        : '<p class="muted">Evidence IDs не сохранены для этого лида.</p>';
      if (body) {
        body.innerHTML = `
          <p class="lead-explain-reason">${escapeHtml(data.reason || data.short_reason || 'Объяснение ещё не сформировано.')}</p>
          <p class="muted">${escapeHtml(data.comment_preview || '')}</p>
          <h4>Почему Lead Radar считает его покупателем</h4>
          <ul class="lead-explain-factors">${contributions || '<li class="muted">Факторы оценки не сохранены</li>'}</ul>
          <h4>Evidence</h4>
          <ul class="lead-explain-evidence">${evidence || '<li class="muted">Текстовые evidence не сохранены</li>'}</ul>
          ${evidenceIds}
        `;
      }
    } catch (error) {
      if (body) body.innerHTML = `<p class="alert error">${escapeHtml(error.message || 'Не удалось загрузить')}</p>`;
    }
  };

  const takeLeadIntoWork = async (leadId, button) => {
    setLoading(button, true);
    try {
      const data = await api(`/api/leads/${leadId}/take`, { method: 'POST', body: '{}' });
      toast(data.message || 'Лид взят в работу');
      reloadSoon(500);
    } catch (error) {
      toast(error.message, true);
      setLoading(button, false);
    }
  };

  const readFindLeadsPrefs = () => {
    try {
      return JSON.parse(sessionStorage.getItem('lr:find-leads') || '{}') || {};
    } catch (_error) {
      return {};
    }
  };

  const findLeadsResultsUrl = () => {
    const prefs = readFindLeadsPrefs();
    const heat = prefs.heat || 'hot';
    const kind = heat === 'hot' ? 'hot' : (heat === 'warm' ? 'warm' : '');
    const base = withScanVertical('/radar');
    if (!kind) return `${base}#find-results`;
    const join = base.includes('?') ? '&' : '?';
    return `${base}${join}kind=${encodeURIComponent(kind)}#find-results`;
  };

  const FIND_CATEGORY_PRODUCTS = {
    chairs: ['CHAIR', 'ARMCHAIR', 'STOOL', 'RATTAN_ARMCHAIR', 'RATTAN_BAR_STOOL'],
    tables: ['TABLE', 'DINING'],
    sets: ['SET', 'DINING_SET', 'GARDEN_SET', 'KOMPLEKT'],
    outdoor: ['OUTDOOR', 'GARDEN', 'TERRACE', 'RATTAN_GARDEN'],
    horeca: ['HORECA', 'CAFE', 'RESTAURANT', 'BAR'],
    office: ['OFFICE'],
    custom: ['CUSTOM', 'ORDER', 'НА ЗАКАЗ'],
    rattan: ['RATTAN', 'РОТАНГ', 'ПЛЕТЕН'],
    all: [],
  };

  const FIND_AUDIENCE_INTENTS = {
    buyers_now: ['BUY', 'QUANTITY', 'PRICE', 'AVAILABILITY', 'DELIVERY', 'CONTACT'],
    interested: ['CATALOG', 'COLOR', 'SIZE', 'LOCATION', 'PRICE', 'OTHER'],
    companies_soon: ['BUY', 'QUANTITY', 'DELIVERY', 'CONTACT', 'LOCATION'],
    makers: ['QUANTITY', 'CATALOG', 'BUY', 'PRICE'],
  };

  const FIND_AUDIENCE_ROLES = {
    buyers_now: [],
    interested: [],
    companies_soon: ['B2B_HORECA', 'DESIGNER_CONTRACTOR'],
    makers: ['WHOLESALER', 'MANUFACTURER', 'DEALER', 'RAW_MATERIAL_BUYER'],
  };

  const cardMatchesFindPrefs = (card, prefs, kind) => {
    const heat = card.getAttribute('data-lead-heat') || 'cool';
    if (kind === 'hot' && heat !== 'hot') return false;
    if (kind === 'warm' && heat !== 'hot' && heat !== 'warm') return false;

    const intent = String(card.getAttribute('data-lead-intent') || '').toUpperCase();
    const role = String(card.getAttribute('data-lead-role') || 'UNKNOWN').toUpperCase();
    const product = String(card.getAttribute('data-lead-product') || '').toUpperCase();
    const audience = prefs.audience || '';

    if (audience && audience !== 'interested') {
      const intents = FIND_AUDIENCE_INTENTS[audience] || [];
      const roles = FIND_AUDIENCE_ROLES[audience] || [];
      const intentOk = !intents.length || intents.includes(intent);
      const roleOk = !roles.length || roles.includes(role) || role === 'UNKNOWN';
      // Для makers/companies роль усиливает, но UNKNOWN не отсекаем жёстко.
      if (audience === 'makers') {
        const makerish = roles.includes(role)
          || product.includes('RATTAN')
          || intents.includes(intent);
        if (!makerish && role !== 'UNKNOWN') return false;
      } else if (audience === 'buyers_now' && intents.length && !intentOk) {
        return false;
      } else if (audience === 'companies_soon') {
        if (!(roleOk || product.includes('HORECA') || intents.includes(intent))) {
          return false;
        }
      }
    }

    const categories = Array.isArray(prefs.categories) ? prefs.categories : [];
    const activeCats = categories.filter((value) => value && value !== 'all');
    if (activeCats.length) {
      const matched = activeCats.some((cat) => {
        const needles = FIND_CATEGORY_PRODUCTS[cat] || [String(cat).toUpperCase()];
        if (!needles.length) return true;
        return needles.some((needle) => product.includes(String(needle).toUpperCase()));
      });
      // Пустой product не отсекаем — scoring мог ещё не проставить категорию.
      if (product && !matched) return false;
    }
    return true;
  };

  const applyFindLeadsCardFilter = (kind) => {
    const root = document.querySelector('[data-find-results]');
    const prefs = readFindLeadsPrefs();
    const note = root instanceof HTMLElement ? root.querySelector('[data-find-filter-note]') : null;
    const empty = root instanceof HTMLElement ? root.querySelector('[data-find-filter-empty]') : null;
    const cards = root instanceof HTMLElement ? [...root.querySelectorAll('.find-lead-card')] : [];
    let visibleCards = 0;
    cards.forEach((card) => {
      if (!(card instanceof HTMLElement)) return;
      const show = cardMatchesFindPrefs(card, prefs, kind);
      card.hidden = !show;
      if (show) visibleCards += 1;
    });

    const rows = [...document.querySelectorAll('[data-find-row]')];
    let visibleRows = 0;
    rows.forEach((row) => {
      if (!(row instanceof HTMLElement)) return;
      const heat = row.getAttribute('data-lead-heat') || 'none';
      // Строки без лида скрываем при любом heat-фильтре; при «все» оставляем.
      let show = true;
      if (kind === 'hot' || kind === 'warm') {
        if (heat === 'none') show = false;
        else show = cardMatchesFindPrefs(row, prefs, kind);
      } else if (prefs.audience || (Array.isArray(prefs.categories) && prefs.categories.filter((v) => v && v !== 'all').length)) {
        if (heat === 'none') show = false;
        else show = cardMatchesFindPrefs(row, prefs, kind);
      }
      row.hidden = !show;
      if (show) visibleRows += 1;
    });

    const bits = [];
    if (kind === 'hot') bits.push('только горячие');
    else if (kind === 'warm') bits.push('горячие + тёплые');
    if (prefs.audience) bits.push(`аудитория: ${prefs.audience}`);
    if (Array.isArray(prefs.categoryLabels) && prefs.categoryLabels.length) {
      bits.push(`категории: ${prefs.categoryLabels.join(', ')}`);
    } else if (Array.isArray(prefs.categories) && prefs.categories.length) {
      bits.push(`категории: ${prefs.categories.join(', ')}`);
    }
    if (note instanceof HTMLElement) {
      if (!bits.length && !kind) {
        note.hidden = true;
        note.textContent = '';
      } else {
        note.hidden = false;
        note.textContent = `Фильтр поиска: ${bits.join(' · ') || 'все'} · карточек ${visibleCards} · строк ${visibleRows}`;
      }
    }
    if (empty instanceof HTMLElement) {
      empty.hidden = visibleCards > 0 || cards.length === 0;
    }
    if (root instanceof HTMLElement) {
      root.querySelectorAll('[data-find-filter-kind]').forEach((btn) => {
        if (!(btn instanceof HTMLElement)) return;
        const value = btn.getAttribute('data-find-filter-kind') || '';
        btn.classList.toggle('primary', value === (kind || ''));
        btn.classList.toggle('ghost', value !== (kind || ''));
      });
    }
  };

  const scrollToFindResultsIfNeeded = () => {
    const target = document.getElementById('find-results') || document.querySelector('[data-find-results]');
    if (!(target instanceof HTMLElement)) return;
    let shouldScroll = window.location.hash === '#find-results';
    try {
      if (sessionStorage.getItem('lr:find-leads-pending-results') === '1') {
        shouldScroll = true;
        sessionStorage.removeItem('lr:find-leads-pending-results');
      }
    } catch (_error) {
      /* ignore */
    }
    if (!shouldScroll) return;
    requestAnimationFrame(() => {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  };

  const syncRadarKindSelect = (kind) => {
    const select = document.querySelector('.radar-filters select[name="kind"]');
    if (!(select instanceof HTMLSelectElement)) return;
    if (kind === 'hot' || kind === 'warm' || kind === '') {
      select.value = kind;
    }
  };

  const clearFindLeadsPrefsFilter = () => {
    const prefs = readFindLeadsPrefs();
    const next = {
      ...prefs,
      heat: 'all',
      audience: '',
      categories: ['all'],
      categoryLabels: ['Всё'],
    };
    try {
      sessionStorage.setItem('lr:find-leads', JSON.stringify(next));
    } catch (_error) {
      /* ignore */
    }
    applyFindLeadsCardFilter('');
    syncRadarKindSelect('');
    const url = `${withScanVertical('/radar')}#find-results`;
    window.history.replaceState({}, '', url);
    toast('Фильтр поиска сброшен');
  };

  const enhanceFindLeadsResultFilters = () => {
    const root = document.querySelector('[data-find-results]');
    if (!(root instanceof HTMLElement)) return;
    const params = new URLSearchParams(window.location.search);
    const urlKind = params.get('kind') || '';
    const prefs = readFindLeadsPrefs();
    const initial = urlKind === 'hot' || urlKind === 'warm'
      ? urlKind
      : (prefs.heat === 'hot' ? 'hot' : (prefs.heat === 'warm' ? 'warm' : ''));
    applyFindLeadsCardFilter(initial === 'all' ? '' : initial);
    syncRadarKindSelect(initial === 'all' ? '' : initial);
    root.addEventListener('click', (event) => {
      const reset = event.target.closest('[data-find-filter-reset]');
      if (reset) {
        event.preventDefault();
        clearFindLeadsPrefsFilter();
        return;
      }
      const btn = event.target.closest('[data-find-filter-kind]');
      if (!(btn instanceof HTMLElement)) return;
      const kind = btn.getAttribute('data-find-filter-kind') || '';
      const prefsNow = readFindLeadsPrefs();
      prefsNow.heat = kind === 'hot' ? 'hot' : (kind === 'warm' ? 'warm' : 'all');
      try {
        sessionStorage.setItem('lr:find-leads', JSON.stringify(prefsNow));
      } catch (_error) {
        /* ignore */
      }
      applyFindLeadsCardFilter(kind);
      syncRadarKindSelect(kind);
      const next = withScanVertical('/radar');
      const join = next.includes('?') ? '&' : '?';
      const url = kind ? `${next}${join}kind=${encodeURIComponent(kind)}#find-results` : `${next}#find-results`;
      window.history.replaceState({}, '', url);
    });
  };

  const enhanceFindLeadsWizard = () => {
    const root = document.querySelector('[data-find-leads]');
    if (!(root instanceof HTMLElement)) return;
    let step = 1;
    const labels = {
      audience: {
        buyers_now: 'Покупателей мебели',
        interested: 'Интересующихся мебелью',
        companies_soon: 'Компании с будущей потребностью',
        makers: 'Производители / дилеры',
      },
      heat: {
        hot: 'Только горячие',
        warm: 'Горячие + тёплые',
        all: 'Все потенциальные',
      },
      geo: {
        UZ: 'Узбекистан',
        Tashkent: 'Ташкент',
        Samarkand: 'Самарканд',
        Bukhara: 'Бухара',
        Andijan: 'Андижан',
        Fergana: 'Фергана',
      },
      category: {
        chairs: 'Стулья',
        tables: 'Столы',
        sets: 'Комплекты',
        outdoor: 'Уличная мебель',
        horeca: 'HoReCa мебель',
        office: 'Офисная мебель',
        custom: 'Мебель на заказ',
        rattan: 'Искусственный ротанг',
        all: 'Всё',
      },
      lang: {
        ru: 'RU',
        uz_lat: 'UZ lat',
        uz_cyr: 'UZ кир',
        mixed: 'RU/UZ',
      },
      source: {
        instagram: 'Instagram',
        telegram: 'Telegram',
        tiktok: 'TikTok',
        facebook: 'Facebook',
        maps: 'Google / Карты',
        olx: 'OLX.uz',
        glotr: 'Glotr.uz',
        tenders: 'Тендеры',
        web: 'Web',
      },
    };

    const syncChoices = (selector) => {
      root.querySelectorAll(selector).forEach((label) => {
        if (!(label instanceof HTMLElement)) return;
        const input = label.querySelector('input');
        label.classList.toggle('is-selected', Boolean(input && input.checked));
      });
    };

    const updateSummary = () => {
      const sources = [...root.querySelectorAll('input[name="find_source"]:checked')]
        .map((el) => labels.source[el.value] || el.value);
      const audience = root.querySelector('input[name="find_audience"]:checked');
      const heat = root.querySelector('input[name="find_heat"]:checked');
      const geo = root.querySelector('input[name="find_geo"]:checked');
      const cats = [...root.querySelectorAll('input[name="find_category"]:checked')]
        .map((el) => labels.category[el.value] || el.value);
      const langs = [...root.querySelectorAll('input[name="find_lang"]:checked')]
        .map((el) => labels.lang[el.value] || el.value);
      const set = (sel, value) => {
        const node = root.querySelector(sel);
        if (node) node.textContent = value;
      };
      set('[data-sum-sources]', sources.length ? sources.join(', ') : 'Не выбрано');
      set('[data-sum-audience]', audience ? (labels.audience[audience.value] || audience.value) : '—');
      set('[data-sum-category]', cats.length ? cats.join(', ') : '—');
      set('[data-sum-geo]', geo ? (labels.geo[geo.value] || geo.value) : '—');
      set('[data-sum-lang]', langs.length ? langs.join(' + ') : '—');
      set('[data-sum-heat]', heat ? (labels.heat[heat.value] || heat.value) : '—');
      const langSoft = root.querySelector('[data-find-lang-soft]');
      if (langSoft) {
        langSoft.textContent = langs.length
          ? `Ориентир: ${langs.join(' + ')}. Поиск не режет выдачу по языку и не выдумывает перевод.`
          : 'Язык не выбран — ориентир широкий. Поиск всё равно идёт по публичным сигналам без языкового среза.';
      }
      const geoSoft = root.querySelector('[data-find-geo-soft]');
      if (geoSoft) {
        const geoLabel = geo ? (labels.geo[geo.value] || geo.value) : 'не выбрана';
        geoSoft.textContent = geo && geo.value !== 'UZ'
          ? `Ориентир: ${geoLabel}. Если город в сигнале не подтверждён — останется «неизвестно», без подстановки.`
          : 'География — мягкий ориентир по Узбекистану. Неподтверждённый город не выдумываем.';
      }
      const sumSoft = root.querySelector('[data-sum-soft]');
      if (sumSoft) {
        sumSoft.textContent = 'Язык и город — ориентир для вас, не жёсткий фильтр запуска.';
      }
      const warn = root.querySelector('[data-find-heat-warn]');
      if (warn) warn.hidden = !(heat && heat.value === 'all');
      const hint = root.querySelector('[data-find-summary-hint]');
      const cta = root.querySelector('[data-find-summary-cta]');
      if (hint) {
        hint.textContent = step >= 4
          ? 'Готово к запуску'
          : step === 1
            ? 'Следующий шаг: что ищем'
            : step === 2
              ? 'Следующий шаг: параметры'
              : 'Следующий шаг: запуск';
      }
      if (cta instanceof HTMLButtonElement) {
        cta.textContent = step >= 4 ? 'Найти лидов →' : 'Далее →';
        cta.dataset.findNext = step >= 4 ? '' : '1';
        if (step >= 4) {
          cta.removeAttribute('data-find-next');
          cta.setAttribute('data-scan', '');
          cta.setAttribute('data-find-launch', '');
        } else {
          cta.removeAttribute('data-scan');
          cta.setAttribute('data-find-next', '');
        }
      }
      try {
        sessionStorage.setItem('lr:find-leads', JSON.stringify({
          sources: [...root.querySelectorAll('input[name="find_source"]:checked')].map((el) => el.value),
          audience: audience?.value,
          heat: heat?.value,
          geo: geo?.value,
          categories: [...root.querySelectorAll('input[name="find_category"]:checked')].map((el) => el.value),
          categoryLabels: cats,
          languages: [...root.querySelectorAll('input[name="find_lang"]:checked')].map((el) => el.value),
          languageLabels: langs,
          step,
        }));
      } catch (_error) {
        /* ignore quota */
      }
    };

    const showStep = (next) => {
      step = Math.max(1, Math.min(4, next));
      root.querySelectorAll('[data-find-panel]').forEach((panel) => {
        if (!(panel instanceof HTMLElement)) return;
        const id = Number(panel.getAttribute('data-find-panel'));
        const active = id === step;
        panel.hidden = !active;
        panel.classList.toggle('is-active', active);
      });
      root.querySelectorAll('[data-find-step-tab]').forEach((tab) => {
        if (!(tab instanceof HTMLElement)) return;
        const id = Number(tab.getAttribute('data-find-step-tab'));
        tab.classList.toggle('is-active', id === step);
        tab.classList.toggle('is-done', id < step);
      });
      updateSummary();
      if (window.lucide && typeof window.lucide.createIcons === 'function') {
        window.lucide.createIcons();
      }
    };

    const applyPreset = (name) => {
      const setRadio = (nameAttr, value) => {
        const input = root.querySelector(`input[name="${nameAttr}"][value="${value}"]`);
        if (input instanceof HTMLInputElement) {
          input.checked = true;
        }
      };
      const setCats = (values) => {
        root.querySelectorAll('input[name="find_category"]').forEach((el) => {
          if (el instanceof HTMLInputElement) el.checked = values.includes(el.value);
        });
      };
      const ig = root.querySelector('input[name="find_source"][value="instagram"]');
      if (ig instanceof HTMLInputElement) ig.checked = true;
      if (name === 'quick') {
        setRadio('find_audience', 'buyers_now');
        setRadio('find_heat', 'hot');
        setCats(['all']);
      } else if (name === 'horeca') {
        setRadio('find_audience', 'companies_soon');
        setRadio('find_heat', 'warm');
        setCats(['horeca', 'chairs', 'tables']);
      } else if (name === 'wholesale') {
        setRadio('find_audience', 'makers');
        setRadio('find_heat', 'hot');
        setCats(['rattan', 'custom']);
      }
      syncChoices('.find-source, .find-choice, .find-chip');
      updateSummary();
      showStep(2);
      toast('Пресет заполнен — проверьте шаги');
    };

    root.addEventListener('click', (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const next = target.closest('[data-find-next]');
      const prev = target.closest('[data-find-prev]');
      const preset = target.closest('[data-find-preset]');
      const tab = target.closest('[data-find-step-tab]');
      if (preset) {
        applyPreset(preset.getAttribute('data-find-preset') || 'quick');
        return;
      }
      if (next && !next.hasAttribute('data-scan')) {
        event.preventDefault();
        showStep(step + 1);
        return;
      }
      if (prev) {
        event.preventDefault();
        showStep(step - 1);
        return;
      }
      if (tab) {
        const id = Number(tab.getAttribute('data-find-step-tab'));
        if (id >= 1 && id <= 4) showStep(id);
      }
    });

    root.addEventListener('change', (event) => {
      const target = event.target;
      if (!(target instanceof HTMLInputElement)) return;
      if (target.name === 'find_source' && target.checked && target.closest('.is-soon')) {
        target.checked = false;
        toast('Источник ещё не подключён', true);
      }
      if (target.name === 'find_category' && target.value === 'all' && target.checked) {
        root.querySelectorAll('input[name="find_category"]').forEach((el) => {
          if (el instanceof HTMLInputElement && el.value !== 'all') el.checked = false;
        });
      } else if (target.name === 'find_category' && target.value !== 'all' && target.checked) {
        const all = root.querySelector('input[name="find_category"][value="all"]');
        if (all instanceof HTMLInputElement) all.checked = false;
      }
      syncChoices('.find-source, .find-choice, .find-chip');
      updateSummary();
    });

    syncChoices('.find-source, .find-choice, .find-chip');
    const saved = readFindLeadsPrefs();
    if (saved.heat) {
      const heatInput = root.querySelector(`input[name="find_heat"][value="${saved.heat}"]`);
      if (heatInput instanceof HTMLInputElement) heatInput.checked = true;
    }
    if (saved.audience) {
      const audienceInput = root.querySelector(`input[name="find_audience"][value="${saved.audience}"]`);
      if (audienceInput instanceof HTMLInputElement) audienceInput.checked = true;
    }
    if (Array.isArray(saved.categories) && saved.categories.length) {
      root.querySelectorAll('input[name="find_category"]').forEach((el) => {
        if (el instanceof HTMLInputElement) {
          el.checked = saved.categories.includes(el.value);
        }
      });
    }
    syncChoices('.find-source, .find-choice, .find-chip');
    updateSummary();
    const startStep = Number(saved.step) || 1;
    showStep(Math.max(1, Math.min(4, startStep)));
  };

  enhanceFindLeadsWizard();
  enhanceFindLeadsResultFilters();
  scrollToFindResultsIfNeeded();
  refreshNavUsage();
  refreshNavHotBadge();

  document.addEventListener('click', (event) => {
    const explainBtn = event.target.closest('[data-lead-explain]');
    if (explainBtn) {
      event.preventDefault();
      const leadId = explainBtn.getAttribute('data-lead-explain');
      if (leadId) showLeadExplain(leadId);
      return;
    }
    const takeBtn = event.target.closest('[data-lead-take]');
    if (takeBtn) {
      event.preventDefault();
      const leadId = takeBtn.getAttribute('data-lead-take');
      if (leadId) takeLeadIntoWork(leadId, takeBtn);
      return;
    }
    const explainClose = event.target.closest('[data-lead-explain-close]');
    if (explainClose) {
      event.preventDefault();
      closeLeadExplain();
      return;
    }
    const explainRoot = document.getElementById('lead-explain');
    if (explainRoot && event.target === explainRoot) closeLeadExplain();
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const explainRoot = document.getElementById('lead-explain');
    if (explainRoot && !explainRoot.hidden) closeLeadExplain();
  });
})();
