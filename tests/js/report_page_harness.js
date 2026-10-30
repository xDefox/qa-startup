// Мини-DOM + исполнитель скрипта страницы отчёта.
//
// Зачем: баг «нажал скачать — пропала таблица» нельзя поймать статической
// проверкой разметки, он живёт в обработчике кликов. Здесь настоящая страница
// парсится, её скрипт исполняется, а тест проверяет, что клик по кнопке
// сохранения не меняет вид находок.
//
// stdin: { "html": "<страница целиком>" }
// stdout: { "ok": true, ... } либо { "ok": false, "error": "..." }

const fs = require("fs");
const vm = require("vm");

const VOID = new Set([
  "area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr", "path", "circle", "rect", "line", "polyline",
]);

function parseAttributes(text) {
  const attrs = {};
  const re = /([^\s=/]+)(?:\s*=\s*"([^"]*)"|\s*=\s*'([^']*)'|(?=\s|$))/g;
  let match;
  while ((match = re.exec(text)) !== null) {
    const value = match[2] !== undefined ? match[2] : match[3] !== undefined ? match[3] : "";
    attrs[match[1].toLowerCase()] = value;
  }
  return attrs;
}

function parseHtml(html) {
  const root = { tag: "#root", attrs: {}, children: [], parent: null };
  const stack = [root];
  const re = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w:-]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  let match;
  while ((match = re.exec(html)) !== null) {
    if (match[0].startsWith("<!--")) continue;
    const closing = match[1];
    const tag = match[2].toLowerCase();
    if (closing) {
      for (let i = stack.length - 1; i > 0; i -= 1) {
        if (stack[i].tag === tag) {
          stack.length = i;
          break;
        }
      }
      continue;
    }
    const node = { tag, attrs: parseAttributes(match[3]), children: [], parent: stack[stack.length - 1] };
    node.parent.children.push(node);
    if (!match[4] && !VOID.has(tag)) stack.push(node);
  }
  return root;
}

// --- разбор тех селекторов, что реально встречаются в скриптах страницы ---

function matches(node, part) {
  const attrMatch = /^([\w-]*)((?:[.#][\w-]+)*)(?:\[([\w-]+)\])?$/.exec(part);
  if (!attrMatch) return false;
  const [, tag, classPart, attr] = attrMatch;
  if (tag && node.tag !== tag) return false;
  if (attr && !(attr in node.attrs)) return false;
  const classes = (node.attrs.class || "").split(/\s+/).filter(Boolean);
  for (const cls of (classPart || "").split(/[.#]/).filter(Boolean)) {
    if (classPart.startsWith(".") || classPart.includes(".")) {
      if (!classes.includes(cls)) return false;
    } else if (node.attrs.id !== cls) {
      return false;
    }
  }
  return true;
}

function queryAll(root, selector) {
  const parts = selector.trim().split(/\s+/);
  let current = [root];
  for (const part of parts) {
    const found = [];
    for (const base of current) {
      const walk = (node) => {
        for (const child of node.children) {
          if (matches(child, part)) found.push(child);
          walk(child);
        }
      };
      walk(base);
    }
    current = found;
  }
  return current;
}

// --- обёртки над узлами: только то, чем пользуются скрипты страницы ---

function makeWrapper(raw, focused) {
  const listeners = {};
  const wrapper = {
    raw,
    tag: raw.tag,
    attrs: raw.attrs,
    dataset: {},
    style: {},
    hidden: "hidden" in raw.attrs,
    classList: {
      add() {},
      remove() {},
      toggle() {},
      contains: (name) => (raw.attrs.class || "").split(/\s+/).includes(name),
    },
    setAttribute(key, value) {
      this.attrs[key] = String(value);
    },
    getAttribute(key) {
      return this.attrs[key];
    },
    removeAttribute(key) {
      delete this.attrs[key];
    },
    addEventListener(type, fn) {
      (listeners[type] = listeners[type] || []).push(fn);
    },
    removeEventListener() {},
    dispatch(type, event) {
      (listeners[type] || []).forEach((fn) => fn(event || {}));
    },
    hasListener(type) {
      return Boolean((listeners[type] || []).length);
    },
    contains(other) {
      let cursor = other;
      while (cursor) {
        if (cursor === this) return true;
        cursor = cursor.parent;
      }
      return false;
    },
    closest(selector) {
      let cursor = this;
      while (cursor) {
        if (cursor.raw && matches(cursor.raw, selector)) return cursor;
        cursor = cursor.parent;
      }
      return null;
    },
    focus() {
      focused.push(this);
    },
    blur() {},
    getBoundingClientRect() {
      return { top: 100, bottom: 138, left: 800, right: 838, width: 38, height: 38 };
    },
    get value() {
      return this.attrs.value || "";
    },
    set value(next) {
      this.attrs.value = String(next);
    },
    querySelectorAll(selector) {
      return queryAll(raw, selector).map((item) => item.wrapper).filter(Boolean);
    },
    querySelector(selector) {
      return this.querySelectorAll(selector)[0] || null;
    },
    submit() {},
  };
  for (const [key, value] of Object.entries(raw.attrs)) {
    if (key.startsWith("data-")) {
      wrapper.dataset[key.slice(5).replace(/-([a-z])/g, (_, ch) => ch.toUpperCase())] = value;
    }
  }
  return wrapper;
}

function buildTree(root) {
  const focused = [];
  const wrappers = [];

  const visit = (raw, parentWrapper) => {
    const wrapper = makeWrapper(raw, focused);
    wrapper.parent = parentWrapper;
    raw.wrapper = wrapper;
    wrappers.push(wrapper);
    for (const child of raw.children) visit(child, wrapper);
    return wrapper;
  };

  const top = { tag: "#document", attrs: {}, children: root.children, parent: null };
  visit(top, null);
  return { top, focused, wrappers };
}

function main() {
  const input = JSON.parse(fs.readFileSync(0, "utf8"));
  const parsed = parseHtml(input.html);
  const { focused, wrappers } = buildTree(parsed);

  const documentWrapper = wrappers.find((node) => node.tag === "#document");
  const body = documentWrapper.querySelector("body") || documentWrapper;

  const documentListeners = {};
  const storage = {};
  const documentApi = {
    documentElement: documentWrapper.querySelector("html"),
    body,
    getElementById: (id) => wrappers.find((node) => node.attrs.id === id) || null,
    querySelectorAll: (selector) => documentWrapper.querySelectorAll(selector),
    querySelector: (selector) => documentWrapper.querySelector(selector),
    createElement: (tag) => makeWrapper({ tag, attrs: {}, children: [] }, focused),
    addEventListener(type, fn) {
      (documentListeners[type] = documentListeners[type] || []).push(fn);
    },
    removeEventListener() {},
    dispatch(type, event) {
      (documentListeners[type] || []).forEach((fn) => fn(event));
    },
  };

  const scripts = [];
  const scriptRe = /<script>([\s\S]*?)<\/script>/g;
  let match;
  while ((match = scriptRe.exec(input.html)) !== null) {
    if (match[1].includes("setFindingsView")) scripts.push(match[1]);
  }
  if (scripts.length === 0) throw new Error("на странице нет скрипта переключения вида");

  const sandbox = {
    document: documentApi,
    window: {
      location: { href: "", assign(value) { this.href = value; } },
      innerWidth: 1200,
      innerHeight: 900,
      matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
      addEventListener() {},
      removeEventListener() {},
      scrollTo() {},
    },
    localStorage: {
      getItem: (key) => (key in storage ? storage[key] : null),
      setItem: (key, value) => {
        storage[key] = String(value);
      },
      removeItem: (key) => {
        delete storage[key];
      },
    },
    setTimeout: () => 0,
    clearTimeout: () => {},
    setInterval: () => 0,
    clearInterval: () => {},
    fetch: () => Promise.resolve({ ok: true, json: () => Promise.resolve({}) }),
    console,
  };
  sandbox.globalThis = sandbox;

  for (const code of scripts) {
    vm.createContext(sandbox);
    vm.runInContext(code, sandbox, { filename: "site-inline.js" });
  }

  const panels = documentApi.querySelectorAll(".findings-view");
  const toggles = documentApi.querySelectorAll(".view-toggle .view-btn");
  const downloadBtn = documentApi.getElementById("download-open");
  const pop = documentApi.getElementById("download-pop");
  if (!downloadBtn) throw new Error("на странице нет кнопки #download-open");
  if (!pop) throw new Error("на странице нет панели #download-pop");

  const visible = () => panels.filter((panel) => !panel.hidden).map((panel) => panel.dataset.mode);

  const result = {
    panels: panels.length,
    toggles: toggles.length,
    downloadButtonHasViewHandler: downloadBtn.hasListener("click") === false ? false : undefined,
    initialVisible: visible(),
  };

  // 1. Клик по «сохранить» открывает панель и не меняет вид находок.
  downloadBtn.dispatch("click", { target: downloadBtn });
  result.popOpened = pop.hidden === false;
  result.afterDownloadClick = visible();

  const toggleList = toggles.find((btn) => btn.dataset.view === "list");
  const toggleTable = toggles.find((btn) => btn.dataset.view === "table");
  if (!toggleList || !toggleTable) throw new Error("не найдены кнопки переключения вида");

  // 2. Переключатель вида работает как раньше.
  toggleTable.dispatch("click", { target: toggleTable });
  result.afterTableToggle = visible();
  toggleList.dispatch("click", { target: toggleList });
  result.afterListToggle = visible();

  // 3. И на таблице клик по «сохранить» тоже ничего не прячет.
  toggleTable.dispatch("click", { target: toggleTable });
  downloadBtn.dispatch("click", { target: downloadBtn });
  result.afterDownloadClickOnTable = visible();

  // 4. Esc закрывает панель и возвращает фокус на кнопку.
  documentApi.dispatch("keydown", { key: "Escape" });
  result.popClosedByEscape = pop.hidden === true;
  result.focusReturned = focused[focused.length - 1] === downloadBtn;

  // 5. Имя файла: ссылки получают filename и правильное расширение.
  const nameInput = documentApi.getElementById("download-name");
  const links = pop.querySelectorAll("a[download]");
  if (!nameInput) throw new Error("в панели нет поля #download-name");
  result.defaultName = nameInput.value;

  nameInput.value = "мой отчёт за октябрь";
  nameInput.dispatch("input", { target: nameInput });
  result.namedHrefs = links.map((link) => link.getAttribute("href"));
  result.namedDownload = links.map((link) => link.getAttribute("download"));
  result.duplicateSuffix = links.map((link) => (link.getAttribute("href").match(/filename=/g) || []).length);

  // путь и перевод строки не должны попадать в ссылку
  nameInput.value = "../../etc/passwd";
  nameInput.dispatch("input", { target: nameInput });
  result.traversalHref = links[0].getAttribute("href");
  nameInput.value = "a\r\nSet-Cookie: x";
  nameInput.dispatch("input", { target: nameInput });
  result.injectionHref = links[0].getAttribute("href");

  // пустое имя — возвращаемся к имени по умолчанию на сервере
  nameInput.value = "   ";
  nameInput.dispatch("input", { target: nameInput });
  result.emptyHref = links[0].getAttribute("href");

  result.nameChecks = {
    defaultIsNotEmpty: Boolean(result.defaultName),
    nameApplied: result.namedHrefs.every((href) => href.includes("filename=")),
    extMatches: result.namedDownload[0].endsWith(".html") && result.namedDownload[4].endsWith(".sarif"),
    noDoubleFilename: result.duplicateSuffix.every((count) => count === 1),
    noTraversal: !result.traversalHref.includes(".."),
    noInjection: !result.injectionHref.includes("%0D") && !result.injectionHref.includes("%0A"),
    emptyFallsBack: result.emptyHref === "/api/sites/1/report.html?download=1",
  };

  result.ok =
    result.panels === 2 &&
    result.toggles === 2 &&
    JSON.stringify(result.initialVisible) === '["list"]' &&
    JSON.stringify(result.afterDownloadClick) === '["list"]' &&
    JSON.stringify(result.afterTableToggle) === '["table"]' &&
    JSON.stringify(result.afterListToggle) === '["list"]' &&
    JSON.stringify(result.afterDownloadClickOnTable) === '["table"]' &&
    result.popOpened === true &&
    result.popClosedByEscape === true &&
    result.focusReturned === true &&
    Boolean(result.defaultName) &&
    result.namedHrefs.every((href) => href.includes("filename=")) &&
    result.namedHrefs.every((href) => href.includes(encodeURIComponent("мой отчёт за октябрь"))) &&
    result.namedDownload[0].endsWith(".html") &&
    result.namedDownload[4].endsWith(".sarif") &&
    result.duplicateSuffix.every((count) => count === 1) &&
    !result.traversalHref.includes("..") &&
    !result.injectionHref.includes("%0D") &&
    !result.injectionHref.includes("%0A") &&
    result.emptyHref === "/api/sites/1/report.html?download=1";

  process.stdout.write(JSON.stringify(result));
}

try {
  main();
} catch (error) {
  process.stdout.write(
    JSON.stringify({ ok: false, error: String(error && error.stack ? error.stack : error) }),
  );
  process.exitCode = 1;
}
