'use strict';

(() => {
  const root = document.getElementById('root');
  const POLL_MS = 5000;

  // ---------------------------------------------------------------- Symbole

  const ICONS = {
    grid: '<rect x="3.5" y="3.5" width="7" height="7" rx="2"/><rect x="13.5" y="3.5" width="7" height="7" rx="2"/><rect x="3.5" y="13.5" width="7" height="7" rx="2"/><rect x="13.5" y="13.5" width="7" height="7" rx="2"/>',
    box: '<path d="M12 3 4 7.2v9.6L12 21l8-4.2V7.2L12 3Z"/><path d="m4.3 7.4 7.7 4.1 7.7-4.1M12 11.5V21"/>',
    clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    warning: '<path d="M12 4 3.5 19h17L12 4Z"/><path d="M12 10v4.5M12 17v.01"/>',
    chip: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 4v3M14 4v3M10 17v3M14 17v3M4 10h3M4 14h3M17 10h3M17 14h3"/>',
    restart: '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
    pulse: '<path d="M3 12h4l2.5-6 4.5 12 2.5-6H21"/>',
    heart: '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.6 4.3 4.3 0 0 1 19.5 10c0 5.4-7.5 10-7.5 10Z"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2.5"/>',
    play: '<path d="M8 5.5v13l10.5-6.5L8 5.5Z"/>',
    check: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    x: '<path d="M6 6l12 12M18 6 6 18"/>',
    chevron: '<path d="m9 6 6 6-6 6"/>',
    mail: '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="m4.5 7.5 7.5 6 7.5-6"/>',
    bell: '<path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 5 2 6 2 6h-15s2-1 2-6Z"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/>',
    sun: '<circle cx="12" cy="12" r="3.5"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6 7 7M17 17l1.4 1.4M5.6 18.4 7 17M17 7l1.4-1.4"/>',
    moon: '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10Z"/>',
    logout: '<path d="M10 4.5H6.5a2 2 0 0 0-2 2v11a2 2 0 0 0 2 2H10"/><path d="m15 8 4 4-4 4M19 12H9.5"/>',
    lock: '<rect x="5.5" y="10.5" width="13" height="9" rx="2.5"/><path d="M8.5 10.5V8a3.5 3.5 0 0 1 7 0v2.5"/>',
    person: '<circle cx="12" cy="8.5" r="3.5"/><path d="M5 19.5a7 7 0 0 1 14 0"/>',
    send: '<path d="M20 4 10.5 13.5M20 4l-6 16-3.5-6.5L4 10l16-6Z"/>',
    server: '<rect x="4" y="4.5" width="16" height="6" rx="2"/><rect x="4" y="13.5" width="16" height="6" rx="2"/><path d="M7.5 7.5v.01M7.5 16.5v.01"/>',
  };

  function icon(name, cls) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('class', 'icon' + (cls ? ' ' + cls : ''));
    svg.setAttribute('aria-hidden', 'true');
    svg.innerHTML = ICONS[name] || ''; // nur feste Zeichenketten von oben
    return svg;
  }

  // Baut DOM-Elemente; Text landet immer als Textknoten im Dokument (kein innerHTML mit Daten).
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    let value;
    for (const [key, val] of Object.entries(props || {})) {
      if (val == null || val === false) continue;
      if (key === 'class') el.className = val;
      else if (key === 'value') value = val;
      else if (key === 'checked') el.checked = true;
      else if (key.startsWith('on')) el.addEventListener(key.slice(2), val);
      else el.setAttribute(key, val === true ? '' : val);
    }
    for (const child of children.flat(Infinity)) {
      if (child == null || child === false) continue;
      el.append(child.nodeType ? child : document.createTextNode(String(child)));
    }
    if (value !== undefined) el.value = value;
    return el;
  }

  const glyph = (name, tint) => h('span', { class: 'glyph tint-' + tint }, icon(name));

  // ---------------------------------------------------------------- Zustand

  const state = {
    user: null,
    version: '',
    eventTypes: [],
    labels: {},
    settings: null,
    route: '',
    refresh: null,
    viewId: 0,
    history: { group: 'all', q: '' },
    containers: { q: '' },
  };

  const TYPE_STYLE = {
    crash: ['warning', 'red'],
    oom: ['chip', 'purple'],
    auto_restart: ['restart', 'orange'],
    restart: ['restart', 'blue'],
    unhealthy: ['pulse', 'pink'],
    healthy: ['heart', 'green'],
    stop: ['stop', 'gray'],
    exit: ['check', 'indigo'],
    start: ['play', 'teal'],
  };

  const HISTORY_GROUPS = [
    ['all', 'Alle', ''],
    ['problems', 'Probleme', 'crash,oom,unhealthy'],
    ['restarts', 'Neustarts', 'auto_restart,restart'],
    ['health', 'Healthcheck', 'unhealthy,healthy'],
    ['lifecycle', 'Start & Stopp', 'start,stop,exit'],
  ];

  const MAIL_STATUS = {
    sent: 'E-Mail gesendet',
    pending: 'E-Mail wird gesendet …',
    failed: 'E-Mail-Versand fehlgeschlagen',
    disabled: 'Keine E-Mail – für diesen Ereignistyp deaktiviert',
    muted: 'Keine E-Mail – Container ist stummgeschaltet',
    throttled: 'Keine E-Mail – Sperrzeit nach vorheriger Meldung',
    unconfigured: 'Keine E-Mail – Versand war nicht eingerichtet',
    paused: 'Keine E-Mail – Benachrichtigungen waren pausiert',
    merged: 'Keine eigene E-Mail – bereits als Speicherlimit-Ereignis gemeldet',
  };

  // ---------------------------------------------------------------- Helfer

  class SessionExpired extends Error {}

  async function api(method, path, body) {
    const options = { method, headers: { 'X-Requested-With': 'dmn' }, credentials: 'same-origin' };
    if (body !== undefined) {
      options.headers['Content-Type'] = 'application/json';
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetch(path, options);
    } catch (e) {
      throw new Error('Der Server ist nicht erreichbar.');
    }
    let data = null;
    try { data = await response.json(); } catch (e) { /* leere Antwort */ }
    if (response.status === 401 && state.user) {
      state.user = null;
      showAuth('login');
      throw new SessionExpired('Sitzung abgelaufen.');
    }
    if (!response.ok) throw new Error((data && data.error) || `Fehler ${response.status}`);
    return data;
  }

  const toasts = h('div', { class: 'toasts', 'aria-live': 'polite' });

  function toast(message, kind = 'ok') {
    if (!toasts.isConnected) document.body.append(toasts);
    const el = h('div', { class: 'toast ' + kind }, icon(kind === 'error' ? 'warning' : 'check'), message);
    toasts.append(el);
    setTimeout(() => {
      el.classList.add('out');
      setTimeout(() => el.remove(), 320);
    }, kind === 'error' ? 6000 : 2400);
  }

  function fail(error) {
    if (!(error instanceof SessionExpired)) toast(error.message, 'error');
  }

  async function busy(button, task) {
    if (button.disabled) return;
    button.disabled = true;
    const spinner = h('span', { class: 'spinner' });
    button.prepend(spinner);
    try {
      return await task();
    } finally {
      spinner.remove();
      button.disabled = false;
    }
  }

  const timeFormat = new Intl.DateTimeFormat('de-DE', { hour: '2-digit', minute: '2-digit' });
  const dayFormat = new Intl.DateTimeFormat('de-DE', { weekday: 'long', day: 'numeric', month: 'long' });
  const shortFormat = new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
  const fullFormat = new Intl.DateTimeFormat('de-DE', { dateStyle: 'full', timeStyle: 'medium' });

  function dayLabel(ts) {
    const date = new Date(ts * 1000);
    const today = new Date();
    const yesterday = new Date(Date.now() - 86400000);
    if (date.toDateString() === today.toDateString()) return 'Heute';
    if (date.toDateString() === yesterday.toDateString()) return 'Gestern';
    return dayFormat.format(date);
  }

  function relativeTime(ts) {
    const seconds = Math.max(0, Date.now() / 1000 - ts);
    if (seconds < 60) return 'gerade eben';
    if (seconds < 3600) return `vor ${Math.floor(seconds / 60)} Min.`;
    if (seconds < 86400) return `vor ${Math.floor(seconds / 3600)} Std.`;
    return shortFormat.format(new Date(ts * 1000));
  }

  const typeLabel = (type) => state.labels[type] || type;

  function eventSubtitle(event) {
    let text = typeLabel(event.type);
    if (event.exit_code != null && event.type !== 'exit') text += ` · Exit-Code ${event.exit_code}`;
    return text;
  }

  function mailMark(status) {
    if (status === 'sent') return icon('mail', 'ok');
    if (status === 'failed') return icon('mail', 'bad');
    if (status === 'pending') return icon('mail');
    return null;
  }

  function eventRow(event, when) {
    const [name, tint] = TYPE_STYLE[event.type] || ['bell', 'gray'];
    return h('button', { class: 'row', type: 'button', onclick: () => openEvent(event.id) },
      glyph(name, tint),
      h('div', { class: 'row-body' },
        h('div', { class: 'row-title' }, event.container_name),
        h('div', { class: 'row-sub' }, eventSubtitle(event))),
      h('div', { class: 'row-end' }, mailMark(event.mail_status), when, icon('chevron')));
  }

  function emptyState(iconName, title, text) {
    return h('div', { class: 'group' }, h('div', { class: 'empty' }, icon(iconName), h('strong', null, title), text));
  }

  function toggle(checked, onchange, options = {}) {
    const input = h('input', {
      type: 'checkbox', checked, disabled: options.disabled, 'aria-label': options.label,
      onchange: () => onchange(input.checked, input),
    });
    return h('label', { class: 'switch', title: options.title }, input, h('span'));
  }

  function segmented(options, current, onchange, disabled) {
    const wrap = h('div', { class: 'segmented', role: 'group' });
    const render = (value) => {
      wrap.replaceChildren(...options.map(([key, label]) => h('button', {
        type: 'button', class: key === value ? 'active' : '', disabled, 'aria-pressed': String(key === value),
        onclick: () => { render(key); onchange(key); },
      }, label)));
      wrap.dataset.value = value;
    };
    render(current);
    return wrap;
  }

  // ---------------------------------------------------------------- Dialoge

  function openSheet({ title, lead, small, body }) {
    const close = () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
      backdrop.remove();
    };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    const content = h('div', { class: 'sheet-body' });
    const sheet = h('div', { class: 'sheet' + (small ? ' small' : ''), role: 'dialog', 'aria-modal': 'true', 'aria-label': title },
      h('div', { class: 'grabber' }),
      h('div', { class: 'sheet-head' }, lead, h('h2', null, title),
        h('button', { class: 'icon-btn filled', type: 'button', 'aria-label': 'Schließen', onclick: close }, icon('x'))),
      content);
    const backdrop = h('div', { class: 'backdrop', onmousedown: (e) => { if (e.target === backdrop) close(); } }, sheet);
    content.append(...[body(close)].flat().filter(Boolean));
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    document.body.append(backdrop);
    const first = sheet.querySelector('input');
    if (first) first.focus();
    return close;
  }

  function confirmDialog(title, text, actionLabel, action) {
    openSheet({
      title, small: true,
      body: (close) => {
        const button = h('button', { class: 'btn danger', type: 'button' }, actionLabel);
        button.addEventListener('click', () => busy(button, async () => {
          try { await action(); close(); } catch (e) { fail(e); }
        }));
        return [
          h('p', { class: 'sheet-text' }, text),
          h('div', { class: 'sheet-actions' },
            h('button', { class: 'btn', type: 'button', onclick: close }, 'Abbrechen'), button),
        ];
      },
    });
  }

  async function openEvent(id) {
    let event;
    try { event = await api('GET', `/api/events/${id}`); } catch (e) { return fail(e); }
    const [name, tint] = TYPE_STYLE[event.type] || ['bell', 'gray'];
    const pair = (key, value) => value ? h('div', { class: 'kv' }, h('dt', null, key), h('dd', null, value)) : null;
    let exit = event.exit_code == null ? '' : String(event.exit_code);
    if (exit && event.exit_code_text) exit += ` – ${event.exit_code_text}`;
    let mail = MAIL_STATUS[event.mail_status] || event.mail_status;
    if (event.mail_error) mail += ` (${event.mail_error})`;

    openSheet({
      title: event.container_name,
      lead: glyph(name, tint),
      body: () => {
        const mailValue = h('dd', null, mail);
        const resend = h('button', { class: 'btn', type: 'button' }, icon('send'),
          event.mail_status === 'sent' ? 'E-Mail erneut senden' : 'E-Mail jetzt senden');
        resend.addEventListener('click', () => busy(resend, async () => {
          try {
            await api('POST', `/api/events/${id}/resend`, {});
            mailValue.textContent = MAIL_STATUS.sent;
            toast('E-Mail gesendet');
            if (state.refresh) state.refresh(true);
          } catch (e) { fail(e); }
        }));
        return [
          h('div', { class: 'section' }, h('dl', { class: 'group' },
            pair('Ereignis', typeLabel(event.type)),
            pair('Zeitpunkt', fullFormat.format(new Date(event.ts * 1000))),
            pair('Exit-Code', exit),
            pair('Details', event.detail),
            pair('Image', event.image),
            pair('Compose-Projekt', event.project),
            pair('Container-ID', event.container_id.slice(0, 12)),
            h('div', { class: 'kv' }, h('dt', null, 'E-Mail'), mailValue))),
          event.logs && h('div', { class: 'section' },
            h('h3', { class: 'section-title' }, 'Letzte Log-Zeilen'),
            h('div', { class: 'group' }, h('pre', { class: 'logs' }, event.logs))),
          h('div', { class: 'sheet-actions' }, resend),
        ];
      },
    });
  }

  // ---------------------------------------------------------------- Anmeldung

  function themeButton(cls) {
    // Welches der beiden Symbole sichtbar ist, regelt das Stylesheet über data-theme.
    return h('button', {
      class: 'icon-btn theme-btn ' + (cls || ''), type: 'button', 'aria-label': 'Hell/Dunkel umschalten', title: 'Hell/Dunkel umschalten',
      onclick: () => window.dmnTheme.set(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'),
    }, icon('moon', 'i-moon'), icon('sun', 'i-sun'));
  }

  function showAuth(mode) {
    stopPolling();
    document.querySelectorAll('.backdrop').forEach((el) => el.remove());
    document.body.style.overflow = '';
    const setup = mode === 'setup';
    const error = h('p', { class: 'auth-error', role: 'alert' });
    const username = h('input', { type: 'text', id: 'f-user', name: 'username', autocomplete: 'username', autocapitalize: 'none', spellcheck: 'false', placeholder: setup ? 'z. B. admin' : 'Benutzername', required: true });
    const password = h('input', { type: 'password', id: 'f-pass', name: 'password', autocomplete: setup ? 'new-password' : 'current-password', placeholder: setup ? 'Mindestens 8 Zeichen' : 'Passwort', required: true });
    const repeat = setup && h('input', { type: 'password', id: 'f-repeat', autocomplete: 'new-password', placeholder: 'Passwort wiederholen', required: true });
    const remember = !setup && h('input', { type: 'checkbox' });
    const submit = h('button', { class: 'btn primary large', type: 'submit' }, setup ? 'Konto erstellen' : 'Anmelden');

    const form = h('form', { class: 'auth-form', novalidate: true },
      h('div', { class: 'group' },
        h('div', { class: 'field' }, h('label', { for: 'f-user' }, 'Benutzername'), username),
        h('div', { class: 'field' }, h('label', { for: 'f-pass' }, 'Passwort'), password),
        repeat && h('div', { class: 'field' }, h('label', { for: 'f-repeat' }, 'Wiederholen'), repeat)),
      remember && h('label', { class: 'check' }, remember, 'Angemeldet bleiben'),
      error, submit);

    form.addEventListener('submit', (e) => {
      e.preventDefault();
      error.textContent = '';
      if (!username.value.trim() || !password.value) { error.textContent = 'Bitte Benutzername und Passwort eingeben.'; return; }
      if (setup && password.value !== repeat.value) { error.textContent = 'Die Passwörter stimmen nicht überein.'; return; }
      busy(submit, async () => {
        try {
          await api('POST', setup ? '/api/setup' : '/api/login',
            { username: username.value.trim(), password: password.value, remember: remember ? remember.checked : false });
          await start();
        } catch (err) {
          error.textContent = err.message;
          if (!setup) { password.value = ''; password.focus(); }
        }
      });
    });

    root.replaceChildren(h('div', { class: 'auth' },
      h('div', { class: 'auth-theme' }, themeButton('filled')),
      h('div', { class: 'auth-card' },
        h('img', { class: 'auth-logo', src: '/static/favicon.svg', alt: '' }),
        h('h1', null, setup ? 'Willkommen' : 'Docker Mail Notifier'),
        h('p', { class: 'lead' }, setup ? 'Lege zuerst dein Admin-Konto für Docker Mail Notifier an.' : 'Melde dich an, um fortzufahren.'),
        form)));
    username.focus();
  }

  // ---------------------------------------------------------------- Grundgerüst

  const ROUTES = {
    overview: { title: 'Übersicht', icon: 'grid', view: viewOverview },
    containers: { title: 'Container', icon: 'box', view: viewContainers },
    history: { title: 'Verlauf', icon: 'clock', view: viewHistory },
    settings: { title: 'Einstellungen', icon: 'sliders', view: viewSettings },
  };

  let shell = null;
  let pollTimer = null;

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = null;
    state.refresh = null;
    state.viewId++;
    shell = null;
  }

  function setConnection(docker) {
    if (!shell) return;
    shell.conn.replaceChildren(
      h('span', { class: 'dot ' + (docker.connected ? 'green' : 'red') }),
      docker.connected ? `Docker ${docker.version || 'verbunden'}` : 'Docker nicht erreichbar');
  }

  async function logout() {
    try { await api('POST', '/api/logout', {}); } catch (e) { /* Sitzung ist dann ohnehin weg */ }
    state.user = null;
    showAuth('login');
  }

  function buildShell() {
    const links = (cls) => Object.entries(ROUTES).map(([key, route]) =>
      h('a', { class: cls, href: '#/' + key, 'data-route': key }, icon(route.icon), h('span', null, route.title)));
    shell = {
      conn: h('div', { class: 'conn' }, h('span', { class: 'dot' }), 'Verbinde …'),
      title: h('h1'),
      actions: h('div', { class: 'head-actions' }),
      view: h('div'),
    };
    root.replaceChildren(h('div', { class: 'shell' },
      h('aside', { class: 'sidebar' },
        h('div', { class: 'brand' },
          h('img', { src: '/static/favicon.svg', alt: '' }),
          h('div', null, h('div', { class: 'brand-name' }, 'Mail Notifier'), h('div', { class: 'brand-sub' }, 'für Docker'))),
        h('nav', { class: 'nav', 'aria-label': 'Hauptnavigation' }, links('nav-item')),
        h('div', { class: 'sidebar-foot' },
          shell.conn,
          h('div', { class: 'user-row' },
            h('span', { class: 'user-name' }, state.user),
            themeButton(),
            h('button', { class: 'icon-btn', type: 'button', title: 'Abmelden', 'aria-label': 'Abmelden', onclick: logout }, icon('logout'))))),
      h('main', { class: 'main' }, h('div', { class: 'main-inner' },
        h('header', { class: 'page-head' }, shell.title, shell.actions),
        shell.view)),
      h('nav', { class: 'tabbar', 'aria-label': 'Hauptnavigation' }, links('tab'))));
  }

  async function navigate() {
    if (!state.user) return;
    const key = location.hash.replace(/^#\/?/, '');
    const routeKey = ROUTES[key] ? key : 'overview';
    const route = ROUTES[routeKey];
    if (!shell) buildShell();

    state.route = routeKey;
    state.refresh = null;
    const viewId = ++state.viewId;
    document.title = `${route.title} – Docker Mail Notifier`;
    document.querySelectorAll('[data-route]').forEach((el) => {
      const active = el.dataset.route === routeKey;
      el.classList.toggle('active', active);
      if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
    });
    shell.title.textContent = route.title;
    shell.actions.replaceChildren();
    shell.view.replaceChildren(h('div', { class: 'spinner' }));
    window.scrollTo(0, 0);

    const view = shell.view;
    const alive = () => viewId === state.viewId;
    try {
      const refresh = await route.view(view, shell.actions, alive);
      if (alive()) state.refresh = refresh || null;
    } catch (e) {
      if (alive() && !(e instanceof SessionExpired)) {
        view.replaceChildren(emptyState('warning', 'Laden fehlgeschlagen', e.message));
        state.refresh = () => navigate();
      }
    }
  }

  let tick = 0;
  async function poll() {
    if (document.hidden || !state.user || !shell) return;
    tick++;
    try {
      if (state.refresh) await state.refresh(false);
      if (state.route !== 'overview' && tick % 3 === 0) setConnection((await api('GET', '/api/overview')).docker);
    } catch (e) { /* nächster Durchlauf versucht es erneut */ }
  }

  // ---------------------------------------------------------------- Übersicht

  async function viewOverview(view, actions, alive) {
    let last = '';
    const load = async () => {
      const data = await api('GET', '/api/overview');
      if (!alive()) return;
      setConnection(data.docker);
      const signature = JSON.stringify(data) + Math.floor(Date.now() / 60000);
      if (signature === last) return;
      last = signature;
      const c = data.counts;

      const tile = (href, iconName, tint, value, label) => h('a', { class: 'tile', href },
        h('div', { class: 'tile-top' }, glyph(iconName, tint), h('span', { class: 'tile-value' }, value)),
        h('span', { class: 'tile-label' }, label));

      const banners = [];
      if (!data.docker.connected) {
        banners.push(h('div', { class: 'banner' }, glyph('warning', 'red'), h('div', { class: 'row-body' },
          h('div', { class: 'row-title wrap' }, 'Keine Verbindung zu Docker'),
          h('div', { class: 'row-sub wrap' }, data.docker.error || 'Die Docker-API ist nicht erreichbar. Läuft der Socket-Proxy?'))));
      }
      if (!data.mail.ready) {
        banners.push(h('div', { class: 'banner' }, glyph('mail', 'orange'), h('div', { class: 'row-body' },
          h('div', { class: 'row-title wrap' }, 'E-Mail-Versand einrichten'),
          h('div', { class: 'row-sub wrap' }, 'Trage SMTP-Server und Empfänger ein, damit du benachrichtigt wirst.')),
          h('a', { class: 'btn primary', href: '#/settings' }, 'Einrichten')));
      }

      const master = toggle(data.mail.enabled, async (on, input) => {
        try {
          await api('PUT', '/api/settings', { notifications_enabled: on });
          toast(on ? 'Benachrichtigungen aktiv' : 'Benachrichtigungen pausiert');
          last = '';
          load();
        } catch (e) { input.checked = !on; fail(e); }
      }, { label: 'E-Mail-Benachrichtigungen' });

      view.replaceChildren(
        ...banners,
        h('div', { class: 'tiles' },
          tile('#/containers', 'play', 'green', c.running, c.unhealthy ? `Laufend · ${c.unhealthy} unhealthy` : 'Laufend'),
          tile('#/containers', 'stop', 'gray', c.stopped, 'Gestoppt'),
          tile('#/history', 'warning', 'red', c.problems_24h, 'Probleme (24 Std.)'),
          tile('#/history', 'mail', 'blue', c.mails_24h, 'E-Mails (24 Std.)')),
        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'Status'),
          h('div', { class: 'group' },
            h('div', { class: 'row' }, glyph('server', data.docker.connected ? 'blue' : 'red'),
              h('div', { class: 'row-body' },
                h('div', { class: 'row-title' }, 'Docker'),
                h('div', { class: 'row-sub' }, data.docker.connected
                  ? `Verbunden · Version ${data.docker.version} · ${c.total} Container` : 'Nicht verbunden')),
              h('div', { class: 'row-end' }, h('span', { class: 'dot ' + (data.docker.connected ? 'green' : 'red') }))),
            h('a', { class: 'row', href: '#/settings' }, glyph('mail', data.mail.ready ? 'green' : 'orange'),
              h('div', { class: 'row-body' },
                h('div', { class: 'row-title' }, 'E-Mail-Versand'),
                h('div', { class: 'row-sub' }, data.mail.ready ? `An ${data.mail.recipients.join(', ')}` : 'Noch nicht eingerichtet')),
              h('div', { class: 'row-end' }, icon('chevron'))),
            h('div', { class: 'row' }, glyph('bell', data.mail.enabled ? 'red' : 'gray'),
              h('div', { class: 'row-body' },
                h('div', { class: 'row-title' }, 'Benachrichtigungen'),
                h('div', { class: 'row-sub' }, data.mail.enabled ? 'Aktiv' : 'Pausiert – es werden keine E-Mails gesendet')),
              master))),
        h('section', { class: 'section' },
          h('div', { class: 'section-head' },
            h('h2', { class: 'section-title' }, 'Letzte Ereignisse'),
            data.recent.length ? h('a', { href: '#/history' }, 'Alle anzeigen') : null),
          data.recent.length
            ? h('div', { class: 'group' }, data.recent.map((event) => eventRow(event, relativeTime(event.ts))))
            : emptyState('clock', 'Noch keine Ereignisse', 'Sobald ein Container abstürzt oder neu startet, erscheint er hier.')));
    };
    await load();
    return load;
  }

  // ---------------------------------------------------------------- Container

  function searchBox(placeholder, value, oninput) {
    const input = h('input', { type: 'search', placeholder, value, 'aria-label': placeholder, autocomplete: 'off', spellcheck: 'false' });
    let timer;
    input.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(() => oninput(input.value.trim()), 200);
    });
    return h('div', { class: 'search' }, icon('search'), input);
  }

  async function viewContainers(view, actions, alive) {
    const list = h('div');
    let items = [];
    let last = '';

    const dotColor = (c) => {
      if (c.state === 'running') return c.health === 'unhealthy' ? 'red' : c.health === 'starting' ? 'orange' : 'green';
      if (c.state === 'restarting' || c.state === 'paused') return 'orange';
      return c.state === 'dead' ? 'red' : 'gray';
    };

    const draw = () => {
      const q = state.containers.q.toLowerCase();
      const shown = items.filter((c) => !q || c.name.toLowerCase().includes(q) || c.image.toLowerCase().includes(q));
      if (!shown.length) {
        list.replaceChildren(emptyState('box', items.length ? 'Keine Treffer' : 'Keine Container',
          items.length ? 'Kein Container passt zur Suche.' : 'Auf diesem Host wurden keine Container gefunden.'));
        return;
      }
      list.replaceChildren(h('div', { class: 'group' }, shown.map((c) => h('div', { class: 'row' },
        h('span', { class: 'dot ' + dotColor(c), title: c.state }),
        h('div', { class: 'row-body' },
          h('div', { class: 'row-title' }, c.name, c.project ? [' ', h('span', { class: 'tag' }, c.project)] : null),
          h('div', { class: 'row-sub' }, `${c.status} · ${c.image}`)),
        toggle(!c.muted && !c.label_muted, async (on, input) => {
          try {
            await api('POST', '/api/containers/mute', { name: c.name, muted: !on });
            c.muted = !on;
            last = '';
            toast(on ? `${c.name}: E-Mails aktiv` : `${c.name}: stummgeschaltet`);
          } catch (e) { input.checked = !on; fail(e); }
        }, {
          disabled: c.label_muted,
          label: `E-Mails für ${c.name}`,
          title: c.label_muted ? 'Per Label mail-notifier.ignore stummgeschaltet' : 'E-Mails für diesen Container',
        })))));
    };

    const load = async () => {
      const data = await api('GET', '/api/containers');
      if (!alive()) return;
      const signature = JSON.stringify(data);
      if (signature === last) return;
      last = signature;
      items = data.containers;
      draw();
    };

    view.replaceChildren(
      h('div', { class: 'toolbar' }, searchBox('Container suchen', state.containers.q, (q) => { state.containers.q = q; draw(); })),
      list,
      h('p', { class: 'section-note' }, 'Der Schalter legt fest, ob für einen Container E-Mails verschickt werden. Stummgeschaltete Container erscheinen weiterhin im Verlauf. Dauerhaft geht das auch mit dem Label ',
        h('code', null, 'mail-notifier.ignore=true'), '.'));
    await load();
    return load;
  }

  // ---------------------------------------------------------------- Verlauf

  async function viewHistory(view, actions, alive) {
    const list = h('div');
    const more = h('div', { class: 'more' });
    const chips = h('div', { class: 'chips', role: 'group', 'aria-label': 'Filter' });
    let events = [];
    let hasMore = false;
    let last = '';

    const query = (extra) => {
      const params = new URLSearchParams(extra);
      const types = HISTORY_GROUPS.find((g) => g[0] === state.history.group)[2];
      if (types) params.set('types', types);
      if (state.history.q) params.set('q', state.history.q);
      return '/api/events?' + params;
    };

    const draw = () => {
      if (!events.length) {
        const filtered = state.history.group !== 'all' || state.history.q;
        list.replaceChildren(emptyState('clock', filtered ? 'Keine Treffer' : 'Noch keine Ereignisse',
          filtered ? 'Für diesen Filter gibt es keine Ereignisse.' : 'Sobald ein Container abstürzt oder neu startet, erscheint er hier.'));
        more.replaceChildren();
        return;
      }
      const nodes = [];
      let day = '';
      let group = null;
      for (const event of events) {
        const label = dayLabel(event.ts);
        if (label !== day) {
          day = label;
          group = h('div', { class: 'group' });
          nodes.push(h('h2', { class: 'day' }, label), group);
        }
        group.append(eventRow(event, timeFormat.format(new Date(event.ts * 1000))));
      }
      list.replaceChildren(...nodes);
      const button = h('button', { class: 'btn', type: 'button' }, 'Ältere laden');
      button.addEventListener('click', () => busy(button, async () => {
        try {
          const data = await api('GET', query({ limit: 50, before: events[events.length - 1].id }));
          if (!alive()) return;
          events = events.concat(data.events);
          hasMore = data.has_more;
          last = '';
          draw();
        } catch (e) { fail(e); }
      }));
      more.replaceChildren(hasMore ? button : '');
    };

    const load = async (force) => {
      const data = await api('GET', query({ limit: Math.max(50, events.length) }));
      if (!alive()) return;
      const signature = JSON.stringify(data) + new Date().toDateString();
      if (!force && signature === last) return;
      last = signature;
      events = data.events;
      hasMore = data.has_more;
      draw();
    };

    const reload = () => { events = []; load(true).catch(fail); };

    const drawChips = () => chips.replaceChildren(...HISTORY_GROUPS.map(([key, label]) => h('button', {
      type: 'button', class: 'chip' + (key === state.history.group ? ' active' : ''), 'aria-pressed': String(key === state.history.group),
      onclick: () => { state.history.group = key; drawChips(); reload(); },
    }, label)));
    drawChips();

    actions.replaceChildren(h('button', {
      class: 'btn danger', type: 'button',
      onclick: () => confirmDialog('Verlauf leeren?', 'Alle gespeicherten Ereignisse werden unwiderruflich gelöscht.', 'Verlauf leeren', async () => {
        await api('DELETE', '/api/events');
        toast('Verlauf geleert');
        reload();
      }),
    }, 'Leeren'));

    view.replaceChildren(
      h('div', { class: 'toolbar' },
        searchBox('Container oder Image suchen', state.history.q, (q) => { state.history.q = q; reload(); }), chips),
      list, more);
    await load(true);
    return load;
  }

  // ---------------------------------------------------------------- Einstellungen

  const SMTP_PORTS = { starttls: 587, ssl: 465, none: 25 };

  async function viewSettings(view, actions, alive) {
    let s = await api('GET', '/api/settings');
    if (!alive()) return null;

    const save = async (patch, message) => {
      s = await api('PUT', '/api/settings', patch);
      if (message !== false) toast(message || 'Gesichert');
      return s;
    };
    const autosave = (patch, revert) => save(patch).catch((e) => { if (revert) revert(); fail(e); });

    const draw = () => {
      const locked = (key) => s.locked.includes(key);
      const lockMark = (key) => locked(key) && h('span', { class: 'lock', title: 'Per Umgebungsvariable festgelegt' }, icon('lock'));

      const textField = (key, label, attrs = {}) => {
        const input = h('input', { type: 'text', id: 'f-' + key, value: s[key] == null ? '' : String(s[key]), disabled: locked(key), autocomplete: 'off', autocapitalize: 'none', spellcheck: 'false', ...attrs });
        return { input, row: h('div', { class: 'field' }, h('label', { for: 'f-' + key }, label), input, lockMark(key)) };
      };
      const selectField = (key, label, options) => {
        const current = Number(s[key]);
        if (!options.some(([value]) => value === current)) options = [...options, [current, String(current)]];
        const select = h('select', { id: 'f-' + key, value: String(current) },
          options.map(([value, text]) => h('option', { value: String(value) }, text)));
        select.addEventListener('change', () => autosave({ [key]: Number(select.value) }, () => { select.value = String(s[key]); }));
        return h('div', { class: 'field' }, h('label', { for: 'f-' + key }, label), select);
      };

      // --- Empfänger
      const recipients = textField('recipients', 'Empfänger', { type: 'text', inputmode: 'email', value: s.recipients.join(', '), placeholder: 'name@example.com' });
      recipients.input.addEventListener('change', () => autosave({ recipients: recipients.input.value }));
      const hostLabel = textField('host_label', 'Host-Name', { placeholder: 'z. B. NAS oder Homeserver', maxlength: 60 });
      hostLabel.input.addEventListener('change', () => autosave({ host_label: hostLabel.input.value }));

      // --- SMTP
      const host = textField('smtp_host', 'Server', { placeholder: 'smtp.example.com', inputmode: 'url' });
      const port = textField('smtp_port', 'Port', { inputmode: 'numeric', placeholder: '587' });
      const user = textField('smtp_user', 'Benutzername', { placeholder: 'optional', autocomplete: 'off' });
      const from = textField('smtp_from', 'Absenderadresse', { inputmode: 'email', placeholder: s.smtp_user.includes('@') ? s.smtp_user : 'notifier@example.com' });
      const fromName = textField('smtp_from_name', 'Absendername', { maxlength: 80 });
      const password = h('input', {
        type: 'password', id: 'f-smtp_password', autocomplete: 'new-password', disabled: locked('smtp_password'),
        placeholder: s.smtp_password_set ? '•••••••• (gespeichert)' : 'optional',
      });
      const security = segmented([['starttls', 'STARTTLS'], ['ssl', 'SSL/TLS'], ['none', 'Keine']], s.smtp_security, (mode) => {
        if (!locked('smtp_port') && Object.values(SMTP_PORTS).includes(Number(port.input.value))) port.input.value = SMTP_PORTS[mode];
      }, locked('smtp_security'));
      const verify = toggle(s.smtp_verify_tls, () => {}, { label: 'TLS-Zertifikat prüfen' });
      const verifyInput = verify.querySelector('input');

      const smtpPatch = () => {
        const patch = {
          smtp_host: host.input.value, smtp_port: port.input.value || 587, smtp_security: security.dataset.value,
          smtp_verify_tls: verifyInput.checked, smtp_user: user.input.value,
          smtp_from: from.input.value, smtp_from_name: fromName.input.value,
        };
        if (password.value) patch.smtp_password = password.value;
        return patch;
      };
      const saveButton = h('button', { class: 'btn primary', type: 'submit' }, 'Sichern');
      const testButton = h('button', { class: 'btn', type: 'button' }, icon('send'), 'Testmail senden');
      const smtpForm = h('form', { class: 'group', novalidate: true, autocomplete: 'off' },
        host.row, port.row,
        h('div', { class: 'field wrap-sm' }, h('span', { class: 'label' }, 'Verschlüsselung'), security, lockMark('smtp_security')),
        h('div', { class: 'field stack' }, h('label', null, 'TLS-Zertifikat prüfen'), verify),
        user.row,
        h('div', { class: 'field' }, h('label', { for: 'f-smtp_password' }, 'Passwort'), password, lockMark('smtp_password')),
        from.row, fromName.row,
        h('div', { class: 'btn-row' }, saveButton, testButton));
      smtpForm.addEventListener('submit', (e) => {
        e.preventDefault();
        busy(saveButton, async () => {
          try { await save(smtpPatch()); draw(); } catch (err) { fail(err); }
        });
      });
      testButton.addEventListener('click', () => busy(testButton, async () => {
        try {
          await save(smtpPatch(), false);
          const result = await api('POST', '/api/test-mail', {});
          toast(`Testmail an ${result.recipients.join(', ')} gesendet`);
          draw();
        } catch (err) { fail(err); }
      }));

      const smtpNotes = [];
      if (s.smtp_password_unreadable) {
        smtpNotes.push(h('p', { class: 'section-note' }, h('strong', null, 'Das gespeicherte Passwort kann nicht mehr entschlüsselt werden. '),
          'Wurde SECRET_KEY geändert? Bitte das Passwort neu eingeben.'));
      }
      if (s.smtp_security === 'none' && s.smtp_user) {
        smtpNotes.push(h('p', { class: 'section-note' }, h('strong', null, 'Achtung: '), 'Ohne Verschlüsselung werden Benutzername und Passwort im Klartext übertragen.'));
      }
      smtpNotes.push(h('p', { class: 'section-note' },
        'Das Passwort wird verschlüsselt gespeichert und nie wieder angezeigt. ',
        s.secret_source === 'env'
          ? 'Der Schlüssel dafür stammt aus deiner Umgebungsvariable SECRET_KEY.'
          : ['Für mehr Schutz die Umgebungsvariable ', h('code', null, 'SECRET_KEY'), ' setzen – dann liegt der Schlüssel getrennt von der Datenbank.'],
        s.locked.length ? ' Felder mit Schloss sind per Umgebungsvariable festgelegt.' : ''));

      // --- Ereignisse
      const eventRows = state.eventTypes.map((type) => {
        const [name, tint] = TYPE_STYLE[type.key] || ['bell', 'gray'];
        return h('div', { class: 'row' }, glyph(name, tint),
          h('div', { class: 'row-body' },
            h('div', { class: 'row-title wrap' }, type.label),
            h('div', { class: 'row-sub wrap' }, type.hint)),
          toggle(s.notify[type.key], (on, input) => autosave({ notify: { [type.key]: on } }, () => { input.checked = !on; }), { label: type.label }));
      });

      // --- Konto
      const theme = segmented([['auto', 'Automatisch'], ['light', 'Hell'], ['dark', 'Dunkel']], window.dmnTheme.get(), (mode) => window.dmnTheme.set(mode));

      view.replaceChildren(
        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'Benachrichtigungen'),
          h('div', { class: 'group' },
            h('div', { class: 'field stack' }, h('label', null, 'E-Mail-Benachrichtigungen'),
              toggle(s.notifications_enabled, (on, input) => autosave({ notifications_enabled: on }, () => { input.checked = !on; }), { label: 'E-Mail-Benachrichtigungen' })),
            recipients.row, hostLabel.row),
          h('p', { class: 'section-note' }, 'Mehrere Empfänger mit Komma trennen. Der Host-Name steht im Betreff, damit du siehst, von welchem Server die Meldung kommt.')),

        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'SMTP-Server'), smtpForm, smtpNotes),

        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'E-Mail senden bei'),
          h('div', { class: 'group' }, eventRows),
          h('p', { class: 'section-note' }, 'Im Verlauf werden immer alle Ereignisse festgehalten – unabhängig von dieser Auswahl.')),

        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'Verhalten'),
          h('div', { class: 'group' },
            selectField('cooldown_minutes', 'Sperrzeit', [[0, 'Aus'], [1, '1 Minute'], [5, '5 Minuten'], [15, '15 Minuten'], [30, '30 Minuten'], [60, '1 Stunde']]),
            selectField('log_lines', 'Log-Zeilen in der E-Mail', [[0, 'Keine'], [10, '10 Zeilen'], [30, '30 Zeilen'], [50, '50 Zeilen'], [100, '100 Zeilen']]),
            selectField('retention_days', 'Verlauf aufbewahren', [[30, '30 Tage'], [90, '90 Tage'], [180, '180 Tage'], [365, '1 Jahr'], [0, 'Unbegrenzt']])),
          h('p', { class: 'section-note' }, 'Sperrzeit: Stürzt ein Container in einer Schleife ab, kommt je Container und Ereignisart höchstens eine E-Mail im gewählten Zeitraum. Log-Zeilen können vertrauliche Daten enthalten.')),

        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'Darstellung'),
          h('div', { class: 'group' }, h('div', { class: 'field wrap-sm' }, h('span', { class: 'label' }, 'Erscheinungsbild'), theme))),

        h('section', { class: 'section' },
          h('h2', { class: 'section-title' }, 'Konto'),
          h('div', { class: 'group' },
            h('div', { class: 'row' }, glyph('person', 'gray'),
              h('div', { class: 'row-body' }, h('div', { class: 'row-title' }, state.user), h('div', { class: 'row-sub' }, 'Angemeldet'))),
            h('button', { class: 'row', type: 'button', onclick: openPasswordDialog }, glyph('lock', 'blue'),
              h('div', { class: 'row-body' }, h('div', { class: 'row-title' }, 'Passwort ändern')), h('div', { class: 'row-end' }, icon('chevron'))),
            h('button', { class: 'row', type: 'button', onclick: logout }, glyph('logout', 'red'),
              h('div', { class: 'row-body' }, h('div', { class: 'row-title' }, 'Abmelden')))),
          h('p', { class: 'section-note' }, `Docker Mail Notifier ${state.version}`)));
    };

    draw();
    return null;
  }

  function openPasswordDialog() {
    openSheet({
      title: 'Passwort ändern', small: true,
      body: (close) => {
        const field = (id, label, autocomplete) => {
          const input = h('input', { type: 'password', id, autocomplete, required: true });
          return { input, row: h('div', { class: 'field' }, h('label', { for: id }, label), input) };
        };
        const current = field('p-current', 'Aktuell', 'current-password');
        const next = field('p-new', 'Neu', 'new-password');
        const repeat = field('p-repeat', 'Wiederholen', 'new-password');
        const error = h('p', { class: 'auth-error', role: 'alert' });
        const submit = h('button', { class: 'btn primary', type: 'submit' }, 'Passwort ändern');
        const form = h('form', { novalidate: true },
          h('div', { class: 'section' }, h('div', { class: 'group' }, current.row, next.row, repeat.row)),
          error,
          h('div', { class: 'sheet-actions' }, h('button', { class: 'btn', type: 'button', onclick: close }, 'Abbrechen'), submit));
        form.addEventListener('submit', (e) => {
          e.preventDefault();
          error.textContent = '';
          if (next.input.value !== repeat.input.value) { error.textContent = 'Die neuen Passwörter stimmen nicht überein.'; return; }
          busy(submit, async () => {
            try {
              await api('POST', '/api/password', { current: current.input.value, new: next.input.value });
              close();
              toast('Passwort geändert');
            } catch (err) { error.textContent = err.message; }
          });
        });
        return form;
      },
    });
  }

  // ---------------------------------------------------------------- Start

  async function start() {
    let info;
    try {
      info = await api('GET', '/api/state');
    } catch (e) {
      root.replaceChildren(h('div', { class: 'auth' }, emptyState('warning', 'Keine Verbindung', e.message)));
      setTimeout(start, 4000);
      return;
    }
    if (info.setup_required) return showAuth('setup');
    if (!info.authenticated) return showAuth('login');
    state.user = info.username;
    state.version = info.version;
    state.eventTypes = info.event_types;
    state.labels = Object.fromEntries(info.event_types.map((t) => [t.key, t.label]));
    await navigate();
    if (!pollTimer) pollTimer = setInterval(poll, POLL_MS);
  }

  window.addEventListener('hashchange', navigate);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  start();
})();
