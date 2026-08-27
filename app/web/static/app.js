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

  const api = async (url, options = {}) => {
    const response = await fetch(url, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    const data = await readResponse(response);
    if (!response.ok) throw new Error(data.detail || data.message || 'Не удалось выполнить действие');
    return data;
  };

  const confirmAction = (title, text) => new Promise((resolve) => {
    const root = document.getElementById('confirm');
    if (!root) return resolve(window.confirm(text));
    root.hidden = false;
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-text').textContent = text;
    const ok = root.querySelector('[data-confirm-ok]');
    const cancel = root.querySelector('[data-confirm-cancel]');
    const done = (value) => {
      root.hidden = true;
      ok.onclick = null;
      cancel.onclick = null;
      resolve(value);
    };
    ok.onclick = () => done(true);
    cancel.onclick = () => done(false);
  });

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

  // Command Palette Handler (Ctrl+K / Cmd+K)
  const commandPalette = document.getElementById('command-palette-backdrop');
  const btnPalette = document.getElementById('btn-command-palette');
  const btnClosePalette = document.getElementById('btn-close-palette');
  const commandInput = document.getElementById('command-input');

  function openPalette() {
    if (commandPalette) {
      commandPalette.classList.add('open');
      if (commandInput) commandInput.focus();
    }
  }

  function closePalette() {
    if (commandPalette) commandPalette.classList.remove('open');
  }

  if (btnPalette) btnPalette.addEventListener('click', openPalette);
  if (btnClosePalette) btnClosePalette.addEventListener('click', closePalette);

  window.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
      e.preventDefault();
      if (commandPalette && commandPalette.classList.contains('open')) {
        closePalette();
      } else {
        openPalette();
      }
    } else if (e.key === 'Escape') {
      closePalette();
      closeGPTDrawer();
    }
  });

  // GPT Drawer Assistant Handler
  const gptDrawer = document.getElementById('gpt-drawer');
  const btnGPT = document.getElementById('btn-gpt-drawer');
  const btnCloseGPT = document.getElementById('btn-close-gpt');
  const btnSendGPT = document.getElementById('btn-send-gpt');
  const gptInput = document.getElementById('gpt-input');
  const gptMessages = document.getElementById('gpt-drawer-messages');

  function openGPTDrawer() {
    if (gptDrawer) gptDrawer.classList.add('open');
  }

  function closeGPTDrawer() {
    if (gptDrawer) gptDrawer.classList.remove('open');
  }

  if (btnGPT) btnGPT.addEventListener('click', openGPTDrawer);
  if (btnCloseGPT) btnCloseGPT.addEventListener('click', closeGPTDrawer);

  async function handleGPTSend(text) {
    const query = text || (gptInput ? gptInput.value.trim() : '');
    if (!query) return;
    if (gptInput) gptInput.value = '';

    const userMsg = document.createElement('div');
    userMsg.style.cssText = 'background:rgba(245,158,11,0.25); border:1px solid rgba(245,158,11,0.40); padding:12px; border-radius:12px; font-size:13px; align-self:flex-end; color:#fff;';
    userMsg.textContent = query;
    if (gptMessages) gptMessages.appendChild(userMsg);

    try {
      const data = await api('/api/agent/query', {
        method: 'POST',
        body: JSON.stringify({ query: query, context: { page: location.pathname } }),
      });

      const assistantMsg = document.createElement('div');
      assistantMsg.style.cssText = 'background:rgba(255,255,255,0.10); border:1px solid rgba(255,255,255,0.18); padding:12px; border-radius:12px; font-size:13px; color:#fff; white-space:pre-wrap;';
      assistantMsg.textContent = data.reply || 'Готово';
      if (gptMessages) gptMessages.appendChild(assistantMsg);
    } catch (err) {
      toast(err.message, true);
    }
  }

  if (btnSendGPT) btnSendGPT.addEventListener('click', () => handleGPTSend());
  if (gptInput) {
    gptInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') handleGPTSend();
    });
  }

  document.querySelectorAll('.gpt-quick-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      openGPTDrawer();
      handleGPTSend(btn.dataset.query);
    });
  });
})();

