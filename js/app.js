(() => {
  'use strict';

  const CHAPTERS = window.CHAPTERS;
  const FOLLOW_UPS = window.FOLLOW_UPS;
  const STORAGE_KEY = 'mystory.v1';
  const app = document.getElementById('app');

  // ---------- Хранилище ----------

  const emptyState = () => ({ profile: { name: '', born: '', city: '', gender: 'm' }, answers: {}, photos: {} });

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
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
      flashSaved();
      return true;
    } catch (e) {
      toast('Не удалось сохранить — возможно, фотографии слишком большие.');
      return false;
    }
  }

  // ---------- Утилиты ----------

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Шаблоны вида {был|была} выбирают форму по полу автора.
  const gendered = (str, gender) => String(str).replace(/\{([^|}]*)\|([^}]*)\}/g, (_, m, f) => (gender === 'f' ? f : m));

  const allQuestions = () => CHAPTERS.flatMap((c, ci) => c.questions.map((q, qi) => ({ q, ci, qi })));

  function isAnswered(q, s = state) {
    if (q.type === 'profile') return Boolean(s.profile.name.trim());
    const a = s.answers[q.id];
    return Boolean(a && ((a.text || '').trim() || (a.options || []).length));
  }

  function progress(s = state) {
    const all = allQuestions();
    return Math.round((all.filter(({ q }) => isAnswered(q, s)).length / all.length) * 100);
  }

  function chapterDone(c) {
    return c.questions.every((q) => isAnswered(q));
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
    arrow: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    back: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M19 12H5M11 6l-6 6 6 6"/></svg>',
    play: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="10"/><path d="M10 8.5v7l5.5-3.5z" fill="currentColor"/></svg>',
    mic: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
    book: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><path d="M3 5.5c3-1 6-1 9 1 3-2 6-2 9-1V19c-3-1-6-1-9 1-3-2-6-2-9-1z"/><path d="M12 6.5V20"/></svg>',
    photo: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-8 8"/></svg>',
    download: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    check: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5 9-10"/></svg>',
    gift: '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"><rect x="3" y="9" width="18" height="12" rx="1"/><path d="M2 9h20M12 9v12M12 9c-2-4-6-5-6-2s6 2 6 2zM12 9c2-4 6-5 6-2s-6 2-6 2z"/></svg>',
  };

  const logo = (dark) => `<a class="logo ${dark ? 'logo--light' : ''}" href="#/">${icon.book}<span>Моя история</span></a>`;

  // Пейзаж из слоёв гор — заменяет фотографии в MVP.
  function scene(name, extra = '') {
    return `<div class="scene scene--${name} ${extra}" aria-hidden="true">
      <div class="scene__sun"></div>
      <svg class="scene__hills" viewBox="0 0 800 400" preserveAspectRatio="none">
        <path class="h1" d="M0 230 L90 180 L170 215 L260 150 L360 205 L450 160 L560 210 L660 165 L800 200 V400 H0Z"/>
        <path class="h2" d="M0 280 L120 235 L230 270 L340 225 L470 275 L590 240 L700 270 L800 250 V400 H0Z"/>
        <path class="h3" d="M0 330 C140 300 260 320 380 305 S640 290 800 315 V400 H0Z"/>
      </svg>
      <div class="scene__grain"></div>
    </div>`;
  }

  // ---------- Лендинг ----------

  function renderLanding() {
    app.innerHTML = `
    <header class="nav">
      ${logo(true)}
      <nav class="nav__links">
        <a href="#how">Как это работает</a>
        <a href="#/example">Пример</a>
        <a href="#pricing">Цены</a>
      </nav>
      <a class="btn btn--light btn--sm" href="#/interview">${progress() ? 'Продолжить историю' : 'Создать свою историю'}</a>
    </header>

    <section class="hero">
      ${scene('sunset', 'scene--hero')}
      <div class="hero__inner">
        <h1>Твоя жизнь заслуживает быть услышанной</h1>
        <p>Ответь на несколько вопросов — голосом или текстом — и мы соберём полноценную автобиографию с историями, которые ты, возможно, уже не помнишь.</p>
        <div class="hero__actions">
          <a class="btn btn--light" href="#/interview">Начать ${icon.arrow}</a>
          <a class="link-light" href="#/example">${icon.play} Посмотреть пример</a>
        </div>
      </div>
      <p class="hero__note">Иногда самые важные моменты<br>не в памяти, а в сердце.</p>
    </section>

    <section class="how" id="how">
      <div class="how__text">
        <p class="eyebrow">Как это работает</p>
        <h2>Просто. Глубоко. По-настоящему.</h2>
        <p class="muted">Ты отвечаешь на вопросы, а мы превращаем их в живую историю твоей жизни — с воспоминаниями, эмоциями и деталями, которые делают тебя тобой.</p>
        <ol class="steps">
          <li><span>1</span><div><h3>Ты отвечаешь на вопросы</h3><p>О детстве, людях, выборах, мечтах и самых ярких моментах. Можно говорить вслух.</p></div></li>
          <li><span>2</span><div><h3>Мы помогаем вспомнить</h3><p>Уточняющие вопросы подсказывают детали, о которых ты мог забыть.</p></div></li>
          <li><span>3</span><div><h3>История собирается в книгу</h3><p>Главы, фотографии и подписи складываются в красивую вёрстку.</p></div></li>
          <li><span>4</span><div><h3>Ты скачиваешь PDF</h3><p>Готовую книгу можно сохранить, распечатать или подарить близким.</p></div></li>
        </ol>
      </div>
      <div class="how__visual">${bookMock('Моя история', '')}</div>
    </section>

    <section class="showcase">
      <div class="showcase__text">
        <h2>Твоя история в красивой книге</h2>
        <span class="rule"></span>
        <p>После интервью все воспоминания соберутся в единую автобиографию. Ты сможешь вернуться, дополнить ответы и скачать новую версию в PDF.</p>
        <a class="btn btn--cream" href="#/example">Посмотреть пример ${icon.arrow}</a>
      </div>
      <div class="showcase__visual">${bookMock('Моя история', 'Автобиография')}</div>
    </section>

    <section class="pricing" id="pricing">
      <div class="pricing__intro">
        <p class="eyebrow eyebrow--light">Цены</p>
        <h2>Сохрани свою историю на всю жизнь</h2>
        <p>Сейчас идёт ранний доступ — создание книги и скачивание PDF бесплатны.</p>
        <div class="gift">${icon.gift}<span>Отличный подарок для родителей и близких. Их история — это тоже важно.</span></div>
      </div>
      <div class="plans">
        <article class="plan">
          <h3>Ранний доступ</h3><p>Все главы, фотографии и PDF-книга</p>
          <strong>0 ₽</strong>
          <a class="btn btn--dark btn--block" href="#/interview">Начать</a>
        </article>
        <article class="plan">
          <h3>С редактором</h3><p>Литературная обработка текста с помощью ИИ</p>
          <strong>1 990 ₽</strong>
          <span class="btn btn--ghost btn--block" aria-disabled="true">Скоро</span>
        </article>
        <article class="plan">
          <h3>Печатная книга</h3><p>Твёрдый переплёт, фотографии, доставка</p>
          <strong class="plan__small">Цена после расчёта</strong>
          <span class="btn btn--ghost btn--block" aria-disabled="true">Скоро</span>
        </article>
      </div>
    </section>

    <footer class="footer">${logo(false)}<span class="muted">Ответы хранятся только в твоём браузере.</span></footer>`;
  }

  function bookMock(title, subtitle) {
    return `<div class="mock">
      <div class="mock__photo mock__photo--a">${scene('lake')}</div>
      <div class="mock__photo mock__photo--b">${scene('field')}</div>
      <div class="mock__book">
        <div class="mock__title">${esc(title)}</div>
        ${subtitle ? `<div class="mock__sub">${esc(subtitle)}</div>` : ''}
      </div>
    </div>`;
  }

  // ---------- Интервью ----------

  function firstOpenStep() {
    const hit = allQuestions().find(({ q }) => !isAnswered(q));
    return hit ? [hit.ci, hit.qi] : [0, 0];
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

    const g = state.profile.gender;
    const pct = progress();
    const answer = state.answers[q.id] || { text: '', options: [] };
    const photo = state.photos[chapter.id];
    const isLast = ci === CHAPTERS.length - 1 && qi === chapter.questions.length - 1;
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;

    app.innerHTML = `
    <div class="studio">
      <aside class="studio__side">
        ${logo(true)}
        <nav class="chapters">
          ${CHAPTERS.map((c, i) => `
            <a href="#/interview/${i}/0" class="chapters__item ${i === ci ? 'is-active' : ''} ${chapterDone(c) ? 'is-done' : ''}">
              <span class="chapters__dot">${chapterDone(c) ? icon.check : ''}</span>${esc(c.title)}
            </a>`).join('')}
        </nav>
        <div class="ring-card">
          <p>Ты на пути<br>к своей книге</p>
          <div class="ring" style="--p:${pct}"><span>${pct}%</span></div>
        </div>
        <a class="btn btn--outline-light btn--block" href="#/book">Открыть книгу</a>
      </aside>

      <main class="studio__main">
        <div class="studio__content">
          <div class="studio__top">
            <p class="eyebrow eyebrow--light">Глава ${ci + 1} · ${esc(chapter.title)}</p>
            <div class="dots">${chapter.questions.map((_, i) => `<span class="${i === qi ? 'is-on' : ''}"></span>`).join('')}</div>
          </div>

          <h1 class="q-title">${esc(gendered(q.title, g))}</h1>
          <p class="q-lead">${esc(gendered(q.lead || '', g))}</p>

          ${q.type === 'profile' ? profileForm() : `
            ${q.options ? `<div class="options">${q.options.map((o, i) => {
              const on = (answer.options || []).includes(i);
              return `<button type="button" class="option ${on ? 'is-on' : ''}" data-opt="${i}" aria-pressed="${on}"><span class="option__mark"></span>${esc(gendered(o, g))}</button>`;
            }).join('')}</div>` : ''}
            <div class="answer">
              <textarea id="answer" rows="${q.options ? 4 : 7}" placeholder="${q.options ? 'Расскажи подробнее — что вспоминается?' : 'Напиши свой ответ…'}">${esc(answer.text)}</textarea>
              ${SpeechRec ? `<button type="button" class="mic" id="mic" aria-label="Надиктовать ответ" title="Надиктовать голосом">${icon.mic}</button>` : ''}
            </div>
            <p class="hint">${SpeechRec ? 'Можно писать или записывать голос.' : 'Голосовой ввод доступен в Chrome и Safari.'} <span class="saved" data-saved>Сохранено</span></p>
            <div class="follow" id="follow" hidden>
              <span class="follow__avatar">${icon.book}</span>
              <div><p class="follow__label">Уточняющий вопрос</p><p class="follow__text" id="follow-text"></p></div>
            </div>
          `}

          <div class="photo-slot">
            ${photo ? `
              <figure class="photo-slot__preview"><img src="${photo.src}" alt="">
                <figcaption><input id="caption" value="${esc(photo.caption)}" placeholder="Подпись к фото"><button type="button" class="link-light" id="photo-remove">Убрать</button></figcaption>
              </figure>` : `
              <label class="photo-slot__add">${icon.photo}<span>Добавить фото к главе «${esc(chapter.title)}»</span><input type="file" id="photo" accept="image/*" hidden></label>`}
          </div>

          <div class="studio__nav">
            <div>
              ${ci || qi ? `<a class="link-light" href="#/interview/${prevStep(ci, qi).join('/')}">${icon.back} Назад</a>` : ''}
              <a class="link-light muted-light" href="${nextHref(ci, qi)}">Пропустить</a>
            </div>
            <a class="btn btn--light" href="${nextHref(ci, qi)}">${isLast ? 'Собрать книгу' : 'Далее'} ${icon.arrow}</a>
          </div>
        </div>
        <div class="studio__scene">${scene(chapter.scene)}</div>
      </main>
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
      <fieldset class="seg"><legend>Как к тебе обращаться в книге?</legend>
        <button type="button" data-gender="m" class="${p.gender !== 'f' ? 'is-on' : ''}">Он</button>
        <button type="button" data-gender="f" class="${p.gender === 'f' ? 'is-on' : ''}">Она</button>
      </fieldset>
      <p class="hint"><span class="saved" data-saved>Сохранено</span></p>
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
      if (q.type !== 'profile' && !q.options) ta.focus({ preventScroll: true });
    }

    // Голос
    const mic = document.getElementById('mic');
    if (mic && SpeechRec) {
      mic.addEventListener('click', () => {
        if (recognition) { stopRecognition(); mic.classList.remove('is-rec'); return; }
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
        recognition.onend = () => { recognition = null; mic.classList.remove('is-rec'); };
        recognition.start();
        mic.classList.add('is-rec');
      });
    }

    // Фото главы
    const file = document.getElementById('photo');
    if (file) file.addEventListener('change', async () => {
      const f = file.files[0];
      if (!f) return;
      try {
        const src = await compressImage(f, 1100, 0.72);
        state.photos[chapter.id] = { src, caption: '' };
        if (!save()) delete state.photos[chapter.id];
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

    app.innerHTML = `
    <div class="reader">
      <header class="reader__bar">
        <a class="link-dark" href="${isExample ? '#/' : '#/interview'}">${icon.back} ${isExample ? 'На главную' : 'Вернуться к интервью'}</a>
        <div class="reader__actions">
          ${isExample ? `<a class="btn btn--dark btn--sm" href="#/interview">Создать свою ${icon.arrow}</a>` : `
            <button class="btn btn--ghost-dark btn--sm" id="reset">Начать заново</button>
            <button class="btn btn--dark btn--sm" id="pdf" ${chapters.length ? '' : 'disabled'}>${icon.download} Скачать PDF</button>`}
        </div>
      </header>
      <div class="reader__body">
        <aside class="reader__toc">
          ${chapters.map((x) => `<a href="#ch-${x.c.id}" data-jump="ch-${x.c.id}"><span class="reader__thumb">${x.photo ? `<img src="${x.photo.src}" alt="">` : scene(x.c.scene)}</span>${esc(x.c.title)}</a>`).join('')}
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
        html2canvas: { scale: 2, useCORS: true, backgroundColor: '#fbf8f2' },
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
    document.body.className = '';
    if (m) {
      document.body.classList.add('is-dark');
      if (m[1] === undefined) return go(`#/interview/${firstOpenStep().join('/')}`);
      renderInterview(Number(m[1]), Number(m[2]));
      window.scrollTo(0, 0);
    } else if (hash === '#/book' || hash === '#/example') {
      renderBook(hash === '#/example');
      window.scrollTo(0, 0);
    } else if (hash === '#/' || !hash.startsWith('#/')) {
      // Якоря лендинга (#how, #pricing) прокручиваем, не перерисовывая страницу.
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
