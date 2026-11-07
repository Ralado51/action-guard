'use strict';
(() => {
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const utc = t => t.replace('T', ' ').replace('Z', ' UTC');
const PLAIN = { chk_status_closed: 'The Case is closed', chk_reason_filled: 'A closure reason is recorded', chk_followup_task: 'Exactly one follow-up Task is linked to the Case' };
const EVT = { opened: 'Detected by the audit', assigned: 'Taken by the visitor', fix_recorded: 'Correction recorded', revalidated: 'Checked again by a new audit', closed: 'Closed with evidence' };
let status = null, view = null, timer = null, busy = false, error = '';

const store = { get() { try { return sessionStorage.getItem('ag_live'); } catch (e) { return null; } }, set(v) { try { v ? sessionStorage.setItem('ag_live', v) : sessionStorage.removeItem('ag_live'); } catch (e) { /* optional */ } } };

async function api(path, body) {
  const r = await fetch('/api/live' + path, body === undefined ? { cache: 'no-store' } : { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  let j = null; try { j = await r.json(); } catch (e) { /* no body */ }
  if (!r.ok) throw new Error((j && j.detail) || 'Something went wrong. Try again.');
  return j;
}

function table(row) {
  const t = el('table', 'ef'); const hr = el('tr'); ['Condition', 'Expected', 'Found in Salesforce', 'Result'].forEach(h => hr.append(el('th', '', h)));
  const th = el('thead'); th.append(hr); t.append(th); const tb = el('tbody');
  row.checks.forEach(c => { const tr = el('tr', c.status); tr.append(el('td', '', PLAIN[c.check_id] || c.description), el('td', '', c.expected), el('td', 'found', c.found), el('td', 'res', c.status === 'passed' ? '✓ Passed' : c.status === 'failed' ? '✗ Failed' : 'Cannot confirm')); tb.append(tr); });
  t.append(tb); return t;
}

function banner(d) {
  const inc = d.status === 'inconclusive';
  const b = el('div', 'banner ' + (d.accepted ? 'ok' : inc ? 'wait' : 'bad'));
  b.append(el('b', '', d.accepted ? 'Result accepted: every condition we can verify was met.' : inc ? 'Result not confirmed: Action Guard could not verify every condition, so it does not accept the result yet.' : 'Result not accepted: ' + (d.severity === 'critical' ? 'a required condition failed.' : 'an operational condition failed.')));
  return b;
}

function reportBlock(entry, label) {
  const d = el('div', 'rep'); d.append(el('p', 'muted', label + ' · ' + utc(entry.report.generated_at) + ' · plan ' + entry.report.plan_hash.slice(0, 17) + '…'));
  d.append(banner(entry.decision), table(entry.report.cases[0]));
  return d;
}

function button(text, cls, fn) { const b = el('button', cls, text); b.type = 'button'; b.disabled = busy; b.onclick = fn; return b; }

async function act(fn) {
  busy = true; error = ''; draw();
  try { view = await fn(); store.set(view.session_id); } catch (e) { error = e.message; }
  busy = false; draw(); poll();
}

function poll() {
  clearTimeout(timer);
  if (view && (view.state === 'running')) timer = setTimeout(async () => { try { view = await api('/sessions/' + view.session_id); } catch (e) { error = e.message; } draw(); poll(); }, 2000);
}

function agreement() {
  const d = el('section', 'card'); d.append(el('h3', '', 'What was agreed'));
  d.append(el('p', '', 'The team already resolved the customer’s issue. The task given to the agent is only to record it in Salesforce:'));
  const ul = el('ul', 'plain'); ['Close the Case', 'Record a closure reason', 'Create exactly one follow-up Task'].forEach(t => ul.append(el('li', '', t)));
  d.append(ul, el('p', 'muted', 'Action Guard will check these three conditions in the Salesforce record. It does not judge whether the customer’s issue was resolved.'));
  return d;
}

function startForm() {
  const w = el('div', 'live');
  const f = el('form', 'live-form card');
  f.append(el('h3', '', 'You are the support analyst'));
  const lc = el('label', '', 'Access code'); lc.setAttribute('for', 'live-code');
  const code = el('input'); code.id = 'live-code'; code.type = 'password'; code.autocomplete = 'off'; code.required = true;
  f.append(lc, code);
  const sc = el('fieldset'); sc.append(el('legend', '', 'Situation (fixed list, you type nothing the agent reads)'));
  status.scenarios.forEach((s, i) => { const l = el('label', 'opt'); const r = el('input'); r.type = 'radio'; r.name = 'sc'; r.value = s.key; r.checked = i === 0; const sp = el('span'); sp.append(el('b', '', s.title), el('br'), s.text); l.append(r, sp); sc.append(l); });
  const md = el('fieldset'); md.append(el('legend', '', 'What should happen'));
  [['agent', 'Let the Vultr agent handle it', 'A real agent records the closure and creates the follow-up Task.'],
   ['verifier_test', 'Test the verifier with a controlled fault', 'No agent acts. The server closes the Case without a closure reason on purpose, so you see the verifier catch it. Not a failure of any agent.']]
    .forEach(([v, t, d], i) => { const l = el('label', 'opt'); const r = el('input'); r.type = 'radio'; r.name = 'md'; r.value = v; r.checked = i === 0; const s = el('span'); s.append(el('b', '', t), el('br'), d); l.append(r, s); md.append(l); });
  f.append(sc, md);
  const go = el('button', 'primary', 'Open the ticket'); go.type = 'submit'; go.disabled = busy; f.append(go);
  f.onsubmit = e => { e.preventDefault(); act(() => api('/sessions', { code: code.value, scenario: f.sc.value, mode: f.md.value })); };
  w.append(f);
  return w;
}

function progress(v) {
  const done = [!!v.case_label, ['agent_done', 'uncertain', 'fixed'].includes(v.state), v.reports.length > 0, v.reports.length > 0];
  const names = ['Case created', v.mode === 'agent' ? 'Agent acted' : 'Fault applied', 'Checked', 'Decision'];
  const n = el('nav', 'chain'); n.setAttribute('aria-label', 'Progress');
  names.forEach((t, i) => { const b = el('span', 'node' + (done[i] ? ' done' : '') + (done[i] && !done[i + 1] ? ' on' : ''), t); n.append(b); });
  return n;
}

function session() {
  const d = el('div', 'live');
  const v = view;
  d.append(progress(v)); d.append(agreement());
  const t = el('section', 'card'); t.append(el('h3', '', 'You are the support analyst'), el('p', 'muted', 'Fixed entry, chosen from a list · ' + (v.case_label ? 'Case ' + v.case_label : 'no Case created')));
  t.append(el('p', 'quote', '“' + v.scenario.text + '”')); d.append(t);
  if (v.state === 'failed') { d.append(el('p', 'banner bad', v.error || 'This session failed.')); d.append(button('Start over', 'quiet', () => { store.set(null); view = null; draw(); })); return d; }

  const h = el('section', 'card'); h.append(el('h3', '', v.mode === 'agent' ? 'Handling' : 'Controlled fault'));
  if (v.mode === 'verifier_test') h.append(el('p', '', 'Action Guard closed this Case without a closure reason, on purpose. No agent was involved.'));
  else if (v.state === 'created') { h.append(el('p', 'muted', 'The agent has not started. It acts once per ticket and is never retried.')); h.append(button('Let the agent handle it', 'primary', () => act(() => api('/sessions/' + v.session_id + '/run', {})))); }
  else if (v.state === 'running') h.append(el('p', '', 'The agent is working on the Case…'));
  else if (v.claims) {
    h.append(el('p', 'muted', 'Executor: Vultr agent · ' + v.claims.steps.length + ' recorded steps · outcome ' + v.claims.outcome));
    if (v.claims.final_message) h.append(el('p', 'quote', '“' + v.claims.final_message + '”'), el('p', 'muted', 'This is the agent’s own account. The next step reads the record instead.'));
    if (v.state === 'uncertain') h.append(el('p', 'banner bad', 'A write had an uncertain outcome. It is not repeated; check the record below.'));
  }
  d.append(h);

  const can = ['agent_done', 'uncertain', 'fixed'].includes(v.state);
  const c = el('section', 'card'); c.append(el('h3', '', 'Now check as operations'));
  if (!v.reports.length) { c.append(el('p', 'muted', can ? 'Action Guard reads the Case in Salesforce and compares it with the approved conditions. Nothing is written.' : 'Available once the ticket has been handled.')); if (can) c.append(button('Check this ticket', 'primary', () => act(() => api('/sessions/' + v.session_id + '/check', {})))); }
  else {
    c.append(reportBlock(v.reports[0], v.reports.length > 1 ? 'First audit' : 'Audit'));
    const last = v.reports[v.reports.length - 1];
    if (v.mode === 'verifier_test' && v.state === 'agent_done' && !last.decision.accepted) {
      c.append(el('p', '', 'The failure is now a finding. Fix the Case and Action Guard checks it again with the same plan.'));
      c.append(button('Fix the Case and check again', 'primary', () => act(() => api('/sessions/' + v.session_id + '/fix', {}))));
    }
  }
  d.append(c);
  if (v.finding) {
    const f = el('section', 'card'); f.append(el('h3', '', 'Finding ' + v.finding.finding_id + ' · ' + v.finding.severity));
    const ol = el('ol', 'tl'); v.finding.events.forEach(e => { const li = el('li'); li.append(el('b', '', EVT[e.type] || e.type), el('span', 'when', ' · ' + utc(e.at) + ' · ' + e.actor)); if (e.note) li.append(el('p', 'muted', e.note)); ol.append(li); });
    f.append(ol, reportBlock(v.reports[1], 'Second audit, same plan'), el('p', 'muted', 'Both audits are kept. The name “Demo visitor” is declared, not an authenticated identity.')); d.append(f);
  }
  d.append(button('Start a new ticket', 'quiet', () => { store.set(null); view = null; draw(); }));
  return d;
}

function draw() {
  const root = $('#live'); root.replaceChildren();
  const h = el('div', 'st-hero live-hero'); h.append(el('h1', '', 'Try it on a live Case'), el('p', 'st-lead', 'Record a handled ticket, then check the Salesforce record.'));
  if (status && status.enabled && !view) {
    const st = el('div', 'agree'); st.append(el('span', 'agree-k', 'The agent must'));
    ['Close the Case', 'Record a closure reason', 'Create one follow-up Task'].forEach(t => st.append(el('span', 'agree-c', t)));
    h.append(st, el('p', 'muted agree-n', 'Action Guard checks these three conditions in the record. It does not judge whether the customer’s issue was resolved.'));
  }
  root.append(h);
  if (!status) { root.append(el('p', 'muted', 'Checking whether the live demo is available…')); return; }
  if (!status.enabled) {
    root.append(el('p', 'st-lead', 'The live demo is switched off right now. The recorded walkthrough shows the same flow with real recorded data.'));
    const a = el('a', 'primary linkbtn', 'Open the walkthrough'); a.href = '#/story'; root.append(a); return;
  }
  if (error) { const e = el('p', 'banner bad', error); e.setAttribute('role', 'alert'); root.append(e); }
  root.append(view ? session() : startForm());
  const det = el('details', 'st-foot'); det.append(el('summary', '', 'Limits and what this shows'));
  det.append(el('p', 'muted', 'Live run in a Salesforce developer org, synthetic Cases only, Salesforce Ids masked, usage limits apply. It checks the outcome of closing a Case with a follow-up Task, not whether the customer’s problem was resolved. The customer message is a fixed entry, not a conversation. Names are declared, not authenticated.')); root.append(det);
}

let loaded = false;
async function show() {
  draw();
  if (!loaded) {
    loaded = true;
    try { status = await api('/status'); } catch (e) { status = { enabled: false, scenarios: [] }; }
    const sid = store.get();
    if (status.enabled && sid) { try { view = await api('/sessions/' + sid); } catch (e) { store.set(null); } }
    draw(); poll();
  }
}
window.AG = Object.assign(window.AG || {}, { showLive: show });
if (location.hash.startsWith('#/live')) show();
})();
