(() => {
  'use strict';

  const CHAPTERS = window.CHAPTERS;
  const FOLLOW_UPS = window.FOLLOW_UPS;
  const STORAGE_KEY = 'mystory.v1';
  const app = document.getElementById('app');

  // ---------- Хранилище ----------
  // Всё (ответы, фото, место, где остановился) лежит в localStorage
  // и сохраняется на каждый ввод — можно закрыть вкладку и вернуться.

  const emptyState = () => ({ profile: { name: '', born: '', city: '', gender: 'm' }, answers: {}, photos: {}, last: null, updatedAt: null });

  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? Object.assign(emptyState(), JSON.parse(raw)) : emptyState();
    } catch (e) {
      return emptyState();
    }
  }

  let state = loadState();

  function save() {
    state.updatedAt = Date.now();
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      flashSaved();
      return true;
    } catch (e) {
      toast('Не удалось сохранить — возможно, фотографии слишком большие.');
      return false;
    }
  }

  // Ответы из другой вкладки подхватываем, чтобы не затереть их старой копией.
  window.addEventListener('storage', (e) => {
    if (e.key === STORAGE_KEY) { state = loadState(); route(); }
  });

  // ---------- Утилиты ----------

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Шаблоны вида {был|была} выбирают форму по полу автора.
  const gendered = (str, gender) => String(str).replace(/\{([^|}]*)\|([^}]*)\}/g, (_, m, f) => (gender === 'f' ? f : m));

  const ALL = CHAPTERS.flatMap((c, ci) => c.questions.map((q, qi) => ({ q, ci, qi })));
  const TOTAL = ALL.length;
  const stepIndex = (ci, qi) => ALL.findIndex((x) => x.ci === ci && x.qi === qi);

  function isAnswered(q, s = state) {
    if (q.type === 'profile') return Boolean(s.profile.name.trim());
    const a = s.answers[q.id];
    return Boolean(a && ((a.text || '').trim() || (a.options || []).length));
  }

  const answeredCount = (s = state) => ALL.filter(({ q }) => isAnswered(q, s)).length;
  const chapterCount = (c) => c.questions.filter((q) => isAnswered(q)).length;

  function plural(n, one, few, many) {
    const m10 = n % 10, m100 = n % 100;
    if (m10 === 1 && m100 !== 11) return one;
    if (m10 >= 2 && m10 <= 4 && (m100 < 10 || m100 >= 20)) return few;
    return many;
  }

  function toast(text) {
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }

  let savedTimer;
  function flashSaved() {
    const el = document.querySelector('[data-saved]');
    if (!el) return;
    el.classList.add('is-on');
    clearTimeout(savedTimer);
    savedTimer = setTimeout(() => el.classList.remove('is-on'), 1400);
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
    chat: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"><path d="M4 5h16v11H9l-5 4z"/></svg>',
    save: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5"/></svg>',
  };

  const logo = () => `<a class="logo" href="#/"><span class="logo__mark">${icon.book}</span><span>Моя история</span></a>`;

  // Мягкое цветное пятно — визуальный «характер» главы вместо фотографий.
  const aura = (hue, extra = '') => `<div class="aura ${extra}" style="--h:${hue}" aria-hidden="true"></div>`;

  function resumeInfo() {
    const done = answeredCount();
    if (!done) return null;
    const [ci, qi] = resumeStep();
    return { done, ci, qi, chapter: CHAPTERS[ci], n: stepIndex(ci, qi) + 1 };
  }

  // ---------- Лендинг ----------

  function renderLanding() {
    const r = resumeInfo();
    const pct = Math.round((answeredCount() / TOTAL) * 100);

    app.innerHTML = `
    <header class="nav" id="nav">
      ${logo()}
      <nav class="nav__links" id="nav-links">
        <a href="#how">Как это работает</a>
        <a href="#chapters">Вопросы</a>
        <a href="#/example">Пример книги</a>
      </nav>
      <a class="btn btn--dark btn--sm" href="#/interview">${r ? 'Продолжить' : '<span class="hide-sm">Начать интервью</span><span class="show-sm">Начать</span>'}</a>
      <button type="button" class="nav__burger" id="burger" aria-label="Меню" aria-expanded="false" aria-controls="nav-links"><span></span></button>
    </header>

    <section class="hero">
      ${aura(24, 'aura--hero-a')}${aura(265, 'aura--hero-b')}${aura(165, 'aura--hero-c')}
      <div class="hero__copy">
        <p class="pill">${icon.spark} Голосом или текстом</p>
        <h1>Интервью <em>с самим собой</em></h1>
        <p class="hero__sub">Твоя автобиография за один час</p>
        <p class="hero__text">Ответь на несколько вопросов — голосом или текстом — и мы соберём полноценную автобиографию всей твоей жизни.</p>
        ${r ? `
        <a class="resume" href="#/interview">
          <div class="resume__top"><span>Ты остановил${state.profile.gender === 'f' ? 'ась' : 'ся'} на вопросе ${r.n} из ${TOTAL}</span><strong>${pct}%</strong></div>
          <div class="bar"><span style="width:${pct}%"></span></div>
          <div class="resume__bottom"><span>Глава «${esc(r.chapter.title)}»</span><span class="resume__go">Продолжить ${icon.arrow}</span></div>
        </a>` : `
        <div class="hero__actions">
          <a class="btn btn--dark btn--lg" href="#/interview">Начать интервью ${icon.arrow}</a>
          <a class="btn btn--ghost btn--lg" href="#/example">Пример книги</a>
        </div>`}
        <p class="hero__fine">Бесплатно · без регистрации · прогресс сохраняется автоматически</p>
      </div>

      <div class="hero__demo" aria-hidden="true">
        <div class="demo-card demo-card--q">
          <p class="demo-card__meta">Вопрос 8 из ${TOTAL} · Детство</p>
          <p class="demo-card__title">Какое место из детства ты помнишь лучше всего?</p>
          <div class="demo-card__answer">Дом бабушки в деревне. Скрипучее крыльцо, запах яблок в сенях…<span class="caret"></span></div>
          <div class="demo-card__row"><span class="demo-mic">${icon.mic}</span><span class="wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span></div>
        </div>
        <div class="demo-card demo-card--follow">
          <span class="demo-card__avatar">${icon.spark}</span>
          <p>А кто был рядом с тобой в тот момент?</p>
        </div>
        <div class="demo-book"><span>Автобиография</span><strong>Сергей Волков</strong><em>1968 — ${new Date().getFullYear()}</em></div>
      </div>
    </section>

    <section class="stats">
      <div><strong>${TOTAL}</strong><span>вопросов</span></div>
      <div><strong>${CHAPTERS.length}</strong><span>глав жизни</span></div>
      <div><strong>~1 час</strong><span>на интервью</span></div>
      <div><strong>PDF</strong><span>готовая книга</span></div>
    </section>

    <section class="section" id="how">
      <p class="eyebrow">Как это работает</p>
      <h2>Ты рассказываешь. Мы собираем книгу.</h2>
      <div class="features">
        <article class="feature">${aura(24, 'aura--icon')}<span class="feature__icon">${icon.mic}</span><h3>Отвечай как удобно</h3><p>Пиши или говори вслух — мы расшифруем голос в текст.</p></article>
        <article class="feature">${aura(265, 'aura--icon')}<span class="feature__icon">${icon.chat}</span><h3>Вспоминай детали</h3><p>Уточняющие вопросы помогают достать истории, о которых ты забыл.</p></article>
        <article class="feature">${aura(165, 'aura--icon')}<span class="feature__icon">${icon.save}</span><h3>Возвращайся когда угодно</h3><p>Каждый ответ сохраняется сразу. Закрой вкладку — продолжишь с того же вопроса.</p></article>
        <article class="feature">${aura(205, 'aura--icon')}<span class="feature__icon">${icon.book}</span><h3>Получи книгу</h3><p>Обложка, содержание, главы и фото — в аккуратном PDF.</p></article>
      </div>
    </section>

    <section class="section" id="chapters">
      <p class="eyebrow">О чём мы спросим</p>
      <h2>${CHAPTERS.length} глав — вся жизнь</h2>
      <div class="chapter-grid">
        ${CHAPTERS.map((c, i) => `
          <a class="chapter-card" href="#/interview/${i}/0">
            ${aura(c.hue, 'aura--card')}
            <span class="chapter-card__num">${String(i + 1).padStart(2, '0')}</span>
            <strong>${esc(c.title)}</strong>
            <span class="chapter-card__q">${esc(gendered(c.questions[c.questions[0].type === 'profile' ? 1 : 0].title, state.profile.gender))}</span>
          </a>`).join('')}
      </div>
    </section>

    <section class="section">
      <div class="product">
        ${aura(24, 'aura--product-a')}${aura(265, 'aura--product-b')}
        <div class="product__copy">
          <p class="eyebrow">Один продукт</p>
          <h2>Сгенерировать автобиографию</h2>
          <p>Пройди интервью и скачай готовую книгу своей жизни. Отличный подарок родителям — их история тоже важна.</p>
        </div>
        <div class="product__card">
          <ul class="checks">
            <li>${icon.check} ${TOTAL} вопросов в ${CHAPTERS.length} главах</li>
            <li>${icon.check} Ответы голосом или текстом</li>
            <li>${icon.check} Фотографии с подписями</li>
            <li>${icon.check} Книга в PDF формата A5</li>
            <li>${icon.check} Автосохранение прогресса</li>
          </ul>
          <div class="product__price"><strong>Бесплатно</strong><span>в раннем доступе</span></div>
          <a class="btn btn--dark btn--lg btn--block" href="#/interview">${r ? 'Продолжить интервью' : 'Сгенерировать автобиографию'} ${icon.arrow}</a>
        </div>
      </div>
    </section>

    <footer class="footer">${logo()}<span>Ответы хранятся только в твоём браузере и никуда не отправляются.</span></footer>`;

    const nav = document.getElementById('nav');
    const burger = document.getElementById('burger');
    const setMenu = (open) => { nav.classList.toggle('nav--open', open); burger.setAttribute('aria-expanded', String(open)); };
    burger.addEventListener('click', () => setMenu(!nav.classList.contains('nav--open')));
    nav.querySelectorAll('.nav__links a').forEach((a) => a.addEventListener('click', () => setMenu(false)));
  }

  // ---------- Интервью ----------

  function firstOpenStep() {
    const hit = ALL.find(({ q }) => !isAnswered(q));
    return hit ? [hit.ci, hit.qi] : [0, 0];
  }

  // Возвращаемся туда, где человек был в прошлый раз; иначе — к первому пустому вопросу.
  function resumeStep() {
    const l = state.last;
    if (Array.isArray(l) && CHAPTERS[l[0]] && CHAPTERS[l[0]].questions[l[1]]) return l;
    return firstOpenStep();
  }

  let recognition = null;

  function stopRecognition() {
    if (recognition) {
      recognition.onend = null;
      recognition.stop();
      recognition = null;
    }
  }

  function renderInterview(ci, qi) {
    stopRecognition();
    const chapter = CHAPTERS[ci];
    const q = chapter && chapter.questions[qi];
    if (!q) return go('#/interview');

    state.last = [ci, qi];
    save();

    const g = state.profile.gender;
    const done = answeredCount();
    const pct = Math.round((done / TOTAL) * 100);
    const n = stepIndex(ci, qi) + 1;
    const answer = state.answers[q.id] || { text: '', options: [] };
    const photo = state.photos[chapter.id];
    const isLast = n === TOTAL;
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

    app.innerHTML = `
    <div class="studio">
      <header class="studio__bar">
        ${logo()}
        <div class="studio__progress">
          <span>${done} из ${TOTAL} ${plural(done, 'ответ', 'ответа', 'ответов')}</span>
          <div class="bar"><span style="width:${pct}%"></span></div>
        </div>
        <span class="saved" data-saved>${icon.check} Сохранено</span>
        <a class="btn btn--ghost btn--sm" href="#/book">${icon.book} Книга</a>
      </header>

      <div class="studio__body">
        <nav class="chapters" aria-label="Главы">
          ${CHAPTERS.map((c, i) => {
            const k = chapterCount(c), all = c.questions.length;
            return `<a href="#/interview/${i}/0" class="chapters__item ${i === ci ? 'is-active' : ''} ${k === all ? 'is-done' : ''}">
              <span class="chapters__dot" style="--h:${c.hue}">${k === all ? icon.check : i + 1}</span>
              <span class="chapters__name">${esc(c.title)}</span>
              <span class="chapters__count">${k}/${all}</span>
            </a>`;
          }).join('')}
        </nav>

        <main class="stage">
          ${aura(chapter.hue, 'aura--stage')}
          <div class="card">
            <div class="card__top">
              <p class="eyebrow">Глава ${ci + 1} · ${esc(chapter.title)}</p>
              <p class="card__n">Вопрос ${n} из ${TOTAL}</p>
            </div>
            <div class="dots">${chapter.questions.map((qq, i) => `<a href="#/interview/${ci}/${i}" class="${i === qi ? 'is-on' : ''} ${isAnswered(qq) ? 'is-done' : ''}" aria-label="Вопрос ${i + 1}"></a>`).join('')}</div>

            <h1 class="q-title">${esc(gendered(q.title, g))}</h1>
            <p class="q-lead">${esc(gendered(q.lead || '', g))}</p>

            ${q.type === 'profile' ? profileForm() : `
              ${q.options ? `<div class="options">${q.options.map((o, i) => {
                const on = (answer.options || []).includes(i);
                return `<button type="button" class="option ${on ? 'is-on' : ''}" data-opt="${i}" aria-pressed="${on}"><span class="option__mark">${icon.check}</span>${esc(gendered(o, g))}</button>`;
              }).join('')}</div>` : ''}
              <div class="answer">
                <textarea id="answer" rows="${q.options ? 3 : 6}" placeholder="${q.options ? 'Расскажи подробнее — что вспоминается?' : 'Начни писать или нажми на микрофон…'}">${esc(answer.text)}</textarea>
                <div class="answer__tools">
                  ${SpeechRec ? `<button type="button" class="mic" id="mic">${icon.mic}<span>Ответить голосом</span></button>` : '<span class="hint">Голосовой ввод работает в Chrome и Safari</span>'}
                  <label class="photo-add" title="Фото к главе">${icon.photo}<span>${photo ? 'Заменить фото' : 'Фото к главе'}</span><input type="file" id="photo" accept="image/*" hidden></label>
                </div>
              </div>
              <div class="follow" id="follow" hidden>
                <span class="follow__avatar">${icon.spark}</span>
                <div><p class="follow__label">Уточняющий вопрос</p><p class="follow__text" id="follow-text"></p></div>
              </div>
            `}

            ${photo ? `
              <figure class="photo-preview"><img src="${photo.src}" alt="">
                <figcaption><input id="caption" value="${esc(photo.caption)}" placeholder="Подпись к фото"><button type="button" class="link" id="photo-remove">Убрать</button></figcaption>
              </figure>` : ''}

            <div class="card__nav">
              ${n > 1 ? `<a class="btn btn--ghost" href="#/interview/${prevStep(ci, qi).join('/')}">${icon.back}<span class="hide-sm">Назад</span></a>` : '<span></span>'}
              <div class="card__nav-right">
                <a class="link" href="${nextHref(ci, qi)}">Пропустить</a>
                <a class="btn btn--dark" id="next" href="${nextHref(ci, qi)}">${isLast ? 'Собрать книгу' : 'Далее'} ${icon.arrow}</a>
              </div>
            </div>
          </div>
          <p class="stage__hint">Прогресс сохраняется автоматически — можно закрыть вкладку и вернуться позже. <kbd>⌘</kbd>+<kbd>Enter</kbd> — следующий вопрос.</p>
        </main>
      </div>
    </div>`;

    bindInterview(chapter, q, SpeechRec);
  }

  function profileForm() {
    const p = state.profile;
    return `<div class="form">
      <label>Как тебя зовут?<input id="p-name" value="${esc(p.name)}" placeholder="Имя и фамилия" autocomplete="name"></label>
      <div class="form__row">
        <label>Год рождения<input id="p-born" value="${esc(p.born)}" inputmode="numeric" maxlength="4" placeholder="1968"></label>
        <label>Место рождения<input id="p-city" value="${esc(p.city)}" placeholder="Город или село"></label>
      </div>
      <fieldset class="seg"><legend>Как обращаться к тебе в книге?</legend>
        <button type="button" data-gender="m" class="${p.gender !== 'f' ? 'is-on' : ''}">Он</button>
        <button type="button" data-gender="f" class="${p.gender === 'f' ? 'is-on' : ''}">Она</button>
      </fieldset>
    </div>`;
  }

  function nextStep(ci, qi) {
    if (qi + 1 < CHAPTERS[ci].questions.length) return [ci, qi + 1];
    if (ci + 1 < CHAPTERS.length) return [ci + 1, 0];
    return null;
  }

  function prevStep(ci, qi) {
    if (qi > 0) return [ci, qi - 1];
    return [ci - 1, CHAPTERS[ci - 1].questions.length - 1];
  }

  function nextHref(ci, qi) {
    const n = nextStep(ci, qi);
    return n ? `#/interview/${n.join('/')}` : '#/book';
  }

  function bindInterview(chapter, q, SpeechRec) {
    const answer = () => (state.answers[q.id] ||= { text: '', options: [] });

    // Профиль
    ['name', 'born', 'city'].forEach((k) => {
      const el = document.getElementById(`p-${k}`);
      if (el) el.addEventListener('input', () => { state.profile[k] = el.value; save(); });
    });
    const nameInput = document.getElementById('p-name');
    if (nameInput && !nameInput.value) nameInput.focus({ preventScroll: true });
    app.querySelectorAll('[data-gender]').forEach((b) => b.addEventListener('click', () => {
      state.profile.gender = b.dataset.gender;
      save();
      route();
    }));

    // Варианты
    app.querySelectorAll('[data-opt]').forEach((b) => b.addEventListener('click', () => {
      const i = Number(b.dataset.opt);
      const opts = answer().options;
      const at = opts.indexOf(i);
      at >= 0 ? opts.splice(at, 1) : opts.push(i);
      opts.sort();
      b.classList.toggle('is-on', at < 0);
      b.setAttribute('aria-pressed', String(at < 0));
      save();
    }));

    // Текст + уточняющий вопрос
    const ta = document.getElementById('answer');
    const follow = document.getElementById('follow');
    const updateFollow = () => {
      if (!ta || !follow) return;
      const len = ta.value.trim().length;
      const show = len > 0 && len < 160;
      follow.hidden = !show;
      if (show) {
        const seed = [...q.id].reduce((s, c) => s + c.charCodeAt(0), 0);
        document.getElementById('follow-text').textContent = gendered(FOLLOW_UPS[seed % FOLLOW_UPS.length], state.profile.gender);
      }
    };
    if (ta) {
      ta.addEventListener('input', () => { answer().text = ta.value; save(); updateFollow(); });
      updateFollow();
      if (!q.options) {
        ta.focus({ preventScroll: true });
        ta.setSelectionRange(ta.value.length, ta.value.length);
      }
    }

    // ⌘/Ctrl + Enter — следующий вопрос
    app.querySelector('.card').addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        document.getElementById('next').click();
      }
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
        const base = ta.value ? ta.value.replace(/\s*$/, ' ') : '';
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
          updateFollow();
        };
        recognition.onerror = (e) => {
          if (e.error === 'not-allowed') toast('Разреши доступ к микрофону в настройках браузера.');
        };
        recognition.onend = () => { recognition = null; setRec(false); };
        recognition.start();
        setRec(true);
      });
    }

    // Фото главы
    const file = document.getElementById('photo');
    if (file) file.addEventListener('change', async () => {
      const f = file.files[0];
      if (!f) return;
      try {
        const prev = state.photos[chapter.id];
        const src = await compressImage(f, 1100, 0.72);
        state.photos[chapter.id] = { src, caption: prev ? prev.caption : '' };
        if (!save()) { if (prev) state.photos[chapter.id] = prev; else delete state.photos[chapter.id]; }
        route();
      } catch (e) {
        toast('Не получилось прочитать изображение.');
      }
    });
    const cap = document.getElementById('caption');
    if (cap) cap.addEventListener('input', () => { state.photos[chapter.id].caption = cap.value; save(); });
    const rm = document.getElementById('photo-remove');
    if (rm) rm.addEventListener('click', () => { delete state.photos[chapter.id]; save(); route(); });
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

  function paragraphs(text) {
    return String(text || '').split(/\n\s*\n|\n/).map((p) => p.trim()).filter(Boolean);
  }

  function chapterBody(c, s) {
    const g = s.profile.gender;
    const parts = [];
    if (c.id === 'about') {
      const { name, born, city } = s.profile;
      const bits = [];
      if (name) bits.push(`Меня зовут ${name}.`);
      if (born || city) bits.push(`Я ${gendered('{родился|родилась}', g)}${born ? ` в ${born} году` : ''}${city ? ` — ${city}` : ''}.`);
      if (bits.length) parts.push(`<p class="bk-drop">${esc(bits.join(' '))}</p>`);
    }
    c.questions.forEach((q) => {
      if (q.type === 'profile') return;
      const a = s.answers[q.id];
      if (!a) return;
      const lines = [];
      if (q.options && a.options && a.options.length) lines.push(a.options.map((i) => gendered(q.options[i], g)).join(' '));
      lines.push(...paragraphs(a.text));
      if (!lines.length) return;
      parts.push(`<h3 class="bk-sub">${esc(gendered(q.title, g))}</h3>`);
      parts.push(...lines.map((l) => `<p>${esc(l)}</p>`));
    });
    return parts;
  }

  function bookMarkup(s) {
    const name = s.profile.name.trim() || 'Моя история';
    const years = s.profile.born ? `${esc(s.profile.born)} — ${new Date().getFullYear()}` : '';
    const chapters = CHAPTERS.map((c) => ({ c, body: chapterBody(c, s), photo: s.photos[c.id] })).filter((x) => x.body.length || x.photo);

    return {
      chapters,
      html: `
      <section class="bk-cover">
        <div class="bk-cover__frame">
          <p class="bk-cover__kicker">Автобиография</p>
          <h1>${esc(name)}</h1>
          <span class="bk-cover__rule"></span>
          <p class="bk-cover__years">${years}</p>
          <p class="bk-cover__brand">Моя история</p>
        </div>
      </section>
      ${chapters.length ? `
      <section class="bk-toc">
        <h2>Содержание</h2>
        <ol>${chapters.map((x, i) => `<li><span>Глава ${i + 1}</span>${esc(x.c.title)}</li>`).join('')}</ol>
      </section>` : ''}
      ${chapters.map((x, i) => `
      <section class="bk-chapter" id="ch-${x.c.id}">
        <p class="bk-chapter__num">Глава ${i + 1}</p>
        <h2>${esc(x.c.title)}</h2>
        ${x.photo ? `<figure class="bk-photo"><img src="${x.photo.src}" alt="">${x.photo.caption ? `<figcaption>${esc(x.photo.caption)}</figcaption>` : ''}</figure>` : ''}
        ${x.body.join('')}
      </section>`).join('')}
      ${chapters.length ? '' : `<section class="bk-empty"><p>Здесь появятся главы твоей книги.</p><a class="btn btn--dark" href="#/interview">Ответить на вопросы ${icon.arrow}</a></section>`}`,
    };
  }

  function renderBook(isExample) {
    stopRecognition();
    const s = isExample ? window.EXAMPLE_STATE : state;
    const { chapters, html } = bookMarkup(s);
    const done = answeredCount(s);

    app.innerHTML = `
    <div class="reader">
      <header class="reader__bar">
        <a class="btn btn--ghost btn--sm" href="${isExample ? '#/' : '#/interview'}">${icon.back}<span class="hide-sm">${isExample ? 'На главную' : 'К интервью'}</span></a>
        ${isExample ? '<span class="reader__label">Пример книги</span>' : `<span class="reader__label">${done} из ${TOTAL} ${plural(done, 'ответ', 'ответа', 'ответов')}</span>`}
        <div class="reader__actions">
          ${isExample ? `<a class="btn btn--dark btn--sm" href="#/interview">Создать свою ${icon.arrow}</a>` : `
            <button class="btn btn--ghost btn--sm hide-sm" id="reset">Начать заново</button>
            <button class="btn btn--dark btn--sm" id="pdf" ${chapters.length ? '' : 'disabled'}>${icon.download} Скачать PDF</button>`}
        </div>
      </header>
      <div class="reader__body">
        <aside class="reader__toc">
          ${chapters.map((x) => `<a href="#ch-${x.c.id}" data-jump="ch-${x.c.id}"><span class="reader__thumb" style="--h:${x.c.hue}">${x.photo ? `<img src="${x.photo.src}" alt="">` : ''}</span>${esc(x.c.title)}</a>`).join('')}
        </aside>
        <article class="paper" id="book">${html}</article>
      </div>
    </div>`;

    app.querySelectorAll('[data-jump]').forEach((a) => a.addEventListener('click', (e) => {
      e.preventDefault();
      document.getElementById(a.dataset.jump).scrollIntoView({ behavior: 'smooth', block: 'start' });
    }));

    const reset = document.getElementById('reset');
    if (reset) reset.addEventListener('click', () => {
      if (!confirm('Удалить все ответы и фотографии? Это нельзя отменить.')) return;
      state = emptyState();
      save();
      go('#/interview/0/0');
    });

    const pdf = document.getElementById('pdf');
    if (pdf) pdf.addEventListener('click', () => downloadPdf(pdf));
  }

  async function downloadPdf(btn) {
    if (!window.html2pdf) { window.print(); return; }
    const label = btn.innerHTML;
    btn.disabled = true;
    btn.textContent = 'Собираем книгу…';
    await document.fonts.ready;

    // html2pdf клонирует элемент, поэтому смещение за экран задаём обёртке, а не самому источнику.
    const holder = document.createElement('div');
    holder.className = 'pdf-stage';
    holder.innerHTML = `<div class="pdf-root">${bookMarkup(state).html}</div>`;
    document.body.appendChild(holder);

    const fileName = `${(state.profile.name.trim() || 'Моя история').replace(/[\\/:*?"<>|]/g, '')} — автобиография.pdf`;
    try {
      await window.html2pdf().set({
        margin: [16, 15, 18, 15],
        filename: fileName,
        image: { type: 'jpeg', quality: 0.92 },
        html2canvas: { scale: 2, useCORS: true, backgroundColor: '#fffdf9' },
        jsPDF: { unit: 'mm', format: 'a5', orientation: 'portrait' },
        pagebreak: { mode: ['css', 'legacy'], before: ['.bk-toc', '.bk-chapter'], avoid: ['.bk-photo', '.bk-sub', 'p'] },
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

  function route() {
    const hash = location.hash || '#/';
    const m = hash.match(/^#\/interview(?:\/(\d+)\/(\d+))?$/);
    if (m) {
      if (m[1] === undefined) return go(`#/interview/${resumeStep().join('/')}`);
      renderInterview(Number(m[1]), Number(m[2]));
      window.scrollTo(0, 0);
    } else if (hash === '#/book' || hash === '#/example') {
      renderBook(hash === '#/example');
      window.scrollTo(0, 0);
    } else if (hash === '#/' || !hash.startsWith('#/')) {
      // Якоря лендинга (#how, #chapters) прокручиваем, не перерисовывая страницу.
      if (!app.querySelector('.hero')) renderLanding();
      const target = hash.startsWith('#/') ? null : document.querySelector(hash);
      if (target) target.scrollIntoView({ behavior: 'smooth' }); else window.scrollTo(0, 0);
    } else {
      go('#/');
    }
  }

  window.addEventListener('hashchange', route);
  route();
})();
