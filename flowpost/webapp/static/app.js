"use strict";

const tg = window.Telegram && window.Telegram.WebApp;
const view = document.getElementById("view");
const footer = document.getElementById("footer");
const langSelect = document.getElementById("lang");
const currencyButtons = document.querySelectorAll("[data-currency]");

const I18N = {
  uk: {
    balance: "Баланс",
    total_balance: "Загальний баланс",
    cashback: "Кешбек",
    top_up: "Поповнити",
    subscriptions: "Підписки",
    subscribe: "Оформити / Продовжити",
    limits: "Поповнити ліміти",
    align: "Вирівняти підписки",
    transfer: "Перенести підписку",
    plans: "Тарифи",
    my_channels: "Мої канали",
    no_channels: "Каналів немає.",
    renew_soon: "Час продовжити",
    renew_all: "Продовжити підписки",
    days_short: "{n} дн.",
    expired: "Закінчилась",
    channel_title: "Канал",
    open_in_tg: "Відкрити в Telegram",
    status: "Статус",
    status_active: "Активний",
    status_inactive: "Неактивний",
    plan: "Тариф",
    plan_trial: "Пробний",
    plan_paid: "Платний",
    plan_none: "Немає",
    plan_free: "Безкоштовний",
    status_free: "Безкоштовний тариф",
    posts_unlimited: "без ліміту",
    posts_left_day: "{left} з {limit} на сьогодні",
    posts_left_trial: "{left} з {limit} на пробний період",
    posts_left_label: "Залишок постів",
    expires: "Спливає",
    valid_until: "Діє до",
    renew_subscription: "Продовжити підписку",
    sub_title: "Підписка на постинг",
    sub_hint: "Оберіть канали, на які оформити підписку.",
    cat_renew: "Час продовжити",
    cat_none: "Без підписки",
    cat_ok: "Все гаразд",
    selected_count: "Обрано каналів: {n}",
    select_all: "Вибрати всі",
    clear_selection: "Зняти вибір",
    no_filtered: "Немає каналів у вибраних категоріях.",
    limits_title: "Ліміти проєкту",
    limits_hint: "Докупіть водяні знаки та AI-тексти для проєкту, якщо основні ліміти закінчилися. Що більший пакет, то вигідніша ціна.",
    project: "Проєкт",
    remaining: "Поточний залишок",
    kind_wm_photo: "Водяні знаки (фото)",
    kind_wm_video: "Водяні знаки (відео)",
    kind_ai_text: "AI-тексти",
    quotas: "Квоти",
    total_due: "До сплати",
    go_to_payment: "Перейти до оплати",
    checkout_limits: "Ліміти",
    pay_balance: "Оплатити з балансу",
    not_enough: "На балансі {balance} ⭐, не вистачає {missing} ⭐.",
    topup_missing: "Поповнити на {missing} ⭐",
    limits_done: "Ліміти поповнено!",
    w_posts: ["пост", "пости", "постів"],
    w_days: ["день", "дні", "днів"],
    w_channels_from: ["каналу", "каналів", "каналів"],
    day_unit: "день",
    per_day: "на день",
    from: "від",
    plans_title: "Тарифи",
    posting_header: "Постинг · ціна за 30 днів · канал",
    wm_line: "Водяні знаки: {photo} фото · {video} відео",
    show_all_plans: "Показати всі тарифи ({n})",
    subscribe_btn: "Оформити підписку",
    calc_link: "Розрахувати вартість підписки",
    free_header: "Безкоштовно і пробний період",
    trial_title: "Пробний період",
    trial_auto: "Вмикається сам, коли підключаєте канал",
    trial_quotas: "Водяні знаки: {photo} фото · {video} відео · AI-тексти: {ai}",
    free_title: "Безкоштовний тариф",
    free_scope: "На канал і на акаунт; ліміт оновлюється раз на добу",
    free_no_multi: "Без мультипостингу та автоповторів",
    free_no_extras: "Водяні знаки та AI недоступні",
    free_note: "Умови безкоштовного та пробного тарифів можуть змінюватися, зокрема індивідуально.",
    discounts_header: "Знижки",
    disc_channels: "За канали",
    disc_channels_text: "Знижка до −{max}%: що більше каналів, то більша.",
    more: "Детальніше",
    less: "Згорнути",
    disc_term: "За строк",
    packs_header: "Додаткові пакети",
    pack_wm_photo: "Знаки фото",
    pack_wm_video: "Знаки відео",
    pack_ai_text: "AI-тексти",
    rate_note: "Довідково: {stars} ⭐ ≈ $1",
    calc_header: "Калькулятор підписки",
    calc_channels: "Канали",
    calc_posts: "Постів на день",
    calc_term: "Строк, днів",
    calc_posts_month: "Постів / місяць · на канал",
    calc_wm: "Водяні знаки · фото / відео",
    calc_base: "Базова ціна",
    calc_disc_channels: "Знижка за канали",
    calc_disc_term: "Знижка за строк",
    calc_total: "Разом",
    per_month: "/ місяць",
    for_30: "за 30 днів · ≈ {usd}",
    for_days: "{stars} Stars за {days} днів · ≈ {usd}",
    transfer_title: "Перенесення підписки",
    transfer_hint: "Переносить платну підписку з одного каналу на інший разом із тарифом, строком дії та додатковими пакетами. Безкоштовно.",
    transfer_empty: "Немає каналів із підпискою, яку можна перенести.",
    transfer_no_targets: "Немає каналу, на який можна перенести підписку: усі інші канали вже мають активну підписку.",
    transfer_from: "З каналу",
    transfer_to: "На канал",
    transfer_packs: "Додаткові пакети",
    transfer_warning: "Після перенесення канал «{title}» залишиться без платної підписки.",
    transfer_btn: "Перенести підписку",
    transfer_confirm: "Перенести підписку з «{from}» на «{to}»?",
    transfer_done: "Підписку перенесено на «{title}».",
    topup_title: "Поповнення",
    topup_hint: "Поповніть баланс один раз, а потім оплачуйте й продовжуйте підписки прямо з нього.",
    topup_amount: "Сума у Stars",
    topup_cashback: "+{percent}% кешбеку з кожного поповнення",
    continue: "Продовжити",
    checkout_title: "Оплата",
    checkout_topup: "Поповнення",
    to_pay: "До сплати",
    accept_prefix: "Я приймаю ",
    terms_link: "умови використання",
    accept_and: " і ",
    privacy_link: "політику конфіденційності",
    accept_suffix: ".",
    pay_stars: "Оплатити Stars",
    terms_title: "Умови використання",
    soon: "Цей розділ скоро з'явиться.",
    paid: "Оплату отримано! Баланс оновиться за кілька секунд.",
    failed: "Оплата не пройшла. Спробуйте ще раз.",
    invalid_amount: "Введіть цілу суму від {min} до {max} Stars.",
    error: "Щось пішло не так. Спробуйте ще раз.",
    open_in_telegram: "Відкрийте цю сторінку через бота в Telegram.",
  },
  en: {
    balance: "Balance",
    total_balance: "Total balance",
    cashback: "Cashback",
    top_up: "Top up",
    subscriptions: "Subscriptions",
    subscribe: "Subscribe / Renew",
    limits: "Top up limits",
    align: "Align subscriptions",
    transfer: "Transfer subscription",
    plans: "Plans",
    my_channels: "My channels",
    no_channels: "No channels yet.",
    renew_soon: "Time to renew",
    renew_all: "Renew subscriptions",
    days_short: "{n} d.",
    expired: "Expired",
    channel_title: "Channel",
    open_in_tg: "Open in Telegram",
    status: "Status",
    status_active: "Active",
    status_inactive: "Inactive",
    plan: "Plan",
    plan_trial: "Trial",
    plan_paid: "Paid",
    plan_none: "None",
    plan_free: "Free",
    status_free: "Free plan",
    posts_unlimited: "unlimited",
    posts_left_day: "{left} of {limit} today",
    posts_left_trial: "{left} of {limit} for the trial",
    posts_left_label: "Posts left",
    expires: "Expires in",
    valid_until: "Valid until",
    renew_subscription: "Renew subscription",
    sub_title: "Posting subscription",
    sub_hint: "Choose the channels you want to subscribe.",
    cat_renew: "Time to renew",
    cat_none: "No subscription",
    cat_ok: "All good",
    selected_count: "Selected channels: {n}",
    select_all: "Select all",
    clear_selection: "Clear selection",
    no_filtered: "No channels in the selected categories.",
    limits_title: "Project limits",
    limits_hint: "Buy extra watermarks and AI texts for a project once the plan limits run out. The bigger the pack, the better the price.",
    project: "Project",
    remaining: "Current balance",
    kind_wm_photo: "Watermarks (photo)",
    kind_wm_video: "Watermarks (video)",
    kind_ai_text: "AI texts",
    quotas: "Quotas",
    total_due: "Amount due",
    go_to_payment: "Proceed to payment",
    checkout_limits: "Limits",
    pay_balance: "Pay from balance",
    not_enough: "Your balance is {balance} ⭐, {missing} ⭐ short.",
    topup_missing: "Top up {missing} ⭐",
    limits_done: "Limits topped up!",
    w_posts: ["post", "posts"],
    w_days: ["day", "days"],
    w_channels_from: ["channel", "channels"],
    day_unit: "day",
    per_day: "per day",
    from: "from",
    plans_title: "Plans",
    posting_header: "Posting · price per 30 days · channel",
    wm_line: "Watermarks: {photo} photo · {video} video",
    show_all_plans: "Show all plans ({n})",
    subscribe_btn: "Subscribe",
    calc_link: "Calculate subscription cost",
    free_header: "Free and trial",
    trial_title: "Free trial",
    trial_auto: "Starts automatically when you connect a channel",
    trial_quotas: "Watermarks: {photo} photo · {video} video · AI texts: {ai}",
    free_title: "Free plan",
    free_scope: "Per channel and per account; the limit resets once a day",
    free_no_multi: "No multiposting or auto-repeats",
    free_no_extras: "Watermarks and AI are not available",
    free_note: "Free and trial terms may change, including on an individual basis.",
    discounts_header: "Discounts",
    disc_channels: "By channels",
    disc_channels_text: "Up to −{max}%: the more channels, the bigger the discount.",
    more: "Details",
    less: "Hide",
    disc_term: "By term",
    packs_header: "Extra packs",
    pack_wm_photo: "Photo marks",
    pack_wm_video: "Video marks",
    pack_ai_text: "AI texts",
    rate_note: "For reference: {stars} ⭐ ≈ $1",
    calc_header: "Subscription calculator",
    calc_channels: "Channels",
    calc_posts: "Posts per day",
    calc_term: "Term, days",
    calc_posts_month: "Posts / month · per channel",
    calc_wm: "Watermarks · photo / video",
    calc_base: "Base price",
    calc_disc_channels: "Channel discount",
    calc_disc_term: "Term discount",
    calc_total: "Total",
    per_month: "/ month",
    for_30: "for 30 days · ≈ {usd}",
    for_days: "{stars} Stars for {days} days · ≈ {usd}",
    transfer_title: "Transfer subscription",
    transfer_hint: "Moves a paid subscription from one channel to another together with its plan, validity and extra packs. Free of charge.",
    transfer_empty: "No channels with a subscription that can be transferred.",
    transfer_no_targets: "There is no channel to transfer to: all your other channels already have an active subscription.",
    transfer_from: "From channel",
    transfer_to: "To channel",
    transfer_packs: "Extra packs",
    transfer_warning: "After the transfer «{title}» will be left without a paid subscription.",
    transfer_btn: "Transfer subscription",
    transfer_confirm: "Transfer the subscription from «{from}» to «{to}»?",
    transfer_done: "Subscription transferred to «{title}».",
    topup_title: "Top up",
    topup_hint: "Top up your balance once, then pay for and renew subscriptions straight from it.",
    topup_amount: "Amount in Stars",
    topup_cashback: "+{percent}% cashback on every top-up",
    continue: "Continue",
    checkout_title: "Payment",
    checkout_topup: "Top-up",
    to_pay: "Amount due",
    accept_prefix: "I accept the ",
    terms_link: "terms of use",
    accept_and: " and ",
    privacy_link: "privacy policy",
    accept_suffix: ".",
    pay_stars: "Pay with Stars",
    terms_title: "Terms of use",
    soon: "This section is coming soon.",
    paid: "Payment received! Your balance will update in a few seconds.",
    failed: "The payment didn't go through. Please try again.",
    invalid_amount: "Enter a whole amount from {min} to {max} Stars.",
    error: "Something went wrong. Please try again.",
    open_in_telegram: "Open this page from the bot in Telegram.",
  },
};

const ICONS = {
  send: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  sliders: '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
  swap: '<path d="m17 3 4 4-4 4"/><path d="M3 7h18"/><path d="m7 21-4-4 4-4"/><path d="M21 17H3"/>',
  tag: '<path d="M20.6 13.4 13.4 20.6a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z"/><circle cx="7" cy="7" r="1.5"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  chevron: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
};

const state = {
  me: null,
  lang: "uk",
  currency: loadPref("currency", "stars"),
  topupDraft: "",
  checkout: null,
  subscribe: null,
  limits: null,
  plansUi: null,
  calc: null,
  transfer: null,
};

function loadPref(key, fallback) {
  try {
    return localStorage.getItem(`fp.${key}`) || fallback;
  } catch {
    return fallback;
  }
}

function savePref(key, value) {
  try {
    localStorage.setItem(`fp.${key}`, value);
  } catch {}
}

function t(key, params = {}) {
  const text = (I18N[state.lang] || I18N.uk)[key] ?? I18N.uk[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, name) => params[name] ?? "");
}

function number(n) {
  return new Intl.NumberFormat(state.lang === "en" ? "en-US" : "uk-UA").format(n);
}

function usdAmount(dollars) {
  return `$${dollars.toFixed(2)}`;
}

function usd(stars) {
  return usdAmount(stars * state.me.usd_rate);
}

function word(key, n) {
  const forms = (I18N[state.lang] || I18N.uk)[key];
  if (forms.length === 2) return n === 1 ? forms[0] : forms[1];
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return forms[0];
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return forms[1];
  return forms[2];
}

function money(stars) {
  return state.currency === "usd" ? usd(stars) : `${number(stars)} ⭐`;
}

function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function icon(name, extraClass = "") {
  const span = document.createElement("span");
  span.className = `icon ${extraClass}`.trim();
  span.innerHTML =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    `stroke-linecap="round" stroke-linejoin="round">${ICONS[name]}</svg>`;
  return span;
}

async function api(path, body) {
  const response = await fetch(`/api/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers: {
      Authorization: `tma ${tg.initData}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(data.error || response.statusText), { status: response.status });
  return data;
}

async function loadMe() {
  state.me = await api("me");
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function soon() {
  tg.showAlert(t("soon"));
}

function menuItem(iconName, label, onClick) {
  return h("button", { class: "menu-item", type: "button", onclick: onClick },
    icon(iconName), h("span", { class: "grow" }, label), icon("chevron", "chev"));
}

function initial(title) {
  return (Array.from(title.trim())[0] || "#").toUpperCase();
}

function renderRenewSoon(me) {
  const expiring = me.channels
    .filter((c) => c.days_left <= me.renew_soon_days)
    .sort((a, b) => a.days_left - b.days_left);
  if (!expiring.length) return [];
  return [
    h("div", { class: "section-label" }, t("renew_soon"), h("span", { class: "count" }, ` · ${expiring.length}`)),
    h("section", { class: "renew-card" },
      expiring.map((c) =>
        h("button", { class: "renew-row", type: "button", onclick: () => go(`channel/${c.id}`) },
          h("span", { class: "avatar" }, initial(c.title)),
          h("span", { class: "grow" }, c.title),
          daysLabel(c),
          icon("chevron", "chev"))),
      h("button", { class: "renew-all", type: "button", onclick: () => openSubscribe(expiring.map((c) => c.id)) },
        t("renew_all"), h("span", {}, "→"))),
  ];
}

function renderHome() {
  const me = state.me;
  return [
    h("h1", { class: "title" }, t("balance")),
    h("section", { class: "balance-card" },
      h("div", { class: "balance-top" },
        h("div", {},
          h("div", { class: "label-light" }, t("total_balance")),
          h("div", { class: "balance-amount" }, money(me.balance))),
        h("div", { class: "cashback" },
          h("div", { class: "label-light" }, t("cashback")),
          h("div", { class: "cashback-amount" }, money(me.cashback)))),
      h("button", { class: "btn btn-light", type: "button", onclick: () => go("topup") }, t("top_up"))),
    renderRenewSoon(me),
    h("div", { class: "section-label" }, t("subscriptions")),
    h("div", { class: "menu" },
      menuItem("send", t("subscribe"), () => openSubscribe()),
      menuItem("layers", t("limits"), () => openLimits()),
      menuItem("sliders", t("align"), soon),
      menuItem("swap", t("transfer"), () => go("transfer")),
      menuItem("tag", t("plans"), () => go("plans"))),
    me.channels.length ? null : h("p", { class: "hint" }, t("no_channels")),
    h("div", { class: "menu menu-bottom" }, menuItem("list", t("my_channels"), soon)),
  ];
}

function renderTopup() {
  const { min, max } = state.me.topup;
  const input = h("input", {
    id: "amount", class: "amount-input", type: "number", inputmode: "numeric",
    min, max, step: 1, placeholder: "100", value: state.topupDraft,
  });
  const usdHint = h("span", { class: "amount-usd" });
  const refresh = () => {
    state.topupDraft = input.value;
    const stars = Number(input.value);
    usdHint.textContent = input.value && stars > 0 ? `≈ ${usd(stars)}` : "";
  };
  input.addEventListener("input", refresh);
  refresh();
  return [
    h("h1", { class: "title" }, t("topup_title")),
    h("section", { class: "card" },
      h("p", { class: "hint" }, t("topup_hint")),
      h("label", { class: "field-label", for: "amount" }, t("topup_amount")),
      h("div", { class: "field-sub" }, `${number(min)}–${number(max)}`),
      h("div", { class: "amount-field" }, input, usdHint),
      state.me.cashback_percent > 0
        ? h("p", { class: "hint" }, t("topup_cashback", { percent: state.me.cashback_percent }))
        : null,
      h("button", { class: "btn btn-primary", type: "button", onclick: () => continueTopup(input) }, t("continue"))),
  ];
}

function continueTopup(input) {
  const stars = Number(input.value);
  const { min, max } = state.me.topup;
  if (!Number.isInteger(stars) || stars < min || stars > max) {
    tg.showAlert(t("invalid_amount", { min: number(min), max: number(max) }));
    return;
  }
  state.checkout = { kind: "topup", stars, accepted: false };
  go("checkout");
}

function legalLink(label, url, fallbackRoute) {
  if (!url && !fallbackRoute) return label;
  return h("a", {
    class: "link",
    href: url || `#/${fallbackRoute}`,
    onclick: (event) => {
      event.preventDefault();
      if (url) tg.openLink(url);
      else go(fallbackRoute);
    },
  }, label);
}

function renderCheckout() {
  const checkout = state.checkout;
  const { terms_url, privacy_url } = state.me.legal;
  const fromBalance = checkout.kind !== "topup";
  const head = [
    h("h1", { class: "title title-tight" }, t("checkout_title")),
    h("div", { class: "subtitle" }, t(`checkout_${checkout.kind}`)),
  ];
  const due = [
    h("div", { class: "due-label" }, t("to_pay")),
    h("div", { class: "due-amount" }, `${number(checkout.stars)} ★`),
    h("div", { class: "due-usd" }, `≈ ${usd(checkout.stars)}`),
  ];

  const available = state.me.balance + state.me.cashback;
  if (fromBalance && available < checkout.stars) {
    const missing = checkout.stars - available;
    return [
      ...head,
      h("section", { class: "card" },
        due,
        h("p", { class: "hint shortfall" }, t("not_enough", { balance: number(available), missing: number(missing) })),
        h("button", { class: "btn btn-primary", type: "button", onclick: () => topUpShortfall(missing) },
          t("topup_missing", { missing: number(missing) }))),
    ];
  }

  const pay = h("button", { class: "btn btn-primary", type: "button", disabled: !checkout.accepted },
    t(fromBalance ? "pay_balance" : "pay_stars"));
  const box = h("input", { id: "accept", class: "checkbox", type: "checkbox" });
  box.checked = checkout.accepted;
  box.addEventListener("change", () => {
    checkout.accepted = box.checked;
    pay.disabled = !box.checked;
  });
  pay.addEventListener("click", () => (fromBalance ? payFromBalance(pay) : payCheckout(pay)));
  return [
    ...head,
    h("section", { class: "card" },
      due,
      h("div", { class: "consent" },
        box,
        h("label", { for: "accept" },
          t("accept_prefix"),
          legalLink(t("terms_link"), terms_url, "terms"),
          t("accept_and"),
          legalLink(t("privacy_link"), privacy_url),
          t("accept_suffix"))),
      pay),
  ];
}

async function payCheckout(button) {
  const { stars } = state.checkout;
  button.disabled = true;
  try {
    const { link } = await api("topup", { stars });
    tg.openInvoice(link, (status) => {
      if (status === "paid") {
        const resume = state.checkout?.resume || null;
        const before = state.me.balance;
        state.checkout = resume;
        state.topupDraft = "";
        tg.HapticFeedback?.notificationOccurred("success");
        go(resume ? "checkout" : "");
        pollBalance(before);
      } else if (status === "failed") {
        tg.showAlert(t("failed"));
      }
    });
  } catch {
    tg.showAlert(t("error"));
  } finally {
    button.disabled = !state.checkout?.accepted;
  }
}

function renderTerms() {
  const body = h("section", { class: "card terms" });
  api("terms")
    .then(({ html }) => { body.innerHTML = html.replace(/\n/g, "<br>"); })
    .catch(() => { body.textContent = t("error"); });
  return [h("h1", { class: "title" }, t("terms_title")), body];
}

function starsUsd(stars) {
  return `${number(stars)} ⭐ (≈${usd(stars)})`;
}

function limitKinds() {
  return Object.keys(state.me.limit_prices);
}

function openLimits(channelId) {
  state.limits = { channelId: channelId ?? state.me.channels[0]?.id ?? null, packs: {} };
  go("limits");
}

function limitsTotal(packs) {
  return limitKinds().reduce((sum, kind) => sum + (packs[kind] ? state.me.limit_prices[kind][packs[kind]] : 0), 0);
}

function renderLimits() {
  const lim = (state.limits ??= { channelId: state.me.channels[0]?.id ?? null, packs: {} });
  const header = [
    h("h1", { class: "title title-tight" }, t("limits_title")),
    h("div", { class: "subtitle" }, t("limits_hint")),
  ];
  if (!state.me.channels.some((c) => c.id === lim.channelId)) lim.channelId = state.me.channels[0]?.id ?? null;
  if (lim.channelId == null) return [...header, h("section", { class: "card" }, h("p", { class: "hint" }, t("no_channels")))];

  const select = h("select", { id: "project", class: "select" },
    state.me.channels.map((c) => h("option", { value: c.id }, c.title)));
  select.value = String(lim.channelId);
  select.addEventListener("change", () => {
    lim.channelId = Number(select.value);
    render();
  });

  const remainingRows = (remaining) => limitKinds().map((kind) =>
    infoRow(t(`kind_${kind}`), remaining ? number(remaining[kind] ?? 0) : "…"));
  const remainingBox = h("div", { class: "remaining" },
    h("div", { class: "remaining-title" }, t("remaining")), remainingRows(null));
  api(`limits/${lim.channelId}`)
    .then(({ remaining }) => remainingBox.replaceChildren(
      h("div", { class: "remaining-title" }, t("remaining")), ...remainingRows(remaining)))
    .catch(() => {});

  const groups = limitKinds().map((kind) => {
    const prices = state.me.limit_prices[kind];
    const sizes = [0, ...Object.keys(prices).map(Number).sort((a, b) => a - b)];
    const chosen = lim.packs[kind] || 0;
    return h("div", { class: "pack" },
      h("div", { class: "field-label" }, t(`kind_${kind}`)),
      h("div", { class: "segmented", role: "radiogroup" }, sizes.map((size) => {
        let cls = "seg-opt";
        if (size === chosen) cls += size ? " active" : " active zero";
        return h("button", {
          class: cls,
          type: "button",
          role: "radio",
          "aria-checked": String(size === chosen),
          onclick: () => {
            lim.packs[kind] = size;
            render();
          },
        }, String(size));
      })),
      chosen ? h("div", { class: "pack-price" }, starsUsd(prices[chosen])) : null);
  });

  const total = limitsTotal(lim.packs);
  return [
    ...header,
    h("section", { class: "card" },
      h("label", { class: "field-label", for: "project" }, t("project")),
      h("div", { class: "select-wrap" }, select),
      remainingBox,
      groups,
      h("div", { class: "summary" },
        h("div", { class: "summary-row" }, h("span", {}, t("quotas")), h("span", {}, `${number(total)} ⭐`)),
        h("div", { class: "summary-row total" },
          h("span", {}, t("total_due")),
          h("span", {}, `${number(total)} ⭐`, h("small", {}, ` (≈${usd(total)})`)))),
      h("button", {
        class: "btn btn-primary btn-quiet-disabled",
        type: "button",
        disabled: total === 0,
        onclick: () => startLimitsCheckout(total),
      }, t("go_to_payment"))),
  ];
}

function startLimitsCheckout(total) {
  const { channelId, packs } = state.limits;
  state.checkout = { kind: "limits", stars: total, accepted: false, channelId, packs: { ...packs } };
  go("checkout");
}

function topUpShortfall(missing) {
  const { min, max } = state.me.topup;
  const stars = Math.min(Math.max(missing, min), max);
  state.checkout = { kind: "topup", stars, accepted: false, resume: state.checkout };
  go("checkout");
}

async function payFromBalance(button) {
  const { channelId, packs } = state.checkout;
  button.disabled = true;
  try {
    const result = await api("limits", { channel_id: channelId, packs });
    state.me.balance = result.balance;
    state.me.cashback = result.cashback;
    state.checkout = null;
    state.limits = { channelId, packs: {} };
    tg.HapticFeedback?.notificationOccurred("success");
    tg.showAlert(t("limits_done"));
    go("limits");
  } catch (error) {
    if (error.status === 402) {
      await loadMe().catch(() => {});
      render();
      return;
    }
    tg.showAlert(t("error"));
    button.disabled = !state.checkout?.accepted;
  }
}

function planName(postsPerDay) {
  return `${number(postsPerDay)} ${word("w_posts", postsPerDay)}/${t("day_unit")}`;
}

function discountFor(tiers, value) {
  let pct = 0;
  for (const [min, tierPct] of tiers) {
    if (value >= min) pct = Math.max(pct, tierPct);
  }
  return pct;
}

function choiceGroup(values, isActive, onPick) {
  const buttons = values.map((value) =>
    h("button", { class: "seg-opt", type: "button", role: "radio", onclick: () => onPick(value) }, String(value)));
  const group = h("div", {
    class: "segmented calc-seg",
    role: "radiogroup",
    style: `grid-template-columns: repeat(${values.length}, minmax(0, 1fr))`,
  }, buttons);
  group.sync = () => buttons.forEach((button, i) => {
    const active = isActive(values[i]);
    button.classList.toggle("fill", active);
    button.setAttribute("aria-checked", String(active));
  });
  return group;
}

function renderCalculator(p) {
  const calc = (state.calc ??= {
    channels: Math.min(Math.max(state.me.channels.length, 1), p.max_channels),
    posts: p.posting[0].posts_per_day,
    days: p.term_discounts[0][0],
  });
  const channelsValue = h("span", { class: "calc-big" });
  const slider = h("input", {
    class: "range", type: "range", min: 1, max: p.max_channels, step: 1, value: calc.channels,
    "aria-label": t("calc_channels"),
  });
  const out = {
    postsMonth: h("b"), wm: h("b"), base: h("b"), discChannels: h("b"), discTerm: h("b"),
    perMonth: h("span"), sub: h("div", { class: "calc-total-sub" }),
  };
  let postsGroup;
  let daysGroup;

  const update = () => {
    const plan = p.posting.find((x) => x.posts_per_day === calc.posts) || p.posting[0];
    const months = calc.days / 30;
    const channelPct = discountFor(p.channel_discounts, calc.channels);
    const termPct = (p.term_discounts.find(([days]) => days === calc.days) || [0, 0])[1];
    const pct = channelPct + termPct;
    const baseStars = plan.stars * calc.channels * months;
    const totalStars = Math.ceil((baseStars * (100 - pct)) / 100);
    const baseUsd = baseStars * state.me.usd_rate;
    const totalUsd = usdAmount((baseUsd * (100 - pct)) / 100);

    channelsValue.textContent = number(calc.channels);
    slider.style.setProperty("--fill", `${((calc.channels - 1) / Math.max(p.max_channels - 1, 1)) * 100}%`);
    postsGroup.sync();
    daysGroup.sync();
    out.postsMonth.textContent = number(calc.posts * 30);
    out.wm.textContent = `${number(Math.round(plan.wm_photo * months))} / ${number(Math.round(plan.wm_video * months))}`;
    out.base.textContent = usdAmount(baseUsd);
    out.base.className = pct ? "strike" : "";
    out.discChannels.textContent = channelPct ? `−${channelPct}% · −${usdAmount((baseUsd * channelPct) / 100)}` : "—";
    out.discChannels.className = channelPct ? "good" : "";
    out.discTerm.textContent = termPct ? `−${termPct}% · −${usdAmount((baseUsd * termPct) / 100)}` : "—";
    out.discTerm.className = termPct ? "good" : "";
    out.perMonth.textContent = number(Math.ceil(totalStars / months));
    out.sub.textContent = calc.days === 30
      ? t("for_30", { usd: totalUsd })
      : t("for_days", { stars: number(totalStars), days: number(calc.days), usd: totalUsd });
  };

  postsGroup = choiceGroup(p.posting.map((plan) => plan.posts_per_day), (v) => v === calc.posts, (v) => {
    calc.posts = v;
    update();
  });
  daysGroup = choiceGroup(p.term_discounts.map(([days]) => days), (v) => v === calc.days, (v) => {
    calc.days = v;
    update();
  });
  slider.addEventListener("input", () => {
    calc.channels = Number(slider.value);
    update();
  });
  update();

  const row = (label, value) => h("div", { class: "calc-row" }, h("span", {}, label), value);
  return h("section", { class: "card calc-card", id: "calculator" },
    h("div", { class: "card-label" }, t("calc_header")),
    h("div", { class: "calc-head" }, h("span", {}, t("calc_channels")), channelsValue),
    slider,
    h("div", { class: "calc-label" }, t("calc_posts")),
    postsGroup,
    h("div", { class: "calc-label" }, t("calc_term")),
    daysGroup,
    h("div", { class: "calc-rows" },
      row(t("calc_posts_month"), out.postsMonth),
      row(t("calc_wm"), out.wm)),
    h("div", { class: "calc-rows" },
      row(t("calc_base"), out.base),
      row(t("calc_disc_channels"), out.discChannels),
      row(t("calc_disc_term"), out.discTerm)),
    h("div", { class: "calc-total" },
      h("span", { class: "calc-total-label" }, t("calc_total")),
      h("div", { class: "calc-total-value" },
        h("div", { class: "calc-total-stars" }, out.perMonth, " ⭐ ", h("small", {}, t("per_month"))),
        out.sub)));
}

function renderPlans() {
  const p = state.me.plans;
  const ui = (state.plansUi ??= { expanded: false, tiers: false });
  const calculator = renderCalculator(p);
  const rerender = (change) => () => {
    change();
    render();
  };

  const planRows = (ui.expanded ? p.posting : p.posting.slice(0, 2)).map((plan) =>
    h("div", { class: "plan-row" },
      h("div", {},
        h("div", { class: "plan-name" }, planName(plan.posts_per_day)),
        h("div", { class: "plan-sub" }, t("wm_line", { photo: number(plan.wm_photo), video: number(plan.wm_video) }))),
      h("div", { class: "plan-price" },
        h("div", { class: "plan-stars" }, `${number(plan.stars)} ⭐`),
        h("div", { class: "plan-usd" }, `≈ ${usd(plan.stars)}`))));
  const posting = h("section", { class: "card plans-card" },
    h("div", { class: "card-label" }, t("posting_header")),
    h("div", { class: "plan-list" }, planRows),
    ui.expanded || p.posting.length <= 2
      ? null
      : h("button", { class: "text-link", type: "button", onclick: rerender(() => { ui.expanded = true; }) },
        t("show_all_plans", { n: p.posting.length })),
    h("button", { class: "btn btn-primary", type: "button", onclick: () => openSubscribe() }, t("subscribe_btn")),
    h("button", {
      class: "text-link",
      type: "button",
      onclick: () => calculator.scrollIntoView({ behavior: "smooth", block: "start" }),
    }, t("calc_link")));

  const quotas = p.trial.quotas;
  const free = h("section", { class: "card" },
    h("div", { class: "card-label" }, t("free_header")),
    h("div", { class: "info-box" },
      h("div", { class: "info-box-title" }, t("trial_title")),
      h("div", { class: "info-box-lead" },
        `${number(p.trial.days)} ${word("w_days", p.trial.days)} · ${number(p.trial.posts)} ${word("w_posts", p.trial.posts)}`),
      h("ul", { class: "bullets" },
        h("li", {}, t("trial_auto")),
        h("li", {}, t("trial_quotas", {
          photo: number(quotas.wm_photo ?? 0), video: number(quotas.wm_video ?? 0), ai: number(quotas.ai_text ?? 0),
        })))),
    p.free_posts_per_day > 0
      ? h("div", { class: "info-box" },
        h("div", { class: "info-box-title" }, t("free_title")),
        h("div", { class: "info-box-lead" },
          `${number(p.free_posts_per_day)} ${word("w_posts", p.free_posts_per_day)} ${t("per_day")}`),
        h("ul", { class: "bullets" },
          h("li", {}, t("free_scope")),
          h("li", {}, t("free_no_multi")),
          h("li", {}, t("free_no_extras"))))
      : null,
    h("p", { class: "fineprint" }, t("free_note")));

  const discountRow = (label, pct) => h("div", { class: "term-row" }, h("span", {}, label), h("span", { class: "good" }, `−${pct}%`));
  const maxDiscount = p.channel_discounts.reduce((max, [, pct]) => Math.max(max, pct), 0);
  const discounts = h("section", { class: "card" },
    h("div", { class: "card-label" }, t("discounts_header")),
    h("div", { class: "disc-grid" },
      h("div", { class: "info-box" },
        h("div", { class: "info-box-title" }, t("disc_channels")),
        h("p", { class: "disc-text" }, t("disc_channels_text", { max: maxDiscount })),
        ui.tiers
          ? h("div", { class: "term-list" }, p.channel_discounts.map(([n, pct]) =>
            discountRow(`${t("from")} ${number(n)} ${word("w_channels_from", n)}`, pct)))
          : null,
        h("button", { class: "text-link text-link-left", type: "button", onclick: rerender(() => { ui.tiers = !ui.tiers; }) },
          t(ui.tiers ? "less" : "more"))),
      h("div", { class: "info-box" },
        h("div", { class: "info-box-title" }, t("disc_term")),
        h("div", { class: "term-list" }, p.term_discounts
          .filter(([, pct]) => pct > 0)
          .map(([days, pct]) => discountRow(`${number(days)} ${word("w_days", days)}`, pct))))));

  const prices = state.me.limit_prices;
  const kinds = Object.keys(prices);
  const sizes = [...new Set(kinds.flatMap((kind) => Object.keys(prices[kind]).map(Number)))].sort((a, b) => a - b);
  const packs = h("section", { class: "card" },
    h("div", { class: "card-label" }, t("packs_header")),
    h("div", { class: "table-wrap" },
      h("table", { class: "packs-table" },
        h("thead", {}, h("tr", {}, h("th", {}), sizes.map((size) => h("th", {}, String(size))))),
        h("tbody", {}, kinds.map((kind) =>
          h("tr", {},
            h("th", {}, t(`pack_${kind}`)),
            sizes.map((size) => h("td", {}, prices[kind][size] == null ? "—" : `${number(prices[kind][size])} ⭐`))))))),
    h("p", { class: "fineprint" }, t("rate_note", { stars: number(Math.round(1 / state.me.usd_rate)) })));

  return [h("h1", { class: "title" }, t("plans_title")), posting, free, discounts, packs, calculator];
}

function channelSelect(id, channels, selected, onChange) {
  const select = h("select", { id, class: "select" }, channels.map((c) => h("option", { value: c.id }, c.title)));
  select.value = String(selected);
  select.addEventListener("change", () => onChange(Number(select.value)));
  return h("div", { class: "select-wrap" }, select);
}

function fillTransfer(card, data) {
  const { sources, targets } = data;
  if (!sources.length) {
    card.replaceChildren(h("p", { class: "empty-state" }, t("transfer_empty")));
    return;
  }
  if (!targets.length) {
    card.replaceChildren(h("p", { class: "empty-state" }, t("transfer_no_targets")));
    return;
  }
  const ui = (state.transfer ??= {});
  if (!sources.some((c) => c.id === ui.fromId)) ui.fromId = sources[0].id;
  if (!targets.some((c) => c.id === ui.toId)) ui.toId = targets[0].id;
  const source = sources.find((c) => c.id === ui.fromId);
  const target = targets.find((c) => c.id === ui.toId);
  const refill = (key) => (value) => {
    ui[key] = value;
    fillTransfer(card, data);
  };
  const packs = Object.entries(source.quotas)
    .filter(([, n]) => n > 0)
    .map(([kind, n]) => `${t(`pack_${kind}`)}: ${number(n)}`)
    .join(" · ");
  const button = h("button", { class: "btn btn-primary", type: "button" }, t("transfer_btn"));
  button.addEventListener("click", () => {
    tg.showConfirm(t("transfer_confirm", { from: source.title, to: target.title }), (ok) => {
      if (ok) runTransfer(button, source, target);
    });
  });

  card.replaceChildren(
    h("label", { class: "field-label", for: "transfer-from" }, t("transfer_from")),
    channelSelect("transfer-from", sources, ui.fromId, refill("fromId")),
    h("label", { class: "field-label", for: "transfer-to" }, t("transfer_to")),
    channelSelect("transfer-to", targets, ui.toId, refill("toId")),
    h("div", { class: "remaining" },
      infoRow(t("plan"), planName(source.posts_per_day)),
      infoRow(t("valid_until"), `${formatDate(source.until, state.me.user.tz)} · ${t("days_short", { n: source.days_left })}`),
      infoRow(t("transfer_packs"), packs || "—")),
    h("p", { class: "hint transfer-warning" }, t("transfer_warning", { title: source.title })),
    button);
}

async function runTransfer(button, source, target) {
  button.disabled = true;
  try {
    await api("transfer", { from_id: source.id, to_id: target.id });
    state.transfer = null;
    await loadMe().catch(() => {});
    tg.HapticFeedback?.notificationOccurred("success");
    tg.showAlert(t("transfer_done", { title: target.title }));
    render();
  } catch {
    tg.showAlert(t("error"));
    button.disabled = false;
  }
}

function renderTransfer() {
  const card = h("section", { class: "card" }, h("p", { class: "empty-state" }, "…"));
  api("transfer")
    .then((data) => fillTransfer(card, data))
    .catch(() => card.replaceChildren(h("p", { class: "empty-state" }, t("error"))));
  return [
    h("h1", { class: "title title-tight" }, t("transfer_title")),
    h("div", { class: "subtitle" }, t("transfer_hint")),
    card,
  ];
}

const CATEGORIES = ["renew", "none", "ok"];

function channelCategory(c) {
  if (c.days_left <= 0) return "none";
  return c.days_left <= state.me.renew_soon_days ? "renew" : "ok";
}

function postsLeftText(c) {
  if (c.posts_left == null) return t("posts_unlimited");
  const params = { left: number(c.posts_left), limit: number(c.posts_limit) };
  return t(c.posts_window === "trial" ? "posts_left_trial" : "posts_left_day", params);
}

function daysLabel(c) {
  if (c.plan === "free") return h("span", { class: "days ok" }, t("plan_free"));
  if (c.days_left <= 0) return h("span", { class: "days expired" }, t("expired"));
  const ok = c.days_left > state.me.renew_soon_days;
  return h("span", { class: ok ? "days ok" : "days" }, t("days_short", { n: c.days_left }));
}

function subscribeState(preselect) {
  const filters = new Set(["renew", "none"]);
  const selected = new Set();
  for (const c of state.me.channels) {
    if (!preselect.includes(c.id)) continue;
    selected.add(c.id);
    filters.add(channelCategory(c));
  }
  return { filters, selected };
}

function openSubscribe(preselect = []) {
  state.subscribe = subscribeState(preselect);
  go("subscribe");
}

function toggleFilter(category) {
  const sub = state.subscribe;
  if (sub.filters.has(category)) {
    sub.filters.delete(category);
    for (const c of state.me.channels) {
      if (channelCategory(c) === category) sub.selected.delete(c.id);
    }
  } else {
    sub.filters.add(category);
  }
  render();
}

function renderSubscribe() {
  const sub = (state.subscribe ??= subscribeState([]));
  const channels = state.me.channels;
  const counts = { renew: 0, none: 0, ok: 0 };
  channels.forEach((c) => { counts[channelCategory(c)] += 1; });
  const visible = channels.filter((c) => sub.filters.has(channelCategory(c)));
  const allSelected = visible.length > 0 && visible.every((c) => sub.selected.has(c.id));
  const count = sub.selected.size;

  const rows = visible.map((c) => {
    const selected = sub.selected.has(c.id);
    const toggle = () => {
      if (selected) sub.selected.delete(c.id);
      else sub.selected.add(c.id);
      render();
    };
    return h("button", { class: "renew-row", type: "button", "aria-pressed": String(selected), onclick: toggle },
      selected ? h("span", { class: "avatar avatar-check" }, icon("check")) : h("span", { class: "avatar" }, initial(c.title)),
      h("span", { class: "grow" }, c.title),
      daysLabel(c));
  });

  let list;
  if (!channels.length) list = h("p", { class: "hint" }, t("no_channels"));
  else if (!visible.length) list = h("p", { class: "hint" }, t("no_filtered"));
  else list = h("div", { class: "pick-list" }, rows);

  const toggleAll = () => {
    if (allSelected) sub.selected.clear();
    else visible.forEach((c) => sub.selected.add(c.id));
    render();
  };

  return [
    h("h1", { class: "title title-tight" }, t("sub_title")),
    h("div", { class: "subtitle" }, t("sub_hint")),
    h("div", { class: "chips" }, CATEGORIES.map((category) =>
      h("button", {
        class: sub.filters.has(category) ? "chip active" : "chip",
        type: "button",
        "aria-pressed": String(sub.filters.has(category)),
        onclick: () => toggleFilter(category),
      }, `${t(`cat_${category}`)} · ${counts[category]}`))),
    h("section", { class: "card pick-card" },
      list,
      h("div", { class: "pick-footer" },
        h("span", {}, t("selected_count", { n: count })),
        visible.length
          ? h("button", { class: "text-btn", type: "button", onclick: toggleAll }, t(allSelected ? "clear_selection" : "select_all"))
          : null),
      h("button", { class: "btn btn-primary btn-quiet-disabled", type: "button", disabled: count === 0, onclick: soon },
        count ? `${t("continue")} · ${count}` : t("continue"))),
    h("button", { class: "text-link", type: "button", onclick: () => go("plans") }, t("plans")),
  ];
}

function formatDate(iso, timeZone) {
  const locale = state.lang === "en" ? "en-US" : "uk-UA";
  const options = { day: "numeric", month: "short", year: "numeric" };
  try {
    return new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(new Date(iso));
  } catch {
    return new Intl.DateTimeFormat(locale, options).format(new Date(iso));
  }
}

function infoRow(label, value, valueClass = "") {
  return h("div", { class: "info-row" },
    h("span", { class: "info-label" }, label),
    h("span", { class: `info-value ${valueClass}`.trim() }, value));
}

function renderChannel(id) {
  const card = h("section", { class: "card channel-card" }, h("p", { class: "hint" }, "…"));
  api(`channels/${id}`)
    .then((c) => {
      let expires;
      if (c.plan === "free") expires = infoRow(t("expires"), "—");
      else if (c.days_left > 0) {
        expires = infoRow(t("expires"), t("days_short", { n: c.days_left }), c.days_left <= state.me.renew_soon_days ? "warn" : "");
      } else expires = infoRow(t("expires"), t("expired"), "danger");
      card.replaceChildren(
        h("div", { class: "channel-head" },
          h("span", { class: "avatar avatar-lg" }, initial(c.title)),
          h("div", { class: "channel-name" },
            h("div", { class: "channel-title" }, c.title),
            h("a", {
              class: "link-plain",
              href: c.link,
              onclick: (event) => {
                event.preventDefault();
                tg.openTelegramLink(c.link);
              },
            }, t("open_in_tg")))),
        h("div", { class: "info" },
          infoRow(t("status"), t(`status_${c.status}`)),
          infoRow(t("plan"), c.posts_per_day ? planName(c.posts_per_day) : t(`plan_${c.plan}`)),
          infoRow(t("posts_left_label"), postsLeftText(c), c.posts_left === 0 ? "danger" : ""),
          expires,
          infoRow(t("valid_until"), c.until ? formatDate(c.until, state.me.user.tz) : "—")));
    })
    .catch(() => card.replaceChildren(h("p", { class: "hint" }, t("error"))));
  return [
    h("h1", { class: "title" }, t("channel_title")),
    card,
    h("button", { class: "btn btn-primary", type: "button", onclick: () => openSubscribe([Number(id)]) },
      t("renew_subscription")),
  ];
}

async function pollBalance(before) {
  for (let i = 0; i < 15; i++) {
    await sleep(1000);
    try {
      await loadMe();
    } catch {
      continue;
    }
    if (state.me.balance !== before) {
      render();
      return;
    }
  }
  tg.showAlert(t("paid"));
}

const ROUTES = {
  "": renderHome,
  topup: renderTopup,
  checkout: renderCheckout,
  terms: renderTerms,
  channel: renderChannel,
  subscribe: renderSubscribe,
  limits: renderLimits,
  plans: renderPlans,
  transfer: renderTransfer,
};
const PARENT = {
  topup: "", checkout: "topup", terms: "checkout", channel: "", subscribe: "", limits: "", plans: "", transfer: "",
};
let lastHash = null;

function currentRoute() {
  const [name = "", param = ""] = location.hash.replace(/^#\/?/, "").split("/");
  if (!(name in ROUTES)) return ["", ""];
  if (name === "checkout" && !state.checkout) return ["", ""];
  if (name === "channel" && !/^\d+$/.test(param)) return ["", ""];
  return [name, param];
}

function route() {
  return currentRoute()[0];
}

function go(name) {
  const hash = `#/${name}`;
  if (location.hash === hash) render();
  else location.hash = hash;
}

function goBack() {
  const name = route();
  const checkout = state.checkout;
  if (name === "checkout" && checkout?.resume) {
    state.checkout = checkout.resume;
    go("checkout");
    return;
  }
  if (name === "checkout" && checkout?.kind === "limits") {
    go("limits");
    return;
  }
  const parent = PARENT[name] ?? "";
  go(parent === "checkout" && !state.checkout ? "" : parent);
}

function render() {
  const [name, param] = currentRoute();
  document.documentElement.lang = state.lang;
  langSelect.value = state.lang;
  currencyButtons.forEach((b) => b.classList.toggle("active", b.dataset.currency === state.currency));
  footer.textContent = state.me.bot_username ? `@${state.me.bot_username}` : "";
  view.replaceChildren(...ROUTES[name](param).flat(Infinity).filter(Boolean));
  if (name) tg.BackButton.show();
  else tg.BackButton.hide();
  if (location.hash !== lastHash) window.scrollTo(0, 0);
  lastHash = location.hash;
}

function notice(text) {
  view.replaceChildren(h("p", { class: "notice" }, text));
}

async function init() {
  if (!tg || !tg.initData) {
    notice(I18N.uk.open_in_telegram);
    return;
  }
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.("#151b26");
  tg.setBackgroundColor?.("#151b26");
  tg.BackButton.onClick(goBack);

  currencyButtons.forEach((b) => b.addEventListener("click", () => {
    state.currency = b.dataset.currency;
    savePref("currency", state.currency);
    render();
  }));
  langSelect.addEventListener("change", () => {
    state.lang = langSelect.value;
    render();
    api("lang", { lang: state.lang })
      .then(() => { if (route() === "terms") render(); })
      .catch(() => {});
  });

  try {
    await loadMe();
  } catch {
    notice(I18N.uk.error);
    return;
  }
  state.lang = state.me.user.lang in I18N ? state.me.user.lang : "uk";
  window.addEventListener("hashchange", render);
  render();
}

init();
