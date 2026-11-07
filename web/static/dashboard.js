'use strict';
(() => {
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const utc = t => t ? t.replace('T', ' ').replace('Z', ' UTC') : '';
const SRC = { 'vultr-agent': 'Vultr agent', agentforce: 'Agentforce agent' };
const PLAIN = {
  chk_status_closed: 'Case is closed', chk_reason_filled: 'Closure reason recorded', chk_followup_task: 'Exactly one follow-up Task',
  chk_reason_matches: 'Closure reason equals the expected one', chk_owner_unchanged: 'Owner unchanged', chk_no_unexpected: 'No unexpected field changes',
};
const STAT = { correct: ['Passed', 'ok', '✓'], incorrect: ['Failed', 'bad', '✕'], inconclusive: ['Not confirmed', 'wait', '?'] };
let cache = null;

async function load() {
  if (cache) return cache;
  const [r, f] = await Promise.all([fetch('/api/recorded-run', { cache: 'no-store' }), fetch('/api/recorded-flow', { cache: 'no-store' })]);
  if (!r.ok) throw Error('No recorded run is published.');
  cache = { run: await r.json(), flow: f.ok ? await f.json() : null };
  return cache;
}

function stackBar(parts, total) {
  const bar = el('div', 'dbar'); bar.setAttribute('role', 'img');
  bar.setAttribute('aria-label', parts.map(p => p.label + ' ' + p.n).join(', ') + ' of ' + total);
  parts.filter(p => p.n > 0).forEach(p => { const s = el('span', 'seg ' + p.cls); s.style.flexGrow = String(p.n); s.title = p.label + ': ' + p.n; s.append(el('i', '', p.icon), document.createTextNode(String(p.n))); bar.append(s); });
  return bar;
}
function legend() {
  const l = el('p', 'dlegend');
  Object.values(STAT).forEach(([t, c, i]) => { const k = el('span', 'key'); k.append(el('i', 'sw2 ' + c, i), document.createTextNode(t)); l.append(k); });
  return l;
}
function card(title, lead) { const c = el('section', 'dcardx'); c.append(el('h2', '', title)); if (lead) c.append(el('p', 'dlead', lead)); return c; }

function kpis(run, flow) {
  const t = run.totals, strip = el('div', 'dkpis');
  const add = (n, l, sub) => { const x = el('div', 'dk'); x.append(el('b', '', n), el('span', '', l)); if (sub) x.append(el('small', '', sub)); strip.append(x); };
  add(String(t.evaluated), 'Cases verified', t.correct + ' passed the verified checks');
  add(String(t.incorrect + t.inconclusive), 'Divergences or not confirmed', t.incorrect + ' failed · ' + t.inconclusive + ' not confirmed');
  const nObs = run.by_check.length, nNot = (run.not_auditable || []).length;
  add(nObs + ' of ' + (nObs + nNot), 'Plan conditions verified', nNot + ' declared as gaps');
  if (flow && flow.bundles) {
    const st = { open: 0, closed: 0, risk: 0 };
    flow.bundles.forEach(b => { const s = b.files.finding.state; if (s === 'closed') st.closed++; else if (s === 'risk_accepted') st.risk++; else st.open++; });
    add(String(flow.bundles.length), 'Findings', st.closed + ' closed · ' + st.risk + ' risk accepted · ' + st.open + ' open');
  }
  return strip;
}

function byExecutor(run) {
  const groups = {};
  run.cases.forEach(c => { const n = (c.agent && SRC[c.agent.source]) || 'Not attributed'; (groups[n] = groups[n] || { correct: 0, incorrect: 0, inconclusive: 0, n: 0 })[c.status]++; groups[n].n++; });
  const names = Object.keys(groups);
  const c = card('Results by executor', 'Counts only. The agents were given different instructions, so this is not a ranking.');
  names.forEach(n => {
    const g = groups[n], row = el('div', 'drow'); row.append(el('b', '', n), el('span', 'dcount', g.n + ' Cases'));
    row.append(stackBar(Object.keys(STAT).map(k => ({ cls: STAT[k][1], label: STAT[k][0], n: g[k], icon: STAT[k][2] })), g.n));
    c.append(row);
  });
  c.append(legend());
  return c;
}

function coverage(run, flow) {
  const c = card('What the audit verifies', 'Each plan condition is either checked on every Case or declared as a gap. Gaps are never counted as passed.');
  const total = run.totals.evaluated || 1;
  const sev = {};
  if (flow && flow.bundles.length) { const rep = Object.values(flow.bundles[0].files).find(x => x && x.policy); if (rep) rep.policy.conditions.forEach(k => { sev[k.check_id] = k.severity; }); }
  run.by_check.forEach(k => {
    const row = el('div', 'crow'); const head = el('div', 'chead'); head.append(el('b', '', PLAIN[k.check_id] || k.description));
    if (sev[k.check_id]) head.append(el('span', 'tag ' + sev[k.check_id], sev[k.check_id] === 'critical' ? 'Required' : 'Operational'));
    row.append(head, stackBar([{ cls: 'ok', label: 'Passed', n: k.passed, icon: '✓' }, { cls: 'bad', label: 'Failed', n: k.failed, icon: '✕' }, { cls: 'wait', label: 'Not confirmed', n: k.inconclusive, icon: '?' }], total));
    c.append(row);
  });
  (run.not_auditable || []).forEach(x => {
    const row = el('div', 'crow gap'); const head = el('div', 'chead'); head.append(el('b', '', PLAIN[x.check_id] || x.check_id));
    if (sev[x.check_id]) head.append(el('span', 'tag ' + sev[x.check_id], sev[x.check_id] === 'critical' ? 'Required' : 'Operational'));
    row.append(head, el('div', 'dbar hatch', 'Not verified'), el('p', 'dwhy', x.reason));
    c.append(row);
  });
  return c;
}

function calibration(flow) {
  const k = flow && flow.calibration; if (!k) return null;
  const c = card('Does the verifier catch known faults?', 'We seeded these ourselves in the Salesforce developer org, so the answer is known. It says how the verifier behaves, not how often a real agent fails.');
  const m = (label, n, of, good) => { const r = el('div', 'mrow'); r.append(el('span', '', label)); const t = el('div', 'dtrack'); const f = el('div', 'dfill ' + good); f.style.width = (of ? (n / of * 100) : 0) + '%'; t.append(f); r.append(t, el('b', '', n + ' of ' + of)); return r; };
  c.append(m('Injected faults detected', k.detected, k.injected, 'ok'), m('Correct Cases flagged by mistake', k.false_alarms, k.controls, 'bad'));
  c.append(el('p', 'dsmall', 'Audited ' + utc(k.audited_at) + ' · ' + k.cases.length + ' Cases'));
  return c;
}

function findings(flow) {
  if (!flow || !flow.bundles.length) return null;
  const c = card('Findings and their lifecycle', 'Every divergence becomes a finding with an owner. It closes only after a new audit passes, or when someone accepts the risk in writing.');
  const t = el('table', 'dtab'); const hr = el('tr'); ['Finding', 'Severity', 'State', 'Owner', 'Opened to resolved'].forEach(h => hr.append(el('th', '', h))); const th = el('thead'); th.append(hr); t.append(th);
  const tb = el('tbody');
  flow.bundles.forEach(b => {
    const f = b.files.finding, ev = f.events, o = ev[0], last = ev[ev.length - 1];
    const mins = Math.round((Date.parse(last.at) - Date.parse(o.at)) / 60000);
    const st = f.state === 'closed' ? ['Closed with evidence', 'ok'] : f.state === 'risk_accepted' ? ['Risk accepted, unresolved', 'wait'] : ['Open', 'bad'];
    const tr = el('tr'); const a = el('td'); a.append(el('b', '', f.finding_id), document.createTextNode(' ' + f.case_id));
    const s = el('td'); s.append(el('span', 'tag ' + (f.severity === 'critical' ? 'critical' : 'operational'), f.severity === 'critical' ? 'Required' : 'Operational'));
    const sc = el('td'); sc.append(el('span', 'state ' + st[1], st[0]));
    tr.append(a, s, sc, el('td', '', f.assignee || '—'), el('td', '', mins + ' min'));
    tb.append(tr);
  });
  t.append(tb); c.append(t);
  return c;
}

function history(run, flow) {
  const rows = [];
  if (flow && flow.calibration) rows.push([flow.calibration.audited_at, 'Calibration audit', flow.calibration.cases.length + ' Cases', flow.calibration.detected + ' of ' + flow.calibration.injected + ' faults detected']);
  if (flow) flow.bundles.forEach(b => Object.entries(b.files).forEach(([k, r]) => { if (k.startsWith('report:') && r.generated_at && r.audit_id !== (flow.calibration && flow.calibration.audit_id)) rows.push([r.generated_at, 'Revalidation after fix', (r.totals ? r.totals.evaluated : 1) + (r.totals && r.totals.evaluated !== 1 ? ' Cases' : ' Case'), r.totals ? r.totals.correct + ' passed · ' + r.totals.incorrect + ' failed' : '']); }));
  rows.push([run.generated_at, 'Recorded agent run', run.totals.evaluated + ' Cases', run.totals.correct + ' passed the verified checks']);
  rows.sort((a, b) => Date.parse(a[0]) - Date.parse(b[0]));
  const c = card('Audit history', 'Each audit is read-only and bound to the same approved plan.');
  const ol = el('ol', 'dtl');
  rows.forEach(([t, k, n, r]) => { const li = el('li'); li.append(el('time', '', utc(t)), el('b', '', k), el('span', '', n + ' · ' + r)); ol.append(li); });
  c.append(ol);
  return c;
}

async function show() {
  const root = $('#dashboard'); root.replaceChildren();
  const ld = el('p', 'loading', 'Loading dashboard…'); ld.setAttribute('role', 'status'); root.append(ld);
  let d;
  try { d = await load(); } catch (e) { const b = el('button', 'secondary', 'Try again'); b.type = 'button'; b.onclick = show; const m = el('div', 'loaderr'); m.append(el('p', '', 'Could not load the dashboard. ' + e.message), b); root.replaceChildren(m); return; }
  root.replaceChildren();
  const head = el('div', 'dhead'); head.append(el('h1', '', 'Dashboard'), el('p', '', 'The recorded evidence at a glance: what was checked, what was found, and what is still not verified.'));
  root.append(head, kpis(d.run, d.flow));
  const g = el('div', 'dgrid'), l = el('div', 'dcol'), r = el('div', 'dcol');
  [byExecutor(d.run), calibration(d.flow), findings(d.flow)].forEach(x => { if (x) l.append(x); });
  [coverage(d.run, d.flow), history(d.run, d.flow)].forEach(x => { if (x) r.append(x); });
  g.append(l, r);
  root.append(g, el('p', 'dsmall dfoot', 'Recorded run in a Salesforce developer org, synthetic Cases only, Salesforce Ids masked.'));
}
window.AG = Object.assign(window.AG || {}, { showDashboard: show });
if (location.hash.startsWith('#/dashboard')) show();
})();
