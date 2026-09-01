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
  };

  const runAgentQuery = async (form, submitButton) => {
    const targetSelector = form.dataset.agentTarget || '#agent-query-result';
    const output = document.querySelector(targetSelector);
    const plainOutput = output?.matches('pre.agent-result') ? output : null;
    setLoading(submitButton, true);
    try {
      const payload = formPayload(form, submitButton);
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

  const toast = (message, bad = false) => {
    const el = document.getElementById('toast');
    if (!el) return;
    const text = el.querySelector('[data-toast-message]');
    if (text) text.textContent = message;
    else el.textContent = message;
    el.className = `toast show ${bad ? 'bad' : ''}`;
    el.querySelector('i')?.getAnimations().forEach((animation) => animation.cancel());
    clearTimeout(window.__lrToastTimer);
    window.__lrToastTimer = setTimeout(() => (el.className = 'toast'), 3200);
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
    if (!response.ok) throw new Error(data.detail || data.message || 'Не удалось выполнить действие');
    return data;
  };

  const confirmAction = (title, text) => new Promise((resolve) => {
    const root = document.getElementById('confirm');
    if (!root) return resolve(window.confirm(text));
    const previouslyFocused = document.activeElement;
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('is-open'));
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-text').textContent = text;
    const ok = root.querySelector('[data-confirm-ok]');
    const cancel = root.querySelector('[data-confirm-cancel]');
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
      ok.onclick = null;
      cancel.onclick = null;
      document.removeEventListener('keydown', onKeydown);
      setTimeout(() => {
        root.hidden = true;
        if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
        resolve(value);
      }, 180);
    };
    ok.onclick = () => done(true);
    cancel.onclick = () => done(false);
    document.addEventListener('keydown', onKeydown);
    requestAnimationFrame(() => cancel.focus());
  });

  const enhanceNavigation = () => {
    const toggle = document.querySelector('[data-more-toggle]');
    const menu = document.getElementById('more-navigation');
    const close = () => {
      menu?.classList.remove('is-open');
      toggle?.setAttribute('aria-expanded', 'false');
      document.body.classList.remove('more-navigation-open');
    };
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
    const elements = document.querySelectorAll(
      '[data-motion-root] > *, .cards > *, .kanban-stack > *, .kanban-col, .task-list-page > *, .catalog-grid > *, .lead-layout > .panel, .stage-actions > .stage-btn, .funnel-track-step, .quick-actions > *, .metrics > *'
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
    sessionStorage.removeItem('lr:focus');
    sessionStorage.removeItem('lr:scroll-y');
    if (y) requestAnimationFrame(() => window.scrollTo({ top: y, behavior: 'instant' }));
    if (key) requestAnimationFrame(() => document.querySelector(key)?.focus());
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

  enhanceNavigation();
  enhanceTables();
  enhanceClickableRows();
  enhanceMotion();
  restoreViewState();

  const flashStageSuccess = (element) => {
    if (!element) return;
    element.classList.add('stage-success');
  };

  const reloadSoon = (delay = 450, focusSelector = '') => {
    sessionStorage.setItem('lr:scroll-y', String(window.scrollY));
    if (focusSelector) sessionStorage.setItem('lr:focus', focusSelector);
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

  const refreshScanBudgetPreview = async (root = document) => {
    const credits = readScanBudgetSelection(root);
    if (!credits) return;
    try {
      const preview = await api(
        `/api/scan/preview?max_credits=${encodeURIComponent(credits)}`,
        { method: 'GET' },
      );
      const maxEl = root.querySelector('[data-budget-max]');
      const monthlyEl = root.querySelector('[data-budget-monthly]');
      const dailyEl = root.querySelector('[data-budget-daily]');
      if (maxEl) maxEl.textContent = `${preview.effective_max_credits} credits`;
      if (monthlyEl && preview.monthly_remaining != null) {
        monthlyEl.textContent = String(preview.monthly_remaining);
      }
      if (dailyEl && preview.daily_remaining != null) {
        dailyEl.textContent = String(preview.daily_remaining);
      }
    } catch (_error) {
      /* preview недоступен offline */
    }
  };

  const openScanQuickModal = () => new Promise((resolve) => {
    const root = document.getElementById('scan-quick');
    if (!root) return resolve(null);
    const meta = root.querySelector('[data-scan-quick-meta]');
    const cancel = root.querySelector('[data-scan-quick-cancel]');
    const go = root.querySelector('[data-scan-quick-go]');
    const previouslyFocused = document.activeElement;
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add('is-open'));
    api('/api/scan/preview?max_credits=10', { method: 'GET' })
      .then((preview) => {
        if (!meta) return;
        if (!preview.is_live) {
          meta.textContent = 'Offline-режим: credits не расходуются.';
          meta.hidden = false;
          return;
        }
        meta.textContent = `Макс. на scan: ${preview.effective_max_credits} credits · `
          + `месяц: ${preview.used_this_month}/${preview.monthly_hard_limit} · `
          + `сегодня: ${preview.daily_remaining}`;
        meta.hidden = false;
      })
      .catch(() => {
        if (meta) meta.hidden = true;
      });
    const close = (value) => {
      root.classList.remove('is-open');
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
      const previewUrl = credits
        ? `/api/scan/preview?max_credits=${encodeURIComponent(credits)}`
        : '/api/scan/preview';
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
          'Запустить Radar?',
          `ScrapeCreators. Максимум: ${hardCap} credits. `
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
        }),
      });
      toast(data.message || 'Проверка запущена');
      if (data.ok) {
        const onRadar = (document.body.dataset.page || '').startsWith('/radar');
        if (onRadar) {
          startRadarPolling();
        } else {
          setTimeout(() => { window.location.href = '/radar'; }, 1200);
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
        'Подтвердите применение импорта',
        event.submitter.dataset.confirm
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
      if (form.dataset.reload === '1') reloadSoon();
    } catch (error) {
      toast(error.message, true);
    } finally {
      setLoading(submit, false);
    }
  });

  document.addEventListener('click', async (event) => {
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

    const agentPreset = event.target.closest('[data-agent-preset]');
    if (agentPreset) {
      event.preventDefault();
      let payload = {};
      try {
        payload = JSON.parse(agentPreset.dataset.agentPreset || '{}');
      } catch (_) {
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
        form.requestSubmit();
        return;
      }
      Object.entries(payload).forEach(([key, value]) => {
        const field = form.querySelector(`[name="${key}"]`);
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
        const proceed = await confirmAction('Подтвердите действие', action.dataset.confirm);
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
        if (action.dataset.reload === '1') reloadSoon();
        else setLoading(action, false);
      } catch (error) {
        toast(error.message, true);
        setLoading(action, false);
      }
      return;
    }

    const leadAction = event.target.closest('[data-lead-action]');
    if (leadAction) {
      const id = leadAction.dataset.leadId;
      const type = leadAction.dataset.leadAction;
      if (type === 'not-lead') {
        const proceed = await confirmAction(
          'Точно не лид?',
          'Это сохранится как обратная связь для будущего скоринга. Сам клиент и его история из базы не удалятся.'
        );
        if (!proceed) return;
      }
      setLoading(leadAction, true);
      try {
        const data = await api(`/api/leads/${id}/${type}`, { method: 'POST', body: '{}' });
        toast(data.message || 'Лид обновлён');
        flashStageSuccess(leadAction);
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        setLoading(leadAction, false);
      }
      return;
    }

    const stage = event.target.closest('[data-stage]');
    if (stage) {
      setLoading(stage, true);
      try {
        const data = await api(`/api/leads/${stage.dataset.leadId}/stage`, {
          method: 'POST',
          body: JSON.stringify({ status: stage.dataset.stage }),
        });
        toast(data.message || 'Стадия обновлена');
        flashStageSuccess(stage);
        reloadSoon(650);
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
        + '<b>Пока спокойно</b><span>Изменения и HOT появятся после проверки и разбора сигналов.</span></div>'
      );
    }
    list.innerHTML = parts.join('');
    if (window.lucide?.createIcons) window.lucide.createIcons();
    const badge = document.querySelector('[data-radar-queue-badge]');
    if (badge) {
      const queueTotal = Number(feed.ai_pending || 0) + Number(feed.analyzing || 0);
      badge.textContent = queueTotal > 0 ? `AI: ${queueTotal}` : 'AI готов';
      badge.classList.toggle('warning', queueTotal > 0);
      badge.classList.toggle('success', queueTotal === 0);
    }
  };

  const updateRadarLiveBanner = (payload) => {
    const banner = document.querySelector('[data-radar-live]');
    if (!banner) return;
    const busy = Boolean(payload.cycle_running)
      || Number(payload.analysis_queue || 0) > 0
      || Number(payload.analysis_in_flight || 0) > 0;
    banner.hidden = !busy;
    const title = banner.querySelector('[data-radar-live-title]');
    const detail = banner.querySelector('[data-radar-live-detail]');
    if (!title || !detail) return;
    if (payload.cycle_running) {
      title.textContent = 'Идёт проверка Instagram';
      detail.textContent = 'Сбор комментариев и Reels…';
    } else if (Number(payload.analysis_in_flight || 0) > 0) {
      title.textContent = 'OpenAI разбирает сигналы';
      detail.textContent = `В работе: ${payload.analysis_in_flight}, в очереди: ${payload.analysis_queue || 0}`;
    } else if (Number(payload.analysis_queue || 0) > 0) {
      title.textContent = 'Очередь OpenAI';
      detail.textContent = `Ждут разбора: ${payload.analysis_queue}`;
    }
  };

  let radarPollTimer = null;
  let radarPollBusy = false;

  const pollRadarFeed = async () => {
    if (radarPollBusy) return;
    radarPollBusy = true;
    try {
      const feed = await api('/api/radar/feed?limit=8', { method: 'GET' });
      notifyNewRadarChanges(feed);
      renderRadarFeed(feed);
      updateRadarLiveBanner(feed);
      const stillBusy = feed.cycle_running
        || Number(feed.analysis_queue || 0) > 0
        || Number(feed.analysis_in_flight || 0) > 0;
      if (!stillBusy && radarPollTimer) {
        clearInterval(radarPollTimer);
        radarPollTimer = null;
        reloadSoon(800);
      }
    } catch (_error) {
      /* тихий poll */
    } finally {
      radarPollBusy = false;
    }
  };

  const startRadarPolling = () => {
    if (!(document.body.dataset.page || '').startsWith('/radar')) return;
    pollRadarFeed();
    if (radarPollTimer) clearInterval(radarPollTimer);
    radarPollTimer = setInterval(pollRadarFeed, 3500);
  };

  if ((document.body.dataset.page || '').startsWith('/radar')) {
    startRadarPolling();
    const budgetRoot = document.querySelector('.radar-budget-card');
    if (budgetRoot) refreshScanBudgetPreview(budgetRoot);
  }

  document.addEventListener('change', (event) => {
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
  });

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
        const payload = { query: query.value.trim() };
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
})();
