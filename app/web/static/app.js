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
    const headers = { ...(options.headers || {}) };
    if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    if (csrfToken && !headers['X-CSRF-Token']) headers['X-CSRF-Token'] = csrfToken;
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers,
      ...options,
    });
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
      '[data-motion-root] > *, .cards > *, .kanban-stack > *, .task-list-page > *, .catalog-grid > *'
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
    }, { threshold: 0.06, rootMargin: '0px 0px -24px' });
    elements.forEach((element) => observer.observe(element));
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
      const output = document.getElementById('agent-query-result');
      setLoading(submit, true);
      try {
        const payload = formPayload(agentForm, submit);
        const data = await api('/api/agent/query', {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        if (output) {
          output.hidden = false;
          output.textContent = formatAgentAnswer(data);
        }
        toast(data.grounded ? 'Ответ grounded' : 'Tool вернул ошибку', !data.grounded);
      } catch (error) {
        toast(error.message, true);
      } finally {
        setLoading(submit, false);
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
      const data = await api(form.action, {
        method: (form.method || 'POST').toUpperCase(),
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

    const scan = event.target.closest('[data-scan]');
    if (scan) {
      const old = scan.textContent;
      scan.disabled = true;
      scan.textContent = 'Проверяю лимиты…';
      try {
        const selectedBudget = document.querySelector('input[name="scan_budget"]:checked');
        let requestedCredits = selectedBudget?.value;
        if (requestedCredits === 'custom') {
          requestedCredits = document.querySelector('[data-custom-scan-budget]')?.value;
        }
        const previewUrl = requestedCredits
          ? `/api/scan/preview?max_credits=${encodeURIComponent(requestedCredits)}`
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
            `Provider: ScrapeCreators. Максимум: ${hardCap} credits. ` +
            `Использовано за месяц: ${monthlyUsed} / ${monthlyHard}. Остаток: ${balance}. ` +
            `Прогноз запаса после запуска: ${months}.`
          );
          if (!proceed) return;
          confirmLive = true;
          requestedCredits = Number(preview.requested_credits);
        }
        scan.textContent = 'Запускаю…';
        const data = await api('/api/scan', {
          method: 'POST',
          body: JSON.stringify({
            confirm_live: confirmLive,
            max_credits: requestedCredits ? Number(requestedCredits) : 0,
          }),
        });
        toast(data.message || 'Проверка запущена');
        if (data.ok) reloadSoon(1800);
      } catch (error) {
        toast(error.message, true);
      } finally {
        scan.disabled = false;
        scan.textContent = old;
      }
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
        reloadSoon();
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
})();
