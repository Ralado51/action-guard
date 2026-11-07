'use strict';
(() => {
const $ = s => document.querySelector(s);
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x !== undefined) n.textContent = x; return n; };
const day = t => t ? t.slice(0, 10) : 'never';
let newKey = null, msg = null;

async function authed(path, method, body) {
  const r = await fetch(path, { method, headers: { 'Authorization': 'Bearer ' + (window.AG.token() || ''), 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
  let d = null; try { d = await r.json(); } catch (e) {}
  if (!r.ok) throw Error((d && typeof d.detail === 'string') ? d.detail : 'The request was not accepted.');
  return d;
}

function link(text, href, cls) { const a = el('a', cls || 'secondary btnlink', text); a.href = href; return a; }
function sec(title, lead) { const c = el('section', 'dcardx'); c.append(el('h2', '', title)); if (lead) c.append(el('p', 'dlead', lead)); return c; }

function steps(who) {
  const c = sec('How an operator puts a plan in place', 'The plan is the rule Action Guard checks every Case against. It is written, reviewed and approved by a named person.');
  const ol = el('ol', 'opsteps');
  [['Sign in with your own key', 'Each operator has a personal key issued by the administrator. Your name comes from the key, so nobody can approve as someone else.'],
   ['Write and review the plan', 'Describe the rule. The plan lists what will be checked and what cannot be, and you bind it to one Case.'],
   ['Approve one version', 'Approval is bound to that exact version by its hash. If the plan changes, it needs a new approval.']].forEach(([h, t]) => { const li = el('li'); li.append(el('b', '', h), el('span', '', t)); ol.append(li); });
  c.append(ol);
  const row = el('div', 'oprow');
  if (!who) { const b = el('button', 'primary', 'Sign in as operator'); b.type = 'button'; b.onclick = () => window.AG.openSignIn(); row.append(b, el('span', 'muted', 'Ask the administrator for a key.')); }
  else row.append(link('Create a plan', '#/setup', 'primary btnlink'), el('span', 'muted', 'Signed in as ' + (who.name ? who.name + ' (operator)' : 'administrator') + '.'));
  c.append(row);
  return c;
}

function why(run) {
  const c = sec('No approved plan, no verdict', 'Action Guard never decides from its own opinion. Every verdict names the approved plan it was checked against.');
  if (run) { const p = el('p', 'opplan'); p.append(el('b', '', 'Plan v' + run.plan_version), document.createTextNode(' · ' + run.plan_hash.slice(0, 22) + '… · used for all ' + run.totals.evaluated + ' recorded Cases')); c.append(p); }
  c.append(el('p', 'dsmall', 'This is the plan behind the numbers on the Dashboard. A different plan would produce a different, separately labeled audit.'));
  return c;
}

function registry(list, who, rerender) {
  const c = sec('Registered operators', 'People who can create and approve plans. The list shows names and dates only, never keys.');
  if (!list.length) { c.append(el('p', 'dsmall', 'No operators are registered yet.')); return c; }
  const t = el('table', 'dtab'); const hr = el('tr'); ['Name', 'Role', 'Registered', 'Last active', ''].forEach(h => hr.append(el('th', '', h))); const th = el('thead'); th.append(hr); t.append(th);
  const tb = el('tbody');
  list.forEach(o => {
    const tr = el('tr'); tr.append(el('td', '', o.name), el('td', '', o.role), el('td', '', day(o.created_at)), el('td', '', day(o.last_seen)));
    const act = el('td');
    if (who && who.role === 'admin') { const b = el('button', 'quiet', 'Revoke'); b.type = 'button'; b.setAttribute('aria-label', 'Revoke ' + o.name); b.onclick = async () => { try { await authed('/api/operators/' + o.id, 'DELETE'); msg = 'Revoked ' + o.name + '. Their key no longer works.'; } catch (e) { msg = e.message; } rerender(); }; act.append(b); }
    tr.append(act); tb.append(tr);
  });
  t.append(tb); c.append(t);
  return c;
}

function admin(rerender) {
  const c = sec('Register an operator', 'Administrator only. The key is shown once and only its hash is stored, so copy it now and send it to the person privately.');
  const f = el('form', 'opform');
  const l = el('label', '', 'Full name'); l.setAttribute('for', 'op-name');
  const i = el('input'); i.id = 'op-name'; i.name = 'operator-display-name'; i.maxLength = 60; i.required = true; i.setAttribute('autocomplete', 'off'); i.setAttribute('data-1p-ignore', '');
  const b = el('button', 'primary', 'Register operator'); b.type = 'submit';
  f.append(l, i, b);
  f.onsubmit = async e => { e.preventDefault(); b.disabled = true; try { const d = await authed('/api/operators', 'POST', { name: i.value, role: 'operator' }); newKey = { name: d.operator.name, key: d.key }; msg = null; } catch (er) { msg = er.message; newKey = null; } rerender(); };
  c.append(f);
  if (newKey) {
    const k = el('div', 'opkey'); k.append(el('p', '', 'Key for ' + newKey.name + ' (shown once):'));
    const code = el('code', '', newKey.key); k.append(code);
    const cp = el('button', 'secondary', 'Copy key'); cp.type = 'button'; cp.onclick = async () => { try { await navigator.clipboard.writeText(newKey.key); cp.textContent = 'Copied'; } catch (e) { cp.textContent = 'Select and copy it manually'; } };
    const done = el('button', 'quiet', 'I saved it, hide it'); done.type = 'button'; done.onclick = () => { newKey = null; rerender(); };
    k.append(cp, done); c.append(k);
  }
  return c;
}

async function show() {
  const root = $('#operators'); root.replaceChildren();
  const who = window.AG.who ? window.AG.who() : null;
  let list = [], run = null;
  try { const r = await fetch('/api/operators', { cache: 'no-store' }); if (r.ok) list = (await r.json()).operators; } catch (e) {}
  try { const r = await fetch('/api/recorded-run', { cache: 'no-store' }); if (r.ok) run = await r.json(); } catch (e) {}
  root.replaceChildren();
  const head = el('div', 'dhead'); head.append(el('h1', '', 'Operators'), el('p', '', 'Operators create and approve the plan that every verdict depends on. Each one has a name and a personal key.'));
  root.append(head);
  if (msg) { const m = el('p', 'banner wait', msg); m.setAttribute('role', 'status'); root.append(m); }
  const g = el('div', 'dgrid'), l = el('div', 'dcol'), r = el('div', 'dcol');
  l.append(steps(who), why(run)); r.append(registry(list, who, show));
  if (who && who.role === 'admin') r.append(admin(show));
  g.append(l, r); root.append(g);
}

document.addEventListener('ag:signin', () => { if (location.hash.startsWith('#/operators')) show(); });
window.AG = Object.assign(window.AG || {}, { showOperators: show });
if (location.hash.startsWith('#/operators')) show();
})();
