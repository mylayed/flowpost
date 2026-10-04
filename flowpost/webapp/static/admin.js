"use strict";

// The bot owner's Mini App: every connected channel with its plan and limits, and granting limits to one.
const tg = window.Telegram && window.Telegram.WebApp;
const view = document.getElementById("view");

const KIND_LABELS = {
  wm_photo: "Водяні знаки (фото)",
  wm_video: "Водяні знаки (відео)",
  ai_text: "AI-тексти",
  ai_mod: "ШІ-модерація",
};
const KIND_SHORT = { wm_photo: "WM фото", wm_video: "WM відео", ai_text: "AI-тексти", ai_mod: "ШІ-мод." };
const UNLIMITED_QUOTA = 999999;
const ERRORS = {
  forbidden: "Ця панель доступна лише власнику бота.",
  unauthorized: "Відкрийте панель з бота командою /admin.",
  not_found: "Канал не знайдено.",
  invalid_quotas: "Перевірте кількість лімітів.",
  invalid_days: "Перевірте кількість днів.",
  invalid_plan: "Оберіть тариф для днів.",
  nothing_to_grant: "Вкажіть, що нарахувати.",
};

const state = { q: "", items: [], total: 0, offset: 0, loading: false, meta: null, current: null };

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

async function api(path, body) {
  const response = await fetch(`/api/admin/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: `tma ${tg.initData}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || response.statusText), { data });
  return data;
}

function errorText(e) {
  return ERRORS[e.message] || `Помилка: ${e.message}`;
}

function alert(text) {
  return new Promise((resolve) => (tg.showAlert ? tg.showAlert(text, resolve) : (window.alert(text), resolve())));
}

function confirm(text) {
  return new Promise((resolve) => (tg.showConfirm ? tg.showConfirm(text, resolve) : resolve(window.confirm(text))));
}

const fmtDate = (iso) => (iso ? new Date(iso).toLocaleDateString("uk-UA") : "—");
const fmtNum = (n) => (n >= UNLIMITED_QUOTA ? "∞" : String(n));

function planBadge(item) {
  if (item.unlimited) return h("span", { class: "adm-badge unlimited" }, "Безліміт");
  if (item.plan === "paid") return h("span", { class: "adm-badge paid" }, `${item.posts_per_day ?? "?"}/день · ${item.days_left} дн.`);
  if (item.plan === "trial") return h("span", { class: "adm-badge trial" }, `Пробний · ${item.days_left} дн.`);
  if (item.plan === "free") return h("span", { class: "adm-badge" }, "Безкоштовний");
  return h("span", { class: "adm-badge none" }, "Немає");
}

function postsLine(item) {
  if (item.posts_left === null) return "без ліміту";
  const span = item.posts_window === "trial" ? "на пробний" : item.posts_window === "day" ? "на сьогодні" : "";
  return `${item.posts_left} з ${item.posts_limit} ${span}`.trim();
}

function ownerLine(owner) {
  return [owner.name, owner.username ? `@${owner.username}` : null, `id ${owner.tg_id}`].filter(Boolean).join(" · ");
}

function quotaGrid(quotas) {
  return h("div", { class: "adm-quotas" },
    Object.keys(KIND_SHORT).map((kind) =>
      h("div", { class: "adm-q" }, h("b", {}, fmtNum(quotas[kind] ?? 0)), h("span", {}, KIND_SHORT[kind]))));
}

function card(item) {
  return h("button", { class: "adm-card", type: "button", onclick: () => openChannel(item) },
    h("div", { class: "adm-row" },
      h("div", { class: "adm-title" }, item.title),
      planBadge(item)),
    h("div", { class: "adm-sub" }, (item.username ? `@${item.username} · ` : "") + ownerLine(item.owner)),
    h("div", { class: "adm-sub" }, `Пости: ${postsLine(item)}`),
    quotaGrid(item.quotas));
}

// ---- list -----------------------------------------------------------------------------------------------------

let searchTimer = null;

function renderList() {
  state.current = null;
  tg.BackButton?.hide();
  const list = h("div", { class: "adm-list" });
  const search = h("input", {
    class: "adm-search", type: "search", placeholder: "Назва, @username, id каналу чи власника", value: state.q,
    oninput: (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => { state.q = e.target.value.trim(); load(true); }, 350);
    },
  });
  view.replaceChildren(
    h("div", { class: "adm-head" }, h("h1", {}, "Адмін-панель"), h("span", { class: "adm-count", id: "count" }, "")),
    search,
    list,
  );
  paintList();
}

function paintList() {
  const list = view.querySelector(".adm-list");
  const count = document.getElementById("count");
  if (!list) return;
  if (count) count.textContent = `Каналів: ${state.total}`;
  const children = state.items.map(card);
  if (!state.items.length && !state.loading) children.push(h("div", { class: "adm-empty" }, "Нічого не знайдено."));
  if (state.items.length < state.total) {
    children.push(h("button", {
      class: "adm-btn ghost", type: "button", disabled: state.loading, onclick: () => load(false),
    }, state.loading ? "Завантаження…" : "Показати ще"));
  }
  list.replaceChildren(...children);
}

async function load(reset) {
  if (state.loading) return;
  state.loading = true;
  if (reset) { state.items = []; state.offset = 0; }
  paintList();
  try {
    const query = new URLSearchParams({ q: state.q, offset: String(state.items.length) });
    const data = await api(`channels?${query}`);
    state.items = reset ? data.items : state.items.concat(data.items);
    state.total = data.total;
  } catch (e) {
    await alert(errorText(e));
  } finally {
    state.loading = false;
    paintList();
  }
}

// ---- one channel ----------------------------------------------------------------------------------------------

function kv(label, value) {
  return h("div", { class: "adm-kv" }, h("span", {}, label), h("span", {}, value));
}

function planText(item) {
  if (item.unlimited) return "Безліміт (власник бота)";
  if (item.plan === "paid") return `Платний, ${item.posts_per_day ?? "?"} постів/день`;
  return { trial: "Пробний", free: "Безкоштовний" }[item.plan] || "Немає";
}

function openChannel(item) {
  state.current = item;
  tg.BackButton?.show();
  window.scrollTo(0, 0);
  const plans = state.meta?.plans || [];
  const inputs = {};
  const quotaFields = Object.keys(KIND_LABELS).map((kind) => {
    inputs[kind] = h("input", { class: "adm-input", type: "number", min: "0", inputmode: "numeric", placeholder: "0" });
    return h("div", { class: "adm-field" }, h("label", {}, KIND_LABELS[kind]), inputs[kind]);
  });
  const days = h("input", { class: "adm-input", type: "number", min: "0", inputmode: "numeric", placeholder: "0" });
  const defaultPlan = item.sub_posts_per_day ?? plans[0];
  const plan = h("select", { class: "adm-select" },
    plans.map((p) => h("option", { value: String(p), selected: p === defaultPlan }, `${p} постів/день`)));
  const note = h("textarea", { class: "adm-note", maxlength: "500", placeholder: "Напр.: компенсація за збій 03.10" });
  const notify = h("input", { type: "checkbox", checked: true });
  const presets = h("div", { class: "adm-presets" },
    [10, 50, 100, 500].map((n) => h("button", {
      class: "adm-chip", type: "button",
      onclick: () => Object.values(inputs).forEach((input) => { input.value = String(n); }),
    }, `усім +${n}`)),
    h("button", { class: "adm-chip", type: "button", onclick: () => Object.values(inputs).forEach((i) => { i.value = ""; }) }, "очистити"));

  const submit = h("button", { class: "adm-btn", type: "button" }, "Нарахувати");
  submit.addEventListener("click", async () => {
    const quotas = {};
    for (const [kind, input] of Object.entries(inputs)) {
      const n = parseInt(input.value, 10);
      if (n > 0) quotas[kind] = n;
    }
    const nDays = parseInt(days.value, 10) > 0 ? parseInt(days.value, 10) : 0;
    if (!Object.keys(quotas).length && !nDays) { await alert(ERRORS.nothing_to_grant); return; }
    const lines = Object.entries(quotas).map(([k, n]) => `${KIND_LABELS[k]}: +${n}`);
    if (nDays) lines.push(`Тариф ${plan.value} постів/день: +${nDays} дн.`);
    if (!(await confirm(`Нарахувати каналу «${item.title}»?\n\n${lines.join("\n")}`))) return;
    submit.disabled = true;
    try {
      const result = await api("grant", {
        channel_id: item.id, quotas, days: nDays, posts_per_day: nDays ? Number(plan.value) : null,
        note: note.value, notify: notify.checked,
      });
      const index = state.items.findIndex((i) => i.id === item.id);
      if (index >= 0) state.items[index] = result.item;
      await alert(notify.checked
        ? (result.notified ? "Нараховано, власника повідомлено." : "Нараховано, але повідомлення власнику не доставлено.")
        : "Нараховано.");
      openChannel(result.item);
    } catch (e) {
      await alert(errorText(e));
      submit.disabled = false;
    }
  });

  const link = item.username ? `https://t.me/${item.username}` : null;
  view.replaceChildren(
    h("div", { class: "adm-head" }, h("h1", {}, item.title), planBadge(item)),
    h("section", { class: "adm-section" },
      h("h2", {}, "Канал"),
      kv("Тип", item.kind === "group" ? "Група" : "Канал"),
      kv("Посилання", link ? h("a", { class: "link", href: link, onclick: (e) => { e.preventDefault(); tg.openTelegramLink(link); } }, `@${item.username}`) : "приватний"),
      kv("Chat id", String(item.chat_id)),
      kv("Власник", ownerLine(item.owner)),
      kv("Підключено", fmtDate(item.connected_at))),
    h("section", { class: "adm-section" },
      h("h2", {}, "Тариф і пости"),
      kv("Тариф", planText(item)),
      kv("Діє до", item.unlimited ? "—" : fmtDate(item.until)),
      kv("Пробний до", fmtDate(item.trial_ends_at)),
      kv("Залишок постів", postsLine(item))),
    h("section", { class: "adm-section" },
      h("h2", {}, "Ліміти"),
      Object.keys(KIND_LABELS).map((kind) => kv(KIND_LABELS[kind], fmtNum(item.quotas[kind] ?? 0)))),
    h("section", { class: "adm-section" },
      h("h2", {}, "Нарахувати"),
      h("div", { class: "adm-grid" }, quotaFields),
      presets,
      h("div", { class: "adm-grid", style: "margin-top:12px" },
        h("div", { class: "adm-field" }, h("label", {}, "Днів тарифу"), days),
        h("div", { class: "adm-field" }, h("label", {}, "Тариф"), plan)),
      h("div", { class: "adm-field", style: "margin-top:12px" }, h("label", {}, "Коментар для власника (необов'язково)"), note),
      h("label", { class: "adm-check" }, notify, "Повідомити власника в боті")),
    h("div", { class: "adm-actions" },
      submit,
      h("button", { class: "adm-btn ghost", type: "button", onclick: backToList }, "До списку")),
  );
}

function backToList() {
  renderList();
}

// ---- start ----------------------------------------------------------------------------------------------------

async function main() {
  if (!tg || !tg.initData) {
    view.replaceChildren(h("div", { class: "adm-empty" }, ERRORS.unauthorized));
    return;
  }
  tg.ready();
  tg.expand();
  tg.BackButton?.onClick(backToList);
  try {
    state.meta = await api("meta");
  } catch (e) {
    view.replaceChildren(h("div", { class: "adm-empty" }, errorText(e)));
    return;
  }
  renderList();
  load(true);
}

main();
