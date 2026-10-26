// Яндекс Метрика: воронка «12 вопросов → предложение → купить».
// Впиши номер счётчика — пока он 0, ничего не загружается и никуда не отправляется.
// Вебвизор выключен намеренно: он записывал бы текст ответов, а это личные истории.
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

  if (METRIKA_ID) {
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

  window.analytics = {
    goal(name) {
      if (ready && GOALS[name]) window.ym(METRIKA_ID, 'reachGoal', GOALS[name]);
    },
  };
})();
