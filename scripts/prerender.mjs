// Вставляет готовую разметку лендинга в web/index.html, чтобы поисковики видели текст без JS.
// Запуск: node scripts/prerender.mjs  (после любых правок лендинга в web/js/app.js)
import { readFileSync, writeFileSync } from 'node:fs';
import vm from 'node:vm';

const root = new URL('../web/', import.meta.url);
const read = (p) => readFileSync(new URL(p, root), 'utf8');

const stub = () => ({
  classList: { toggle() {}, add() {}, remove() {} },
  dataset: {},
  addEventListener() {},
  setAttribute() {},
  focus() {},
  querySelector: () => null,
  querySelectorAll: () => [],
});
const appEl = { ...stub(), innerHTML: '', dataset: { prerendered: '1' } };

const ctx = {
  console,
  setTimeout,
  clearTimeout,
  location: { hash: '', search: '' },
  URLSearchParams,
  document: {
    title: '',
    getElementById: (id) => (id === 'app' ? appEl : stub()),
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: stub,
    body: stub(),
  },
  fetch: async () => ({
    ok: true,
    json: async () => ({ exists: false, paid: false, data: null, ai: {}, photos: {}, features: { ai: true, payments: true, price: '1490.00' } }),
  }),
};
ctx.window = { ...ctx, addEventListener() {}, scrollTo() {} };
Object.assign(ctx, { addEventListener() {}, scrollTo() {} });
vm.createContext(ctx);
for (const file of ['js/questions.js', 'js/followups.js', 'js/example.js', 'js/app.js']) {
  vm.runInContext(read(file).replaceAll('window.', 'globalThis.window.'), ctx, { filename: file });
}
await new Promise((r) => setTimeout(r, 50));

if (!appEl.innerHTML.includes('class="hero"')) throw new Error('landing did not render');
const html = read('index.html').replace(
  /<!--PRERENDER-->[\s\S]*?<!--\/PRERENDER-->/,
  `<!--PRERENDER-->${appEl.innerHTML.trim()}<!--/PRERENDER-->`,
);
writeFileSync(new URL('index.html', root), html);
console.log(`prerendered ${appEl.innerHTML.length} chars`);
