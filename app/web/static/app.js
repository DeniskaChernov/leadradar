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
    } catch (_) {}
  }

  const toast = (message, bad = false) => {
    const el = document.getElementById('toast');
    if (!el) return;
    el.textContent = message;
    el.className = `toast show ${bad ? 'bad' : ''}`;
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
    const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) };
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
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-text').textContent = text;
    const ok = root.querySelector('[data-confirm-ok]');
    const cancel = root.querySelector('[data-confirm-cancel]');
    const onKeydown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        done(false);
      }
    };
    const done = (value) => {
      root.hidden = true;
      ok.onclick = null;
      cancel.onclick = null;
      document.removeEventListener('keydown', onKeydown);
      if (previouslyFocused instanceof HTMLElement) previouslyFocused.focus();
      resolve(value);
    };
    ok.onclick = () => done(true);
    cancel.onclick = () => done(false);
    document.addEventListener('keydown', onKeydown);
    requestAnimationFrame(() => cancel.focus());
  });

  const enhanceNavigation = () => {
    if (!window.matchMedia('(max-width: 720px)').matches) return;
    const navigation = document.querySelector('.sidebar nav');
    const active = document.querySelector('.sidebar nav .nav.active');
    if (!navigation || !active) return;
    requestAnimationFrame(() => {
      navigation.scrollTo({
        left: active.offsetLeft - (navigation.clientWidth - active.offsetWidth) / 2,
        behavior: 'instant',
      });
    });
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

  const reloadSoon = (delay = 450) => setTimeout(() => location.reload(), delay);

  const formPayload = (form) => {
    const result = {};
    for (const [key, value] of new FormData(form).entries()) result[key] = value;
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
    const form = event.target.closest('[data-api-form]');
    if (!form) return;
    event.preventDefault();
    const submit = form.querySelector('[type="submit"]');
    const oldText = submit?.textContent;
    if (submit) {
      submit.disabled = true;
      submit.textContent = 'Сохраняю…';
    }
    try {
      const data = await api(form.action, {
        method: (form.method || 'POST').toUpperCase(),
        body: JSON.stringify(formPayload(form)),
      });
      toast(data.message || 'Сохранено');
      if (form.dataset.reset === '1') form.reset();
      if (form.dataset.reload === '1') reloadSoon();
    } catch (error) {
      toast(error.message, true);
    } finally {
      if (submit) {
        submit.disabled = false;
        submit.textContent = oldText;
      }
    }
  });

  document.addEventListener('click', async (event) => {
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
        const preview = await api('/api/scan/preview', { method: 'GET' });
        if (!preview.search_enabled) {
          throw new Error('Поиск лидов временно приостановлен. Токены не расходуются.');
        }
        let confirmLive = false;
        if (preview.is_live) {
          if (!preview.live_enabled) {
            throw new Error('Live-запросы выключены. Токены не будут потрачены.');
          }
          const plan = preview.plan || {};
          const hardCap = Number(plan.hard_cap_units || 0);
          const daily = Number(plan.daily_remaining || 0);
          const competitors = Number(plan.active_competitors || 0);
          const candidates = Number(plan.comment_candidates || 0);
          const proceed = await confirmAction(
            'Подтвердить расход live-запросов?',
            `Активных конкурентов: ${competitors}. Reels с изменениями: ${candidates}. ` +
            `Жёсткий предел этой проверки: ${hardCap} операций. Остаток дневного лимита: ${daily}. ` +
            'Система не сможет превысить указанный предел даже при fallback.'
          );
          if (!proceed) return;
          confirmLive = true;
        }
        scan.textContent = 'Запускаю…';
        const data = await api('/api/scan', {
          method: 'POST',
          body: JSON.stringify({ confirm_live: confirmLive }),
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
      action.disabled = true;
      try {
        const payload = action.dataset.payload ? JSON.parse(action.dataset.payload) : {};
        const data = await api(action.dataset.apiAction, {
          method: 'POST',
          body: JSON.stringify(payload),
        });
        toast(data.message || 'Готово');
        if (action.dataset.reload === '1') reloadSoon();
      } catch (error) {
        toast(error.message, true);
        action.disabled = false;
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
      leadAction.disabled = true;
      try {
        const data = await api(`/api/leads/${id}/${type}`, { method: 'POST', body: '{}' });
        toast(data.message || 'Лид обновлён');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        leadAction.disabled = false;
      }
      return;
    }

    const stage = event.target.closest('[data-stage]');
    if (stage) {
      stage.disabled = true;
      try {
        const data = await api(`/api/leads/${stage.dataset.leadId}/stage`, {
          method: 'POST',
          body: JSON.stringify({ status: stage.dataset.stage }),
        });
        toast(data.message || 'Стадия обновлена');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        stage.disabled = false;
      }
      return;
    }

    const task = event.target.closest('[data-task-complete]');
    if (task) {
      task.disabled = true;
      try {
        const data = await api(`/api/tasks/${task.dataset.taskComplete}/complete`, {
          method: 'POST',
          body: '{}',
        });
        toast(data.message || 'Задача выполнена');
        reloadSoon();
      } catch (error) {
        toast(error.message, true);
        task.disabled = false;
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
