(() => {
  'use strict';

  const TRACKS = { free: window.QUESTIONS.free, full: window.QUESTIONS.full };
  const FOLLOW_UPS = window.FOLLOW_UPS;
  const app = document.getElementById('app');

  // ---------- Состояние и синхронизация с сервером ----------
  // Книга хранится на сервере и привязана к httpOnly-cookie. В браузере — только копия в памяти.
  // Статус оплаты знает только сервер.

  const emptyData = () => ({
    profile: { name: '', gender: 'm' },
    answers: {},
    book: { title: '', dedication: '', style: 'answers', aiSig: {} },
    last: null,
    events: [],
  });

  let state = emptyData();
  let server = { paid: false, exists: false, ai: {}, photos: {}, features: { ai: false, payments: false, price: '1490.00' } };
  let PRICE = '1 490 ₽';

  async function api(method, url, body) {
    const opts = { method, credentials: 'same-origin', headers: {} };
    if (method !== 'GET') opts.headers['X-Requested-With'] = 'mystory';
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(url, opts);
    let data = null;
    try { data = await res.json(); } catch (e) { /* пустой ответ */ }
    if (!res.ok) {
      const err = new Error((data && data.error) || `http_${res.status}`);
      err.status = res.status;
      throw err;
    }
    return data;
  }

  async function loadState() {
    const s = await api('GET', '/api/state');
    server = { paid: s.paid, exists: s.exists, ai: s.ai || {}, photos: s.photos || {}, features: s.features };
    PRICE = `${Number(s.features.price).toLocaleString('ru-RU')} ₽`;
    const d = s.data || {};
    const base = emptyData();
    state = { ...base, ...d, profile: { ...base.profile, ...d.profile }, book: { ...base.book, ...d.book, aiSig: { ...(d.book && d.book.aiSig) } } };
  }

  // Сохраняем пачкой через полсекунды после последнего изменения.
  let saveTimer = null;
  let saving = Promise.resolve();
  let dirty = false;

  function save() {
    dirty = true;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flush, 600);
  }

  function flush() {
    clearTimeout(saveTimer);
    if (!dirty) return saving;
    dirty = false;
    const body = { data: state };
    saving = saving
      .then(() => api('PUT', '/api/state', body))
      .then(() => { server.exists = true; flashSaved(); })
      .catch((e) => {
        dirty = true;
        if (e.status === 413) toast('Слишком много текста для одной книги — сократи пару ответов.');
        else toast('Не удалось сохранить — проверь интернет. Попробуем ещё раз.');
        saveTimer = setTimeout(flush, 5000);
      });
    return saving;
  }

  // При закрытии вкладки отправляем несохранённое (keepalive переживает закрытие страницы).
  window.addEventListener('pagehide', () => {
    if (!dirty) return;
    const body = JSON.stringify({ data: state });
    if (body.length < 60000) {
      fetch('/api/state', { method: 'PUT', keepalive: true, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'mystory' }, body });
    }
  });

  // Событие пишем в книгу и отправляем целью в Метрику (если счётчик подключён).
  function track(name) {
    state.events.push({ name, at: Date.now() });
    if (state.events.length > 200) state.events.shift();
    if (window.analytics) window.analytics.goal(name);
  }

  // ---------- Утилиты ----------

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Шаблоны вида {был|была} выбирают форму по полу автора.
  const gendered = (str, gender) => String(str).replace(/\{([^|}]*)\|([^}]*)\}/g, (_, m, f) => (gender === 'f' ? f : m));
  const g = (str, s = state) => gendered(str, s.profile.gender);

  const steps = (t) => TRACKS[t].flatMap((c, ci) => c.questions.map((q, qi) => ({ q, c, ci, qi })));
  const STEPS = { free: steps('free'), full: steps('full') };
  const total = (t) => STEPS[t].length;
  const stepIndex = (t, ci, qi) => STEPS[t].findIndex((x) => x.ci === ci && x.qi === qi);

  function isAnswered(q, s = state) {
    const a = s.answers[q.id];
    return Boolean(a && (a.text || '').trim()) || (q.type === 'intro' && Boolean(s.profile.name.trim()));
  }

  const answered = (t, s = state) => STEPS[t].filter(({ q }) => isAnswered(q, s)).length;
  const chapterCount = (c) => c.questions.filter((q) => isAnswered(q)).length;

  function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
    return many;
  }
  const answersWord = (n) => plural(n, 'ответ', 'ответа', 'ответов');

  function toast(text) {
    document.querySelectorAll('.toast').forEach((t) => t.remove());
    const el = document.createElement('div');
    el.className = 'toast';
    el.setAttribute('role', 'status');
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3600);
  }

  let savedTimer;
  function flashSaved() {
    const el = document.querySelector('[data-saved]');
    if (!el) return;
    el.classList.add('is-on');
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => el.classList.remove('is-on'), 1400);
  }

  // Короткая подпись ответов главы — чтобы понять, устарел ли литературный текст.
  function signature(str) {
    let h = 5381;
    for (let i = 0; i < str.length; i++) h = ((h << 5) + h + str.charCodeAt(i)) | 0;
    return (h >>> 0).toString(36);
  }

  const icon = {
    arrow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    back: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>',
    mic: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    book: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M3 5.5c3-1 6-1 9 1 3-2 6-2 9-1V19c-3-1-6-1-9 1-3-2-6-2-9-1z"/><path d="M12 6.5V20"/></svg>',
    photo: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-8 8"/></svg>',
    download: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    check: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10"/></svg>',
    spark: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.9 6.1L20 10l-6.1 1.9L12 18l-1.9-6.1L4 10l6.1-1.9z"/></svg>',
    pen: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>',
    lock: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>',
    link: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
  };

  const logo = () => `<a class="logo" href="#/"><span class="logo__mark">${icon.book}</span><span>Книга моей жизни</span></a>`;

  // Мягкое цветное пятно — визуальный «характер» главы вместо фотографий.
  const aura = (hue, extra = '') => `<div class="aura ${extra}" style="--h:${hue}" aria-hidden="true"></div>`;

  // ---------- Где продолжить ----------

  function firstOpen(t) {
    const hit = STEPS[t].find(({ q }) => !isAnswered(q));
    return hit ? [hit.ci, hit.qi] : [0, 0];
  }

  function validStep(t, ci, qi) {
    return Boolean(TRACKS[t] && TRACKS[t][ci] && TRACKS[t][ci].questions[qi]);
  }

  // Возвращаемся туда, где человек был в прошлый раз; иначе — к первому пустому вопросу.
  function resumeStep(t) {
    const l = state.last;
    if (l && l.track === t && validStep(t, l.ci, l.qi)) return [l.ci, l.qi];
    return firstOpen(t);
  }

  function currentTrack() {
    if (!server.paid) return 'free';
    if (state.last && state.last.track === 'full') return 'full';
    return freeDone() ? 'full' : 'free';
  }

  const freeDone = () => answered('free') === total('free');

  // ---------- Лендинг ----------

  function renderLanding() {
    const started = answered('free') + answered('full') > 0;
    const t = currentTrack();
    const [ci, qi] = resumeStep(t);
    const done = answered(t), all = total(t);
    const pct = Math.round((done / all) * 100);

    app.innerHTML = `
    <header class="nav" id="nav">
      ${logo()}
      <nav class="nav__links" id="nav-links">
        <a href="#how">Как это работает</a>
        <a href="#chapters">Главы</a>
        <a href="#pricing">Цены</a>
        <a href="#faq">Вопросы</a>
        <a href="#/example">Пример</a>
      </nav>
      <a class="btn btn--dark btn--sm" href="#/interview">${started ? 'Продолжить' : 'Начать бесплатно'}</a>
      <button type="button" class="nav__burger" id="burger" aria-label="Меню" aria-expanded="false" aria-controls="nav-links"><span></span></button>
    </header>

    <main>
    <section class="hero">
      ${aura(24, 'aura--hero-a')}${aura(265, 'aura--hero-b')}${aura(165, 'aura--hero-c')}
      <div class="hero__copy">
        <p class="pill">${icon.spark} 12 вопросов — бесплатно</p>
        <h1>Интервью <em>с самим собой</em></h1>
        <p class="hero__sub">Твоя автобиография за один час</p>
        <p class="hero__text">Ответь на несколько вопросов — голосом или текстом — и мы соберём полноценную автобиографию всей твоей жизни.</p>
        ${started ? `
        <a class="resume" href="#/interview">
          <div class="resume__top"><span>${t === 'full' ? 'Полная книга' : 'Бесплатная версия'} · вопрос ${stepIndex(t, ci, qi) + 1} из ${all}</span><strong>${pct}%</strong></div>
          <div class="bar"><span style="width:${pct}%"></span></div>
          <div class="resume__bottom"><span>${esc(g(TRACKS[t][ci].title))}</span><span class="resume__go">Продолжить ${icon.arrow}</span></div>
        </a>
        ${freeDone() ? `<a class="hero__book-link" href="#/book">${icon.book} Открыть мою книгу</a>` : ''}` : `
        <div class="hero__actions">
          <a class="btn btn--dark btn--lg" href="#/interview">Начать бесплатно ${icon.arrow}</a>
          <a class="btn btn--ghost btn--lg" href="#/example">Пример книги</a>
        </div>`}
        <p class="hero__fine">Без регистрации · можно пропустить любой вопрос · прогресс сохраняется</p>
      </div>

      <div class="hero__demo" aria-hidden="true">
        <div class="demo-card demo-card--q">
          <p class="demo-card__meta">Вопрос 4 из 12 · Детство</p>
          <p class="demo-card__title">Какое самое раннее воспоминание о себе ты помнишь?</p>
          <div class="demo-card__answer">Дом бабушки в деревне. Скрипучее крыльцо, запах яблок в сенях…<span class="caret"></span></div>
          <div class="demo-card__row"><span class="demo-mic">${icon.mic}</span><span class="wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span></div>
        </div>
        <div class="demo-card demo-card--follow">
          <span class="demo-card__avatar">${icon.spark}</span>
          <p>Сколько тебе было лет и кто был рядом?</p>
        </div>
        <div class="demo-book"><span>Автобиография</span><strong>Сергей Волков</strong><em>Мост через Оку</em></div>
      </div>
    </section>

    <section class="stats" aria-label="Коротко">
      <div><strong>12</strong><span>вопросов бесплатно</span></div>
      <div><strong>94</strong><span>вопроса в полной книге</span></div>
      <div><strong>10</strong><span>глав жизни</span></div>
      <div><strong>${PRICE}</strong><span>единоразово, без подписки</span></div>
    </section>

    <section class="section" id="how">
      <p class="eyebrow">Как это работает</p>
      <h2>Начни с короткой истории. Продолжи, когда захочешь.</h2>
      <ol class="path">
        <li><span>1</span><h3>Ответь на 12 вопросов</h3><p>Знакомство, детство, люди, повороты и настоящее. Голосом или текстом.</p></li>
        <li><span>2</span><h3>Прочитай свою историю</h3><p>ИИ бережно соберёт ответы в связный текст — твоими словами.</p></li>
        <li><span>3</span><h3>Продолжи полную книгу</h3><p>10 глав и 94 вопроса в своём темпе. Ответы сохраняются.</p></li>
        <li><span>4</span><h3>Отредактируй и скачай</h3><p>Выбери истории, добавь фото и посвящение — и получи PDF.</p></li>
      </ol>
      <div class="principles">
        <div>${icon.check}<span>Отвечай в своём темпе</span></div>
        <div>${icon.check}<span>Любой вопрос можно пропустить</span></div>
        <div>${icon.check}<span>ИИ ничего не выдумывает — только твои факты</span></div>
        <div>${icon.check}<span>Ты решаешь, какие истории войдут в книгу</span></div>
      </div>
    </section>

    <section class="section" id="chapters">
      <p class="eyebrow">Полная книга</p>
      <h2>10 глав — вся жизнь</h2>
      <div class="chapter-grid">
        ${TRACKS.full.map((c, i) => `
          <div class="chapter-card">
            ${aura(c.hue, 'aura--card')}
            <span class="chapter-card__num">${String(i + 1).padStart(2, '0')} · ${c.questions.length} ${plural(c.questions.length, 'вопрос', 'вопроса', 'вопросов')}</span>
            <h3>${esc(g(c.title))}</h3>
            <span class="chapter-card__q">${esc(g(c.questions[0].title))}</span>
          </div>`).join('')}
      </div>
    </section>

    <section class="section" id="pricing">
      <p class="eyebrow">Цены</p>
      <h2>Попробуй бесплатно. Плати один раз.</h2>
      <div class="plans">
        <article class="plan">
          <h3 class="plan__name">Моя история</h3>
          <p class="plan__price"><strong>0 ₽</strong></p>
          <ul class="checks">
            <li>${icon.check} 12 вопросов в 5 разделах</li>
            <li>${icon.check} Короткая автобиография с названием и главами</li>
            <li>${icon.check} Литературная обработка текста ИИ</li>
            <li>${icon.check} Чтение, базовое редактирование и PDF</li>
          </ul>
          <a class="btn btn--ghost btn--lg btn--block" href="#/free">${answered('free') ? 'Продолжить' : 'Начать бесплатно'}</a>
        </article>
        <article class="plan plan--main">
          ${aura(24, 'aura--plan')}
          <h3 class="plan__name">Полная книга моей жизни <span class="tag">единоразово</span></h3>
          <p class="plan__price"><strong>${PRICE}</strong><span>без подписки</span></p>
          <ul class="checks">
            <li>${icon.check} 10 глав и 94 вопроса</li>
            <li>${icon.check} Уточняющие вопросы для важных историй</li>
            <li>${icon.check} Редактирование текста и выбор историй</li>
            <li>${icon.check} Фотографии с подписями</li>
            <li>${icon.check} Название книги и посвящение</li>
            <li>${icon.check} Красиво оформленный PDF для печати</li>
          </ul>
          <a class="btn btn--dark btn--lg btn--block" href="${server.paid ? '#/full' : '#/offer'}">${server.paid ? 'Открыть полную книгу' : 'Хочу полную книгу'} ${icon.arrow}</a>
        </article>
      </div>
      <p class="pricing__gift">Отличный подарок родителям и близким — их история тоже важна.</p>
    </section>

    <section class="section" id="faq">
      <p class="eyebrow">Частые вопросы</p>
      <h2>Что важно знать</h2>
      <div class="faq">
        ${FAQ.map(([q, a]) => `<details><summary>${esc(q)}</summary><p>${esc(a)}</p></details>`).join('')}
      </div>
    </section>
    </main>

    <footer class="footer">${logo()}<nav class="footer__links"><a href="/privacy.html">Конфиденциальность</a><a href="/terms.html">Оферта</a></nav></footer>`;

    const nav = document.getElementById('nav');
    const burger = document.getElementById('burger');
    const setMenu = (open) => { nav.classList.toggle('nav--open', open); burger.setAttribute('aria-expanded', String(open)); };
    burger.addEventListener('click', () => setMenu(!nav.classList.contains('nav--open')));
    nav.querySelectorAll('.nav__links a').forEach((a) => a.addEventListener('click', () => setMenu(false)));
  }

  // Тексты FAQ дублируются в разметке JSON-LD в index.html — меняй в обоих местах.
  const FAQ = [
    ['Сколько времени займёт?', 'Бесплатная часть — 12 вопросов, обычно 15–30 минут. Полная книга — 94 вопроса, её удобно проходить за несколько вечеров: прогресс сохраняется.'],
    ['ИИ не перепишет мою жизнь?', 'Нет. ИИ только связывает твои ответы в текст и правит повторы. Он не добавляет фактов, имён и событий, которых ты не называл. Любой абзац можно отредактировать вручную.'],
    ['Можно ли пропустить вопрос?', 'Да, любой. Пустые вопросы просто не попадут в книгу. Вернуться к ним можно в любой момент.'],
    ['Как оплачивается полная книга?', 'Один раз, без подписки. После оплаты открываются все 10 глав, фото, посвящение и полная PDF-книга. Ответы бесплатной части тоже войдут в неё.'],
    ['Где хранятся мои ответы?', 'На нашем сервере, привязанные к твоему браузеру. Для продолжения на другом устройстве есть личная ссылка. Мы не публикуем и не продаём твои истории.'],
    ['Можно ли подарить книгу?', 'Да — пройди интервью вместе с родителями или близкими: отвечать можно голосом, а PDF легко распечатать.'],
  ];

  // ---------- Предложение полной версии ----------

  function renderOffer() {
    app.innerHTML = `
    <div class="offer">
      ${aura(24, 'aura--offer-a')}${aura(265, 'aura--offer-b')}
      <header class="offer__bar">${logo()}<a class="btn btn--ghost btn--sm" href="${freeDone() ? '#/book' : '#/free'}">${icon.back}<span class="hide-sm">Моя история</span></a></header>
      <main class="offer__card">
        <p class="eyebrow">Полная книга моей жизни</p>
        <h1>Это только начало твоей истории</h1>
        <p class="offer__text">Мы собрали первые воспоминания, но впереди ещё много глав: люди, которые тебя изменили, решения, о которых ты не жалеешь, ошибки, которым ты ${g('{научился|научилась}')}, и моменты, которые хочется сохранить.</p>
        <p class="offer__text">Ответь на дополнительные вопросы и создай полную книгу своей жизни.</p>
        <div class="offer__grid">
          <ul class="checks">
            <li>${icon.check} 10 глав и 94 вопроса</li>
            <li>${icon.check} Уточняющие вопросы для важных историй</li>
            <li>${icon.check} Редактирование перед финальной сборкой</li>
            <li>${icon.check} Фотографии с подписями</li>
            <li>${icon.check} Название книги и посвящение</li>
            <li>${icon.check} PDF для сохранения и печати</li>
          </ul>
          <div class="offer__buy">
            <p class="plan__price"><strong>${PRICE}</strong><span>единоразово</span></p>
            <p class="offer__note">Без подписки. Твои ответы бесплатной части уже войдут в книгу.</p>
            <button type="button" class="btn btn--dark btn--lg btn--block" id="buy" ${server.paid ? 'disabled' : ''}>${server.paid ? 'Уже оплачено' : `Оплатить ${PRICE}`} ${icon.arrow}</button>
            <p class="offer__legal">Нажимая «Оплатить», ты принимаешь <a href="/terms.html" target="_blank" rel="noopener">условия оферты</a>.</p>
          </div>
        </div>
      </main>
    </div>`;

    document.getElementById('buy').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      track('buy_click');
      btn.disabled = true;
      btn.textContent = 'Переходим к оплате…';
      try {
        await flush();
        if (!server.exists) await api('PUT', '/api/state', { data: state }).then(() => { server.exists = true; });
        const res = await api('POST', '/api/pay');
        if (res.paid) { server.paid = true; go('#/full'); return; }
        location.href = res.url;
      } catch (err) {
        btn.disabled = false;
        btn.innerHTML = `Оплатить ${PRICE} ${icon.arrow}`;
        toast(err.message === 'payments_disabled' ? 'Оплата временно недоступна — попробуй чуть позже.' : 'Не получилось создать платёж. Попробуй ещё раз.');
      }
    });
  }

  // Возврат с оплаты: спрашиваем сервер, подтвердил ли UrlPay платёж.
  function renderPaid() {
    app.innerHTML = `
    <div class="offer">
      ${aura(160, 'aura--offer-a')}
      <header class="offer__bar">${logo()}</header>
      <main class="offer__card offer__card--center">
        <div class="spinner" aria-hidden="true"></div>
        <h1 id="paid-title">Проверяем оплату…</h1>
        <p class="offer__text" id="paid-text">Обычно это занимает несколько секунд.</p>
        <div id="paid-actions"></div>
      </main>
    </div>`;
    let tries = 0;
    const check = async () => {
      if (location.hash !== '#/paid') return;
      tries++;
      try {
        const res = await api('POST', '/api/pay/check');
        if (res.paid) {
          server.paid = true;
          track('paid');
          flush();
          document.querySelector('.spinner').remove();
          document.getElementById('paid-title').textContent = 'Оплата прошла — спасибо!';
          document.getElementById('paid-text').textContent = 'Полная книга открыта. Твои 12 ответов уже в ней.';
          document.getElementById('paid-actions').innerHTML = `<a class="btn btn--dark btn--lg" href="#/full">Продолжить книгу ${icon.arrow}</a>`;
          return;
        }
      } catch (e) { /* повторим */ }
      if (tries < 40) setTimeout(check, 3000);
      else {
        document.querySelector('.spinner').remove();
        document.getElementById('paid-title').textContent = 'Пока не видим оплату';
        document.getElementById('paid-text').textContent = 'Если деньги списались, подожди пару минут и обнови страницу — платёж подтвердится автоматически.';
        document.getElementById('paid-actions').innerHTML = `<a class="btn btn--ghost btn--lg" href="#/offer">Вернуться</a>`;
      }
    };
    check();
  }

  // ---------- Интервью ----------

  let recognition = null;

  function stopRecognition() {
    if (recognition) {
      recognition.onend = null;
      recognition.stop();
      recognition = null;
    }
  }

  function nextStep(t, ci, qi) {
    const ch = TRACKS[t];
    if (qi + 1 < ch[ci].questions.length) return [ci, qi + 1];
    if (ci + 1 < ch.length) return [ci + 1, 0];
    return null;
  }

  function prevStep(t, ci, qi) {
    if (qi > 0) return [ci, qi - 1];
    return [ci - 1, TRACKS[t][ci - 1].questions.length - 1];
  }

  function nextHref(t, ci, qi) {
    const n = nextStep(t, ci, qi);
    return n ? `#/${t}/${n.join('/')}` : '#/book';
  }

  function renderInterview(t, ci, qi) {
    stopRecognition();
    const chapters = TRACKS[t];
    const chapter = chapters[ci];
    const q = chapter.questions[qi];

    state.last = { track: t, ci, qi };
    save();

    const done = answered(t), all = total(t);
    const pct = Math.round((done / all) * 100);
    const n = stepIndex(t, ci, qi) + 1;
    const answer = state.answers[q.id] || { text: '' };
    const photo = server.photos[chapter.id];
    const isLast = n === all;
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

    app.innerHTML = `
    <div class="studio">
      <header class="studio__bar">
        ${logo()}
        <div class="studio__progress">
          <span>${t === 'full' ? 'Полная книга' : 'Моя история'} · ${done} из ${all} ${answersWord(done)}</span>
          <div class="bar"><span style="width:${pct}%"></span></div>
        </div>
        <span class="saved" data-saved>${icon.check} Сохранено</span>
        <a class="btn btn--ghost btn--sm" href="#/book">${icon.book}<span class="hide-sm">Книга</span></a>
      </header>

      <div class="studio__body">
        <aside class="side">
          <nav class="chapters" aria-label="Главы">
            ${chapters.map((c, i) => {
              const k = chapterCount(c), cnt = c.questions.length;
              return `<a href="#/${t}/${i}/0" class="chapters__item ${i === ci ? 'is-active' : ''} ${k === cnt ? 'is-done' : ''}">
                <span class="chapters__dot" style="--h:${c.hue}">${k === cnt ? icon.check : i + 1}</span>
                <span class="chapters__name">${esc(g(c.title))}</span>
                <span class="chapters__count">${k}/${cnt}</span>
              </a>`;
            }).join('')}
          </nav>
          ${t === 'free' ? `
            <a class="side__upsell" href="${server.paid ? '#/full' : '#/offer'}">
              <strong>Полная книга</strong><span>10 глав · 94 вопроса${server.paid ? '' : ` · ${PRICE}`}</span>
            </a>` : `
            <a class="side__upsell side__upsell--plain" href="#/free/0/0"><strong>Моя история</strong><span>12 первых вопросов · ${answered('free')}/12</span></a>`}
        </aside>

        <main class="stage">
          ${aura(chapter.hue, 'aura--stage')}
          <div class="card">
            <div class="card__top">
              <p class="eyebrow">${t === 'full' ? `Глава ${ci + 1} · ` : ''}${esc(g(chapter.title))}</p>
              <p class="card__n">Вопрос ${n} из ${all}</p>
            </div>
            <div class="dots">${chapter.questions.map((qq, i) => `<a href="#/${t}/${ci}/${i}" class="${i === qi ? 'is-on' : ''} ${isAnswered(qq) ? 'is-done' : ''}" aria-label="Вопрос ${i + 1}"></a>`).join('')}</div>

            <h1 class="q-title">${esc(g(q.title))}</h1>

            ${q.type === 'intro' ? introFields() : ''}
            <div class="answer">
              <label class="visually-hidden" for="answer">Ответ</label>
              <textarea id="answer" rows="6" placeholder="${q.type === 'intro' ? 'Как ты обычно представляешься? Например: «Я Серёжа, инженер и папа двоих детей»' : 'Начни писать или нажми на микрофон…'}">${esc(answer.text)}</textarea>
              <div class="answer__tools">
                ${SpeechRec ? `<button type="button" class="mic" id="mic">${icon.mic}<span>Ответить голосом</span></button>` : '<span class="hint">Голосовой ввод работает в Chrome и Safari</span>'}
                ${t === 'full' ? `<label class="photo-add" title="Фото к главе">${icon.photo}<span>${photo ? 'Заменить фото' : 'Фото к главе'}</span><input type="file" id="photo" accept="image/*" hidden></label>` : ''}
              </div>
            </div>
            <div class="follow" id="follow" hidden aria-live="polite"></div>

            ${t === 'full' && photo ? `
              <figure class="photo-preview"><img src="${photo.src}" alt="">
                <figcaption><input id="caption" value="${esc(photo.caption)}" placeholder="Подпись к фото" aria-label="Подпись к фото"><button type="button" class="link" id="photo-remove">Убрать</button></figcaption>
              </figure>` : ''}

            <div class="card__nav">
              ${n > 1 ? `<a class="btn btn--ghost" href="#/${t}/${prevStep(t, ci, qi).join('/')}">${icon.back}<span class="hide-sm">Назад</span></a>` : '<span></span>'}
              <div class="card__nav-right">
                <a class="link" href="${nextHref(t, ci, qi)}">Пропустить</a>
                <a class="btn btn--dark" id="next" href="${nextHref(t, ci, qi)}">${isLast ? (t === 'free' ? 'Собрать мою историю' : 'Собрать книгу') : 'Далее'} ${icon.arrow}</a>
              </div>
            </div>
          </div>
          <p class="stage__hint">Прогресс сохраняется автоматически — можно закрыть вкладку и вернуться позже. <kbd>⌘</kbd>+<kbd>Enter</kbd> — следующий вопрос.</p>
        </main>
      </div>
    </div>`;

    bindInterview(t, chapter, q, SpeechRec);
  }

  function introFields() {
    const p = state.profile;
    return `<div class="form">
      <label>Имя для обложки книги<input id="p-name" value="${esc(p.name)}" placeholder="Имя и фамилия" autocomplete="name"></label>
      <fieldset class="seg"><legend>Как обращаться к тебе в вопросах и книге?</legend>
        <button type="button" data-gender="m" class="${p.gender !== 'f' ? 'is-on' : ''}" aria-pressed="${p.gender !== 'f'}">Он</button>
        <button type="button" data-gender="f" class="${p.gender === 'f' ? 'is-on' : ''}" aria-pressed="${p.gender === 'f'}">Она</button>
      </fieldset>
    </div>`;
  }

  // Запасные уточнения по правилам — если ИИ недоступен.
  function ruleFollowUps(text, asked) {
    const len = text.trim().length;
    if (len < 15 || len > 900) return [];
    return FOLLOW_UPS.filter((f) =>
      !asked.includes(f.text)
      && (!f.minLen || len >= f.minLen)
      && (!f.maxLen || len <= f.maxLen)
      && (!f.missing || !f.missing.test(text))).slice(0, 2).map((f) => g(f.text));
  }

  // Уточнения от ИИ кешируем по тексту ответа, чтобы не спрашивать повторно.
  const followCache = new Map();

  async function aiFollowUps(qid, text) {
    const key = `${qid}:${text.trim()}`;
    if (followCache.has(key)) return followCache.get(key);
    await flush();
    const res = await api('POST', '/api/ai/followup', { questionId: qid, text });
    followCache.set(key, res.questions);
    return res.questions;
  }

  function bindInterview(t, chapter, q, SpeechRec) {
    const answer = () => (state.answers[q.id] ||= { text: '' });

    // Знакомство
    const nameInput = document.getElementById('p-name');
    if (nameInput) {
      nameInput.addEventListener('input', () => { state.profile.name = nameInput.value; save(); });
      if (!nameInput.value) nameInput.focus({ preventScroll: true });
    }
    app.querySelectorAll('[data-gender]').forEach((b) => b.addEventListener('click', () => {
      state.profile.gender = b.dataset.gender;
      save();
      route();
    }));

    // Текст + уточняющие вопросы: сначала ИИ, при ошибке — правила.
    const ta = document.getElementById('answer');
    const follow = document.getElementById('follow');
    let lastAskedLen = 0;
    const showFollow = (list, fromAi) => {
      const asked = answer().asked || [];
      const items = list.filter((x) => !asked.includes(x)).slice(0, 2);
      follow.hidden = !items.length;
      follow.innerHTML = items.length ? `
        <span class="follow__avatar">${icon.spark}</span>
        <div class="follow__body">
          <p class="follow__label">${fromAi ? 'Уточнение от ИИ' : 'Уточнение'} — можно пропустить</p>
          ${items.map((text) => `<button type="button" class="follow__q" data-follow="${esc(text)}">${esc(text)}<span>${icon.pen}</span></button>`).join('')}
        </div>` : '';
    };
    const renderFollow = async () => {
      const text = ta.value;
      const len = text.trim().length;
      if (len < 20 || len > 3500) { showFollow([], false); return; }
      const rules = ruleFollowUps(text, answer().asked || []);
      if (!server.features.ai || Math.abs(len - lastAskedLen) < 25) {
        if (!server.features.ai) showFollow(rules, false);
        return;
      }
      lastAskedLen = len;
      try {
        const list = await aiFollowUps(q.id, text);
        if (ta.value === text) showFollow(list, true);
      } catch (e) {
        showFollow(rules, false);
      }
    };
    let followTimer;
    follow.addEventListener('click', (e) => {
      const b = e.target.closest('[data-follow]');
      if (!b) return;
      // Ответ на уточнение дописывается в тот же текст — отдельным абзацем.
      const a = answer();
      a.asked = [...(a.asked || []), b.dataset.follow];
      ta.value = ta.value.replace(/\s*$/, '') + '\n\n';
      a.text = ta.value;
      save();
      b.remove();
      if (!follow.querySelector('[data-follow]')) follow.hidden = true;
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
      ta.scrollTop = ta.scrollHeight;
    });
    ta.addEventListener('input', () => {
      answer().text = ta.value;
      save();
      clearTimeout(followTimer);
      followTimer = setTimeout(renderFollow, 1800);
    });
    if (ta.value.trim().length >= 20) renderFollow();
    if (q.type !== 'intro' || state.profile.name) {
      ta.focus({ preventScroll: true });
      ta.setSelectionRange(ta.value.length, ta.value.length);
    }

    // ⌘/Ctrl + Enter — следующий вопрос
    app.querySelector('.card').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        document.getElementById('next').click();
      }
    });

    document.getElementById('next').addEventListener('click', () => {
      if (!nextStep(t, state.last.ci, state.last.qi)) { track(`${t}_finished`); save(); }
    });

    // Голос
    const mic = document.getElementById('mic');
    if (mic && SpeechRec) {
      const label = mic.querySelector('span');
      const setRec = (on) => { mic.classList.toggle('is-rec', on); label.textContent = on ? 'Остановить запись' : 'Ответить голосом'; };
      mic.addEventListener('click', () => {
        if (recognition) { stopRecognition(); setRec(false); return; }
        recognition = new SpeechRec();
        recognition.lang = 'ru-RU';
        recognition.continuous = true;
        recognition.interimResults = true;
        const base = ta.value ? ta.value.replace(/[ \t]*$/, ta.value.endsWith('\n') ? '' : ' ') : '';
        let finalText = '';
        recognition.onresult = (e) => {
          let interim = '';
          for (let i = e.resultIndex; i < e.results.length; i++) {
            const r = e.results[i];
            if (r.isFinal) finalText += r[0].transcript.trim() + ' ';
            else interim += r[0].transcript;
          }
          ta.value = base + finalText + interim;
          answer().text = ta.value.trim();
          save();
          clearTimeout(followTimer);
          followTimer = setTimeout(renderFollow, 2500);
        };
        recognition.onerror = (e) => {
          if (e.error === 'not-allowed') toast('Разреши доступ к микрофону в настройках браузера.');
        };
        recognition.onend = () => { recognition = null; setRec(false); };
        recognition.start();
        setRec(true);
      });
    }

    // Фото главы (полная книга) — хранится на сервере.
    const file = document.getElementById('photo');
    if (file) file.addEventListener('change', async () => {
      const f = file.files[0];
      if (!f) return;
      try {
        const prev = server.photos[chapter.id];
        const src = await compressImage(f, 1400, 0.8);
        const caption = prev ? prev.caption : '';
        await flush();
        await api('PUT', `/api/photo/${chapter.id}`, { src, caption });
        server.photos[chapter.id] = { src, caption };
        route();
      } catch (e) {
        toast(e.status === 413 ? 'Фото слишком большое.' : 'Не получилось загрузить фото.');
      }
    });
    const cap = document.getElementById('caption');
    let capTimer;
    if (cap) cap.addEventListener('input', () => {
      server.photos[chapter.id].caption = cap.value;
      clearTimeout(capTimer);
      capTimer = setTimeout(() => api('PUT', `/api/photo/${chapter.id}`, { src: null, caption: cap.value }).then(flashSaved).catch(() => toast('Не удалось сохранить подпись.')), 700);
    });
    const rm = document.getElementById('photo-remove');
    if (rm) rm.addEventListener('click', async () => {
      try {
        await api('DELETE', `/api/photo/${chapter.id}`);
        delete server.photos[chapter.id];
        route();
      } catch (e) { toast('Не удалось убрать фото.'); }
    });
  }

  function compressImage(file, maxSide, quality) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const k = Math.min(1, maxSide / Math.max(img.width, img.height));
        const c = document.createElement('canvas');
        c.width = Math.round(img.width * k);
        c.height = Math.round(img.height * k);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(img.src);
        resolve(c.toDataURL('image/jpeg', quality));
      };
      img.onerror = reject;
      img.src = URL.createObjectURL(file);
    });
  }

  // ---------- Книга ----------

  // Состав книги: бесплатная — 5 разделов из 12 вопросов;
  // полная — «Знакомство» + 10 глав, куда вливаются и ответы бесплатной части.
  function bookChapters(s, full, photos = {}) {
    const freeQs = TRACKS.free.flatMap((c) => c.questions);
    const items = (qs) => qs.filter((q) => isAnswered(q, s) && (s.answers[q.id] || {}).text).map((q) => ({ q, a: s.answers[q.id] }));
    if (!full) return TRACKS.free.map((c) => ({ c, key: `free:${c.id}`, items: items(c.questions) }));
    const intro = { id: 'intro', title: 'Знакомство', hue: 24 };
    return [intro, ...TRACKS.full].map((c) => ({
      c,
      key: `full:${c.id}`,
      items: items([...freeQs.filter((q) => q.into === c.id), ...(c.questions || [])]),
      photo: photos[c.id],
    }));
  }

  const chapterSig = (x, s) => signature(s.profile.gender + x.items.filter((it) => !it.a.excluded).map((it) => it.a.text).join('\u0001'));

  const paragraphs = (text) => String(text || '').split(/\n+/).map((p) => p.trim()).filter(Boolean);
  const defaultTitle = (full) => (full ? 'Книга моей жизни' : 'Моя история');

  function bookMarkup(s, full, opts = {}) {
    const aiTexts = opts.ai || {};
    const literary = s.book.style === 'ai';
    const title = s.book.title.trim() || defaultTitle(full);
    const author = s.profile.name.trim();
    const dedication = full ? s.book.dedication.trim() : '';
    const chapters = bookChapters(s, full, opts.photos)
      .map((x) => ({ ...x, all: x.items, items: x.items.filter((it) => !it.a.excluded) }))
      .filter((x) => x.items.length || x.photo);

    const body = (x) => {
      const ai = literary && aiTexts[x.key];
      if (ai && ai.text) {
        const stale = !ai.edited && (s.book.aiSig || {})[x.key] && s.book.aiSig[x.key] !== chapterSig(x, s);
        return `${stale && opts.screen ? '<p class="bk-stale">Ответы в этой главе изменились — текст можно обновить в редакторе.</p>' : ''}${paragraphs(ai.text).map((p) => `<p>${esc(p)}</p>`).join('')}`;
      }
      return x.items.map((it) => `<h3 class="bk-sub">${esc(g(it.q.title, s))}</h3>${paragraphs(it.a.text).map((p) => `<p>${esc(p)}</p>`).join('')}`).join('');
    };

    return {
      chapters,
      html: `
      <section class="bk-cover">
        <div class="bk-cover__frame">
          <p class="bk-cover__kicker">Автобиография</p>
          <h1>${esc(title)}</h1>
          <span class="bk-cover__rule"></span>
          <p class="bk-cover__years">${esc(author)}</p>
          <p class="bk-cover__brand">Книга моей жизни</p>
        </div>
      </section>
      ${dedication ? `<section class="bk-dedication"><p>${paragraphs(dedication).map(esc).join('<br>')}</p></section>` : ''}
      ${chapters.length > 1 ? `
      <section class="bk-toc">
        <h2>Содержание</h2>
        <ol>${chapters.map((x, i) => `<li><span>${full ? `Глава ${i + 1}` : String(i + 1).padStart(2, '0')}</span>${esc(g(x.c.title, s))}</li>`).join('')}</ol>
      </section>` : ''}
      ${chapters.map((x, i) => `
      <section class="bk-chapter" id="ch-${x.c.id}">
        <p class="bk-chapter__num">${full ? `Глава ${i + 1}` : `Часть ${i + 1}`}</p>
        <h2>${esc(g(x.c.title, s))}</h2>
        ${x.photo ? `<figure class="bk-photo"><img src="${x.photo.src}" alt="">${x.photo.caption ? `<figcaption>${esc(x.photo.caption)}</figcaption>` : ''}</figure>` : ''}
        ${body(x)}
      </section>`).join('')}
      ${chapters.length ? '' : `<section class="bk-empty"><p>Здесь появятся главы твоей книги.</p><a class="btn btn--dark" href="#/interview">Ответить на вопросы ${icon.arrow}</a></section>`}`,
    };
  }

  let editing = false;
  let generating = false;

  function renderBook(isExample) {
    stopRecognition();
    const s = isExample ? window.EXAMPLE_STATE : state;
    const full = !isExample && server.paid;
    const opts = isExample ? { ai: window.EXAMPLE_AI, photos: {} } : { ai: server.ai, photos: full ? server.photos : {}, screen: true };
    const { chapters, html } = bookMarkup(s, full, opts);
    const t = full ? 'full' : 'free';
    const done = answered(t, s), all = total(t);
    if (isExample) editing = false;
    const literary = s.book.style === 'ai';

    app.innerHTML = `
    <div class="reader">
      <header class="reader__bar">
        <a class="btn btn--ghost btn--sm" href="${isExample ? '#/' : '#/interview'}">${icon.back}<span class="hide-sm">${isExample ? 'На главную' : 'К вопросам'}</span></a>
        <span class="reader__label">${isExample ? 'Пример: бесплатная версия' : `${full ? 'Полная книга' : 'Моя история'} · ${done} из ${all}`}</span>
        <div class="reader__actions">
          ${isExample ? `<a class="btn btn--dark btn--sm" href="#/free">Создать свою ${icon.arrow}</a>` : `
            <button class="btn btn--ghost btn--sm" id="edit">${editing ? `${icon.check}<span>Готово</span>` : `${icon.pen}<span class="hide-sm">Редактировать</span>`}</button>
            <button class="btn btn--dark btn--sm" id="pdf" ${chapters.length && !editing ? '' : 'disabled'}>${icon.download}<span>PDF</span></button>`}
        </div>
      </header>
      <div class="reader__body">
        <aside class="reader__toc">
          ${chapters.map((x) => `<a href="#ch-${x.c.id}" data-jump="ch-${x.c.id}"><span class="reader__thumb" style="--h:${x.c.hue}">${x.photo ? `<img src="${x.photo.src}" alt="">` : ''}</span>${esc(g(x.c.title, s))}</a>`).join('')}
        </aside>
        <div class="reader__main">
          ${!isExample && !editing && done < all ? `
            <div class="notice">${t === 'free' ? `Ответов: ${done} из ${all}. Пустые вопросы просто не попадут в историю.` : `Ответов: ${done} из ${all}. Продолжай в своём темпе — книга пересобирается сама.`}
              <a href="#/${t}">Продолжить ${icon.arrow}</a></div>` : ''}
          ${!isExample && !editing && chapters.length ? `
            <div class="style-switch" role="group" aria-label="Вид текста">
              <button type="button" data-style="answers" class="${literary ? '' : 'is-on'}" aria-pressed="${!literary}">Мои ответы</button>
              <button type="button" data-style="ai" class="${literary ? 'is-on' : ''}" aria-pressed="${literary}">${icon.spark} Литературный текст</button>
              <span class="style-switch__hint" id="gen-status">${literary ? literaryHint(chapters) : 'ИИ соберёт ответы в связный текст твоими словами'}</span>
            </div>` : ''}
          ${editing ? editorMarkup(full) : `<article class="paper" id="book">${html}</article>`}
          ${!isExample && !editing && chapters.length ? recoveryMarkup() : ''}
          ${!isExample && !full && !editing && chapters.length ? upsellMarkup() : ''}
          ${isExample ? upsellMarkup(true) : ''}
        </div>
      </div>
    </div>`;

    app.querySelectorAll('[data-jump]').forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault();
      const el = document.getElementById(a.dataset.jump);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));

    app.querySelectorAll('[data-style]').forEach((b) => b.addEventListener('click', async () => {
      state.book.style = b.dataset.style;
      save();
      if (state.book.style === 'ai') {
        track('ai_style');
        const missing = chapters.filter((x) => !server.ai[x.key] || isStale(x));
        if (missing.length) { renderBook(false); await generateChapters(missing, full); return; }
      }
      renderBook(false);
    }));

    const edit = document.getElementById('edit');
    if (edit) edit.addEventListener('click', () => { editing = !editing; if (editing) track('edit_open'); renderBook(false); window.scrollTo(0, 0); });
    if (editing) bindEditor(full);

    const pdf = document.getElementById('pdf');
    if (pdf) pdf.addEventListener('click', () => downloadPdf(pdf, full));

    const rec = document.getElementById('recovery');
    if (rec) rec.addEventListener('click', copyRecoveryLink);
  }

  function isStale(x) {
    const ai = server.ai[x.key];
    if (!ai || ai.edited) return false;
    return (state.book.aiSig || {})[x.key] !== chapterSig(x, state);
  }

  function literaryHint(chapters) {
    if (generating) return 'ИИ пишет главы…';
    if (!server.features.ai) return 'Литературная обработка временно недоступна';
    const missing = chapters.filter((x) => !server.ai[x.key]).length;
    return missing ? `${missing} ${plural(missing, 'глава ждёт', 'главы ждут', 'глав ждут')} обработки` : 'Текст собран из твоих ответов — править можно в редакторе';
  }

  // Генерируем главы по одной: так видно прогресс и не упираемся в лимиты.
  async function generateChapters(list, full, force = false) {
    if (generating || !server.features.ai) {
      if (!server.features.ai) toast('Литературная обработка временно недоступна.');
      return;
    }
    generating = true;
    await flush();
    let done = 0;
    const status = () => document.getElementById('gen-status');
    for (const x of list) {
      if (status()) status().textContent = `ИИ пишет: «${g(x.c.title)}» (${done + 1} из ${list.length})…`;
      try {
        const entry = await api('POST', '/api/ai/chapter', { edition: full ? 'full' : 'free', chapterId: x.c.id, force });
        server.ai[x.key] = entry;
        state.book.aiSig[x.key] = chapterSig(x, state);
        done++;
      } catch (e) {
        generating = false;
        save();
        toast(e.message === 'rate_limited' ? 'На сегодня лимит обработки исчерпан — попробуй завтра.' : e.message === 'ai_busy' ? 'ИИ сейчас занят — попробуй через минуту.' : 'Не получилось обработать главу. Попробуй ещё раз.');
        if (location.hash === '#/book') renderBook(false);
        return;
      }
    }
    generating = false;
    save();
    if (location.hash === '#/book') renderBook(false);
  }

  function recoveryMarkup() {
    return `<div class="notice notice--soft">
      <span>${icon.link} Продолжить на другом устройстве — по личной ссылке. Не делись ею: по ней открывается твоя книга.</span>
      <button type="button" class="link link--strong" id="recovery">Скопировать ссылку</button>
    </div>`;
  }

  async function copyRecoveryLink() {
    try {
      await flush();
      const { url } = await api('GET', '/api/recovery-link');
      try {
        await navigator.clipboard.writeText(url);
        toast('Ссылка скопирована. Сохрани её в заметках или отправь себе.');
      } catch (e) {
        window.prompt('Скопируй ссылку:', url);
      }
    } catch (e) {
      toast('Сначала ответь хотя бы на один вопрос.');
    }
  }

  function upsellMarkup(example) {
    return `<section class="upsell">
      ${aura(24, 'aura--upsell')}
      <p class="eyebrow">${example ? 'Это бесплатная версия' : 'Что дальше'}</p>
      <h2>Это только начало твоей истории</h2>
      <p>Впереди ещё много глав: люди, которые тебя изменили, решения, о которых ты не жалеешь, ошибки, которым ты ${g('{научился|научилась}')}, и моменты, которые хочется сохранить.</p>
      <div class="upsell__row">
        <a class="btn btn--dark btn--lg" href="${example ? '#/free' : server.paid ? '#/full' : '#/offer'}">${example ? 'Начать бесплатно' : `Полная книга — ${PRICE}`} ${icon.arrow}</a>
        <span>${example ? '12 вопросов · без регистрации' : 'Единоразово, без подписки. 10 глав · 94 вопроса'}</span>
      </div>
    </section>`;
  }

  // Редактор: название, посвящение, выбор историй, правка ответов и литературного текста.
  function editorMarkup(full) {
    const literary = state.book.style === 'ai';
    return `<div class="editor">
      <section class="editor__card">
        <h2>Книга</h2>
        <div class="form">
          <label>Название<input id="b-title" value="${esc(state.book.title)}" placeholder="${defaultTitle(full)}"></label>
          <label>Имя автора<input id="b-author" value="${esc(state.profile.name)}" placeholder="Имя и фамилия"></label>
          <label class="${full ? '' : 'is-locked'}">Посвящение ${full ? '' : `<span class="lock">${icon.lock} в полной книге</span>`}
            <textarea id="b-dedication" rows="3" placeholder="Например: «Моим детям — чтобы помнили, откуда всё началось»" ${full ? '' : 'disabled'}>${esc(state.book.dedication)}</textarea>
          </label>
        </div>
      </section>
      ${bookChapters(state, full).filter((x) => x.items.length).map((x) => {
        const ai = server.ai[x.key];
        return `
        <section class="editor__card" id="ch-${x.c.id}">
          <h2>${esc(g(x.c.title))}</h2>
          ${literary ? `
            <div class="story story--ai">
              <div class="story__head">
                <p>${icon.spark} Литературный текст главы</p>
                <button type="button" class="link link--strong" data-regen="${x.key}">${ai ? 'Пересобрать из ответов' : 'Собрать из ответов'}</button>
              </div>
              ${ai ? `<textarea data-ai="${x.key}" rows="6">${esc(ai.text)}</textarea>` : '<p class="editor__empty">Текст ещё не собран.</p>'}
            </div>` : ''}
          ${x.items.map((it) => `
            <div class="story ${it.a.excluded ? 'is-off' : ''}" data-story="${it.q.id}">
              <div class="story__head">
                <p>${esc(g(it.q.title))}</p>
                <label class="switch"><input type="checkbox" data-include="${it.q.id}" ${it.a.excluded ? '' : 'checked'}><span></span>В книге</label>
              </div>
              <textarea data-text="${it.q.id}" rows="4" aria-label="Ответ">${esc(it.a.text)}</textarea>
            </div>`).join('')}
        </section>`;
      }).join('')}
      <p class="editor__hint">Правки сохраняются сразу. Выключенные истории останутся в твоих ответах, но не попадут в книгу${literary ? ' — после правок пересобери текст главы' : ''}.</p>
    </div>`;
  }

  function bindEditor(full) {
    const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('input', () => { fn(el.value); save(); }); };
    bind('b-title', (v) => { state.book.title = v; });
    bind('b-author', (v) => { state.profile.name = v; });
    bind('b-dedication', (v) => { state.book.dedication = v; });
    const fit = (ta) => { ta.style.height = 'auto'; ta.style.height = `${ta.scrollHeight + 2}px`; };
    app.querySelectorAll('[data-text]').forEach((ta) => {
      fit(ta);
      ta.addEventListener('input', () => { state.answers[ta.dataset.text].text = ta.value; save(); fit(ta); });
    });
    app.querySelectorAll('[data-include]').forEach((cb) => cb.addEventListener('change', () => {
      state.answers[cb.dataset.include].excluded = !cb.checked;
      cb.closest('.story').classList.toggle('is-off', !cb.checked);
      save();
    }));
    const aiTimers = {};
    app.querySelectorAll('[data-ai]').forEach((ta) => {
      fit(ta);
      ta.addEventListener('input', () => {
        const key = ta.dataset.ai;
        fit(ta);
        server.ai[key] = { ...server.ai[key], text: ta.value, edited: true };
        clearTimeout(aiTimers[key]);
        aiTimers[key] = setTimeout(() => api('PUT', '/api/ai/chapter', { key, text: ta.value }).then(flashSaved).catch(() => toast('Не удалось сохранить текст главы.')), 700);
      });
    });
    app.querySelectorAll('[data-regen]').forEach((b) => b.addEventListener('click', async () => {
      const x = bookChapters(state, full).find((c) => c.key === b.dataset.regen);
      if (!x) return;
      if (server.ai[x.key] && server.ai[x.key].edited && !confirm('Твои ручные правки этой главы заменятся новым текстом. Продолжить?')) return;
      b.textContent = 'ИИ пишет…';
      b.disabled = true;
      await generateChapters([x], full, true);
      renderBook(false);
    }));
  }

  async function downloadPdf(btn, full) {
    track(full ? 'pdf_full' : 'pdf_free');
    save();
    if (!window.html2pdf) { window.print(); return; }
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = 'Собираем…';
    await document.fonts.ready;

    // html2pdf клонирует элемент, поэтому смещение за экран задаём обёртке, а не самому источнику.
    const holder = document.createElement('div');
    holder.className = 'pdf-stage';
    holder.innerHTML = `<div class="pdf-root">${bookMarkup(state, full, { ai: server.ai, photos: full ? server.photos : {} }).html}</div>`;
    document.body.appendChild(holder);

    const base = state.book.title.trim() || defaultTitle(full);
    const fileName = `${base.replace(/[\\/:*?"<>|]/g, '')}${state.profile.name.trim() ? ` — ${state.profile.name.trim()}` : ''}.pdf`;
    try {
      await window.html2pdf().set({
        margin: [16, 15, 18, 15],
        filename: fileName,
        image: { type: 'jpeg', quality: 0.92 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: '#fffdf9' },
        jsPDF: { unit: 'mm', format: 'a5', orientation: 'portrait' },
        pagebreak: { mode: ['css', 'legacy'], before: ['.bk-dedication', '.bk-toc', '.bk-chapter'], avoid: ['.bk-photo', '.bk-sub', 'p'] },
      }).from(holder.firstElementChild).save();
    } catch (e) {
      toast('Не удалось собрать PDF — откроем печать, там можно выбрать «Сохранить как PDF».');
      window.print();
    } finally {
      holder.remove();
      btn.disabled = false;
      btn.innerHTML = label;
    }
  }

  // ---------- Роутинг ----------

  function go(hash) {
    if (location.hash === hash) route(); else location.hash = hash;
  }

  const TITLES = {
    landing: 'Книга моей жизни — автобиография за один час',
    offer: 'Полная книга моей жизни — Книга моей жизни',
    book: 'Моя книга — Книга моей жизни',
    example: 'Пример книги — Книга моей жизни',
    interview: 'Интервью — Книга моей жизни',
  };

  function route() {
    const hash = location.hash || '#/';
    const m = hash.match(/^#\/(free|full)(?:\/(\d+)\/(\d+))?$/);
    if (hash !== '#/book') editing = false;

    if (hash === '#/interview') return go(`#/${currentTrack()}`);
    if (m) {
      const t = m[1];
      if (t === 'full' && !server.paid) return go('#/offer');
      if (m[2] === undefined) return go(`#/${t}/${resumeStep(t).join('/')}`);
      if (!validStep(t, +m[2], +m[3])) return go(`#/${t}`);
      document.title = TITLES.interview;
      renderInterview(t, +m[2], +m[3]);
      window.scrollTo(0, 0);
    } else if (hash === '#/offer') {
      if (!document.querySelector('.offer__buy')) { track('offer_view'); save(); }
      document.title = TITLES.offer;
      renderOffer();
      window.scrollTo(0, 0);
    } else if (hash === '#/paid') {
      renderPaid();
    } else if (hash === '#/book' || hash === '#/example') {
      document.title = hash === '#/book' ? TITLES.book : TITLES.example;
      renderBook(hash === '#/example');
      window.scrollTo(0, 0);
    } else if (hash === '#/' || !hash.startsWith('#/')) {
      // Якоря лендинга (#how, #pricing) прокручиваем, не перерисовывая страницу.
      document.title = TITLES.landing;
      if (!app.querySelector('.hero') || app.dataset.prerendered) { delete app.dataset.prerendered; renderLanding(); }
      const target = hash.startsWith('#/') ? null : document.querySelector(hash);
      if (target) target.scrollIntoView({ behavior: 'smooth' }); else window.scrollTo(0, 0);
    } else {
      go('#/');
    }
  }

  async function start() {
    try {
      await loadState();
    } catch (e) {
      toast('Сервер недоступен — ответы не сохранятся, пока связь не вернётся.');
    }
    window.addEventListener('hashchange', route);
    route();
  }

  start();
})();
