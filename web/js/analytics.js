// Яндекс Метрика: воронка «12 вопросов → предложение → купить».
// Впиши номер счётчика — пока он 0, ничего не загружается и никуда не отправляется.
// Вебвизор выключен намеренно: он записывал бы текст ответов, а это личные истории.
// Метрика запускается только после «Принять» на плашке cookie; выбор хранится в этом браузере.
(() => {
  'use strict';

  const METRIKA_ID = 0;

  // Цели воронки. В Метрике заведи цели типа «JavaScript-событие» с этими идентификаторами.
  const GOALS = {
    free_finished: 'free_finished', // дошёл до конца 12 бесплатных вопросов
    offer_view: 'offer_view',       // открыл предложение полной книги
    buy_click: 'buy_click',         // нажал «Открыть полную версию» (купить)
  };

  let ready = false;

  const CONSENT_KEY = 'ms_cookies'; // 'all' — со статистикой, 'necessary' — только нужные для работы

  function savedConsent() {
    try { return localStorage.getItem(CONSENT_KEY); } catch (e) { return null; }
  }

  function saveConsent(value) {
    try { localStorage.setItem(CONSENT_KEY, value); } catch (e) { /* приватный режим: спросим снова */ }
  }

  function startMetrika() {
    if (!METRIKA_ID || ready) return;
    /* eslint-disable */
    (function (m, e, t, r, i, k, a) {
      m[i] = m[i] || function () { (m[i].a = m[i].a || []).push(arguments); };
      m[i].l = 1 * new Date();
      for (let j = 0; j < e.scripts.length; j++) { if (e.scripts[j].src === r) return; }
      k = e.createElement(t); a = e.getElementsByTagName(t)[0]; k.async = 1; k.src = r; a.parentNode.insertBefore(k, a);
    })(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');
    /* eslint-enable */
    window.ym(METRIKA_ID, 'init', { clickmap: true, trackLinks: true, accurateTrackBounce: true, trackHash: true, webvisor: false });
    ready = true;
  }

  function showCookieBar() {
    if (document.querySelector('.cookie')) return;
    const bar = document.createElement('section');
    bar.className = 'cookie';
    bar.setAttribute('aria-label', 'Cookie');
    bar.innerHTML = `
      <p>Cookie сохраняют твою книгу в этом браузере, а с твоего согласия — помогают считать посещения. <a href="/privacy.html#cookies">Подробнее</a></p>
      <div class="cookie__actions">
        <button type="button" class="btn btn--dark btn--sm" data-consent="all">Принять</button>
        <button type="button" class="btn btn--ghost btn--sm" data-consent="necessary">Только нужные</button>
      </div>`;
    bar.addEventListener('click', (e) => {
      const button = e.target.closest('[data-consent]');
      if (!button) return;
      const choice = button.dataset.consent;
      saveConsent(choice);
      bar.remove();
      if (choice === 'all') startMetrika();
      else if (ready) location.reload(); // отозвал согласие — выгружаем уже запущенный счётчик
    });
    document.body.append(bar);
  }

  if (savedConsent() === 'all') startMetrika();
  else if (!savedConsent()) setTimeout(showCookieBar, 900); // не перебиваем первый экран

  // Кнопка «Cookie» в подвале: передумать можно в любой момент.
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-cookie-settings]')) showCookieBar();
  });

  window.analytics = {
    goal(name) {
      if (ready && GOALS[name]) window.ym(METRIKA_ID, 'reachGoal', GOALS[name]);
    },
  };
})();
