'use strict';
(() => {
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const utc = t => t.replace('T', ' ').replace('Z', ' UTC');
const PLAIN = {
  chk_status_closed: 'The Case is closed',
  chk_reason_filled: 'A closure reason is recorded',
  chk_followup_task: 'Exactly one follow-up Task is linked to the Case',
};
const NAMES = ['Agreement', 'Claim', 'Check', 'Decision', 'Fixed and checked again'];
let S = null, step = 0;

function derive(flow, run) {
  const closed = flow.bundles.find(b => b.files.finding.state === 'closed');
  if (!closed) return null;
  const f = closed.files.finding, ev = t => f.events.find(e => e.type === t);
  const first = closed.files['report:' + f.opened_audit_id];
  const second = closed.files['report:' + ev('revalidated').data.audit_id];
  const row = r => r.cases.find(c => c.case_id === f.case_id);
  const real = run && run.cases.find(c => c.agent && c.agent.final_message && c.agent.source === 'vultr-agent');
  return { f, ev, first, second, bad: row(first), good: row(second), cal: flow.calibration, run, real };
}

function pill(text, cls) { return el('span', 'pill ' + (cls || ''), text); }


function player() {
  const root = el('div', 'player'), nodes = el('div', 'flow'), stage = el('div', 'stage'), ctl = el('div', 'pctl');
  const labels = ['Approved rule', 'Agent reports', 'Record checked', 'Decision', 'Fixed and re-checked'];
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rowsOf = (r, shown) => { const ul = el('ul', 'plain pl'); r.checks.forEach((c, i) => { const li = el('li', 'pli'); const ok = c.status === 'passed'; li.append(el('b', ok ? 'ok' : 'no', ok ? 'Met' : 'Not met'), document.createTextNode(' ' + (PLAIN[c.check_id] || c.description))); if (!reduce) { li.style.animationDelay = (i * 0.7) + 's'; } ul.append(li); }); return ul; };
  const views = [
    () => { const d = el('div'); d.append(el('h3', '', 'Before anything runs, the rule is turned into conditions.')); const ul = el('ul', 'plain pl'); S.first.policy.conditions.filter(c => c.observed).forEach((c, i) => { const li = el('li', 'pli'); li.append(el('b', 'ok', c.severity === 'critical' ? 'Required' : 'Operational'), document.createTextNode(' ' + (PLAIN[c.check_id] || c.description))); if (!reduce) li.style.animationDelay = (i * 0.5) + 's'; ul.append(li); }); d.append(ul, el('p', 'muted', 'A person approves this version. Its hash is recorded.')); return d; },
    () => { const d = el('div'); d.append(el('h3', '', 'The agent answers:'), el('p', 'big pli', '“Case closed.”'), el('p', 'muted', 'That is its own account. Action Guard does not take it as proof.')); return d; },
    () => { const d = el('div'); d.append(el('h3', '', 'Action Guard reads the Salesforce record, read-only:'), rowsOf(S.bad), el('p', 'muted', 'Controlled test Case: we left out the closure reason on purpose.')); return d; },
    () => { const d = el('div'); d.append(el('h3', '', 'A required condition is not met, so the result is not accepted.'), el('p', 'pli', 'A finding is opened, assigned to a person, and tracked until it is fixed.')); return d; },
    () => { const d = el('div'); d.append(el('h3', '', 'After the fix, a new audit confirms it.'), rowsOf(S.good), el('p', 'muted', 'The finding closes only after this second check, with a verifiable evidence dossier.')); return d; },
  ];
  let i = 0, timer = null, playing = !reduce;
  const btns = labels.map((t, k) => { const b = el('button', 'chip w', t); b.type = 'button'; b.onclick = () => { stop(); set(k); }; return b; });
  btns.forEach((b, k) => { if (k) nodes.append(el('i', 'arrow')); nodes.append(b); });
  function set(k) { i = k; btns.forEach((b, j) => { b.classList.toggle('y', j === k); b.classList.toggle('w', j !== k); b.classList.toggle('done', j < k); b.toggleAttribute('aria-current', j === k); }); stage.replaceChildren(views[k]()); }
  function tick() { set((i + 1) % views.length); }
  function start() { playing = true; pb.textContent = 'Pause'; clearInterval(timer); timer = setInterval(() => { if (!document.hidden && document.body.contains(root)) tick(); else if (!document.body.contains(root)) clearInterval(timer); }, 4200); }
  function stop() { playing = false; pb.textContent = 'Play'; clearInterval(timer); }
  const pb = el('button', 'quiet', 'Pause'); pb.type = 'button'; pb.onclick = () => playing ? stop() : start();
  ctl.append(pb);
  stage.setAttribute('aria-live', 'polite');
  root.append(nodes, stage, ctl); set(0); if (playing) start(); else pb.textContent = 'Play';
  return root;
}

const ICON = {
  sheet: '<svg viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.5"/><path d="M2 6.5h12M6 6.5v7"/></svg>',
  rule: '<svg viewBox="0 0 16 16"><path d="M4 2.5h6l3 3v8H4z"/><path d="M6 8h5M6 10.5h5"/></svg>',
  db: '<svg viewBox="0 0 16 16"><ellipse cx="8" cy="4" rx="5" ry="2"/><path d="M3 4v8c0 1.1 2.2 2 5 2s5-.9 5-2V4M3 8c0 1.1 2.2 2 5 2s5-.9 5-2"/></svg>',
  chat: '<svg viewBox="0 0 16 16"><path d="M2.5 3.5h11v7h-6l-3 2.5v-2.5h-2z"/></svg>',
  search: '<svg viewBox="0 0 16 16"><circle cx="7" cy="7" r="4"/><path d="M10 10l3.5 3.5"/></svg>',
  scale: '<svg viewBox="0 0 16 16"><path d="M8 2.5v11M4 13.5h8M3 5.5h10M3 5.5l-1.5 4a2 2 0 003 0zM13 5.5l-1.5 4a2 2 0 003 0z"/></svg>',
  wrench: '<svg viewBox="0 0 16 16"><path d="M10.5 2.5a3.2 3.2 0 00-3 4.3L2.5 11.8l1.7 1.7 5-5a3.2 3.2 0 004.3-3l-2 2-1.8-.4-.4-1.8z"/></svg>',
  file: '<svg viewBox="0 0 16 16"><path d="M4 2h5.5L13 5.5V14H4z"/><path d="M9 2v4h4"/></svg>',
  list: '<svg viewBox="0 0 16 16"><path d="M5.5 4h8M5.5 8h8M5.5 12h8M2.5 4h.01M2.5 8h.01M2.5 12h.01"/></svg>',
  check: '<svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5"/><path d="M5.5 8l2 2 3.5-4"/></svg>',
};
function chip(cls, icon, text, x, y, w) {
  const c = el('div', 'dn ' + cls); c.style.cssText = 'left:' + (x / 10) + '%;top:' + (y / 3.3) + '%;width:' + (w / 10) + '%';
  const i = el('span', 'ic'); i.innerHTML = ICON[icon]; c.append(i, el('span', '', text)); return c;
}
const SHORT = { chk_status_closed: 'Case closed', chk_reason_filled: 'Closure reason', chk_followup_task: 'One follow-up Task' };
function diagram() {
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const root = el('div', 'diag'); root.setAttribute('role', 'img');
  root.setAttribute('aria-label', 'Animated: the approved rule and the Salesforce record go through a read-only audit, a decision, and a fix with a second audit. The outputs are an evidence dossier, a findings log and a decision.');
  const NX = [200, 420, 640], NY = 80;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); svg.setAttribute('viewBox', '0 0 1000 330'); svg.setAttribute('class', 'wires');
  const line = (d, cls) => { const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', d); p.setAttribute('class', cls); svg.append(p); return p; };
  const conn = (d, g) => { line(d, 'w base'); line(d, 'w hot ' + g); const q = line(d, 'pulse ' + g); q.setAttribute('pathLength', '100'); };
  const elbow = (x0, y0, xm, y1, x1, r) => { if (y0 === y1) return 'M' + x0 + ' ' + y0 + 'H' + x1; const sg = y1 > y0 ? 1 : -1; return 'M' + x0 + ' ' + y0 + 'H' + (xm - r) + 'Q' + xm + ' ' + y0 + ' ' + xm + ' ' + (y0 + sg * r) + 'V' + (y1 - sg * r) + 'Q' + xm + ' ' + y1 + ' ' + (xm + r) + ' ' + y1 + 'H' + x1; };
  const ROWS = [43, 83, 123];
  ROWS.forEach(y => conn(elbow(150, y + 17, 175, NY + 20, 200, 8), 'g0'));
  conn('M390 100H420', 'g1'); conn('M610 100H640', 'g2');
  ROWS.forEach(y => conn(elbow(830, NY + 20, 836, y + 17, 848, 5), 'g3'));
  NX.forEach((x, i) => { line('M' + x + ' 48V' + NY, 'w dot dt' + i); line('M' + x + ' ' + (NY + 40) + 'V158', 'w dot db' + i); });
  root.append(svg);
  const srcs = [['sheet', 'Approved rule', 43], ['db', 'Salesforce record', 83], ['chat', 'Agent’s report', 123]].map(([ic, t, y]) => { const c = chip('src', ic, t, 10, y, 140); root.append(c); return c; });
  const nodes = [['search', 'Read-only audit'], ['scale', 'Decision'], ['wrench', 'Fix and re-check']].map(([ic, t], i) => { const n = chip('node n' + i, ic, t, NX[i], NY, 190); root.append(n); return n; });
  const outs = [['file', 'Evidence dossier', 'o-blue', 43], ['list', 'Findings log', 'o-tan', 83], ['check', 'Decision', 'o-green', 123]].map(([ic, t, c, y]) => { const o = chip('out ' + c, ic, t, 848, y, 150); root.append(o); return o; });
  const metrics = ['3 conditions checked on the real record', '1 required condition not met: result not accepted', 'A finding closes only after a second audit'];
  const mets = metrics.map((t, i) => { const m = el('div', 'metric m' + i, t); m.style.cssText = 'left:' + ((NX[i] + 8) / 10) + '%;top:' + (2 / 3.3) + '%;width:' + 19 + '%'; root.append(m); return m; });
  const card = (i, build) => { const c = el('div', 'dcard c' + i); c.style.cssText = 'left:' + (NX[i] / 10) + '%;top:' + (158 / 3.3) + '%;width:' + (205 / 10) + '%'; build(c); root.append(c); return c; };
  const rows = r => { const u = el('div', 'dl'); r.checks.forEach(c => { const l = el('div'); l.append(el('b', c.status === 'passed' ? 'ok' : 'no', c.status === 'passed' ? 'MET ' : 'NOT MET '), document.createTextNode(SHORT[c.check_id] || c.description)); u.append(l); }); return u; };
  const cards = [
    card(0, c => { c.append(el('div', 'dh', 'Case record'), rows(S.bad)); }),
    card(1, c => { c.append(el('div', 'dh', 'Finding'), el('div', 'dl', 'Result: not accepted\nStatus: opened\nOwner: assigned to a person')); }),
    card(2, c => { c.append(el('div', 'dh', 'Second audit'), rows(S.good), el('div', 'dl', 'Finding: closed')); }),
  ];
  const g = el('div', 'dgi'); while (root.firstChild) g.append(root.firstChild); root.append(g);
  if (reduce) root.classList.add('calm');
  let k = -1, timer = null;
  function set(n) {
    k = n; root.dataset.k = String(n);
    nodes.forEach((x, i) => x.classList.toggle('lit', i === n));
    srcs.forEach(x => x.classList.toggle('lit', n === 0));
    mets.forEach((x, i) => x.classList.toggle('on', i === n || (n === 3)));
    cards.forEach((x, i) => x.classList.toggle('on', i === n || (n === 3)));
    outs.forEach(x => x.classList.toggle('lit', n === 3));
    root.classList.toggle('s1', n >= 1 || n === 3); root.classList.toggle('s2', n >= 2 || n === 3); root.classList.toggle('s3', n === 3);
  }
  const order = [0, 1, 2, 3, 3, -1];
  let idx = 0; set(order[0]);
  timer = setInterval(() => { if (!document.body.contains(root)) { clearInterval(timer); return; } if (document.hidden) return; idx = (idx + 1) % order.length; set(order[idx]); }, 3600);
  return root;
}

function hero() {
  const d = el('section', 'st-hero');
  d.append(el('h1', '', 'An AI agent says the work is done. Would you accept it?'));
  d.append(el('p', 'st-lead', 'Check what the agent actually changed in Salesforce. Accept the result, or investigate, with evidence.'));
  const b = el('button', 'quiet', 'See how it works'); b.type = 'button'; b.onclick = () => go(1);
  d.append(b);
  const tl = el('a', 'primary linkbtn', 'Try it live'); tl.href = '#/live'; tl.hidden = true; d.insertBefore(tl, b);
  b.className = 'primary';
  fetch('/api/live/status', { cache: 'no-store' }).then(r => r.json()).then(j => { tl.hidden = !j.enabled; if (j.enabled) b.className = 'quiet'; }).catch(() => {});
  if (S && S.bad) { d.append(diagram()); const pm = player(); pm.classList.add('pmobile'); d.append(pm); }
  if (S && S.cal) {
    const c = S.cal, st = el('div', 'stats');
    const add = (n, l) => { const x = el('div', 'stat'); x.append(el('b', '', n), el('span', '', l)); st.append(x); };
    add(c.detected + ' of ' + c.injected, 'injected faults detected');
    add(c.false_alarms + ' of ' + c.controls, 'correct Cases flagged by mistake');
    if (S.run) add(String(S.run.totals.evaluated), 'real agent Cases checked, from two executors');
    d.append(st);
  }
  d.append(el('p', 'muted st-note', 'Recorded run in a Salesforce developer org, with synthetic Cases only. Nothing here is executed live.'));
  return d;
}

function s1() {
  const p = S.first.policy, d = el('div');
  d.append(el('h2', '', 'Close the Case, record why, create one follow-up Task.'));
  d.append(el('p', 'st-lead', 'This is the rule the agent was given, turned into conditions that can be checked in the data. It was approved before anything was audited.'));
  const ul = el('ul', 'conds');
  p.conditions.filter(c => c.observed).forEach(c => {
    const li = el('li'); li.append(el('span', '', PLAIN[c.check_id] || c.description), pill(c.severity === 'critical' ? 'Required' : 'Operational', c.severity));
    ul.append(li);
  });
  d.append(ul);
  const det = el('details'); det.append(el('summary', '', 'Also in the plan, but not verifiable from the final state (' + p.conditions.filter(c => !c.observed).length + ')'));
  const nl = el('ul', 'plain'); p.conditions.filter(c => !c.observed).forEach(c => nl.append(el('li', '', c.description + ' (' + (c.why_not_observed || '').replace(/^Needs the previous state; the audit only reads the final state\.$/, 'needs the state from before the agent acted') + ')')));
  det.append(nl); d.append(det);
  d.append(el('p', 'muted', 'Plan v' + S.first.plan_version + ' · ' + S.first.plan_hash.slice(0, 17) + '…'));
  return d;
}

function s2() {
  const d = el('div'); d.append(el('h2', '', 'Two different starting points, labeled so they are not mixed up.'));
  const g = el('div', 'two');
  const a = el('article', 'card'); a.append(el('h3', '', 'Real agent run'));
  if (S.real) {
    a.append(el('p', 'muted', 'Executor: Vultr agent · ' + S.real.agent.steps.length + ' recorded steps'));
    a.append(el('p', 'quote', '“' + S.real.agent.final_message + '”'));
    a.append(el('p', 'muted', 'This is the agent’s own account. Action Guard does not take it as proof; it reads the record.'));
  } else a.append(el('p', 'muted', 'The recorded agent run is not available.'));
  const b = el('article', 'card seeded'); b.append(el('h3', '', 'Controlled detection test'));
  b.append(el('p', 'muted', 'Fault injected by us, no agent involved'));
  b.append(el('p', '', 'We closed a synthetic Case without a closure reason on purpose, to see whether the verifier would notice. This is the Case followed in the next steps.'));
  const st = el('ul', 'plain'); S.bad.checks.forEach(c => st.append(el('li', '', (PLAIN[c.check_id] || c.description) + ': ' + c.found)));
  b.append(el('p', 'muted', 'What Salesforce holds for it:'), st);
  g.append(a, b); d.append(g);
  d.append(el('p', 'muted', 'No real agent produced this fault. We do not claim one did.'));
  return d;
}

function checkTable(row) {
  const t = el('table', 'ef'); const hr = el('tr');
  ['Condition', 'Expected', 'Found', 'Result'].forEach(h => hr.append(el('th', '', h))); const th = el('thead'); th.append(hr); t.append(th);
  const tb = el('tbody');
  row.checks.forEach(c => { const tr = el('tr', c.status); tr.append(el('td', '', PLAIN[c.check_id] || c.description), el('td', '', c.expected), el('td', 'found', c.found), el('td', 'res', c.status === 'passed' ? '✓ Passed' : c.status === 'failed' ? '✗ Failed' : 'Cannot confirm')); tb.append(tr); });
  t.append(tb); return t;
}

function s3() {
  const d = el('div'); d.append(el('h2', '', 'The record disagrees on one condition.'));
  d.append(el('p', 'st-lead', 'Action Guard reads the final state in Salesforce and compares it with the agreed conditions. Nothing is written during an audit.'));
  d.append(checkTable(S.bad));
  const c = S.cal;
  d.append(el('p', 'muted', 'Audited ' + utc(S.first.generated_at) + '. Across the ' + (c.injected + c.controls) + ' Cases we seeded, the verifier flagged ' + c.detected + ' of ' + c.injected + ' injected faults and ' + c.false_alarms + ' of ' + c.controls + ' correct Cases. That shows how it behaves on faults we know about, not how often a real agent fails.'));
  return d;
}

function s4() {
  const f = S.f, d = el('div');
  d.append(el('h2', '', 'Result not accepted: a required condition failed.'));
  const card = el('article', 'card verdict-card');
  card.append(el('p', 'muted', 'Finding ' + f.finding_id + ' · Case ' + f.case_id + ' · severity ' + f.severity));
  const ev = S.ev;
  card.append(el('p', '', 'Opened by the audit at ' + utc(ev('opened').at) + '. Assigned to ' + ev('assigned').data.assignee + ' at ' + utc(ev('assigned').at) + '.'));
  d.append(card);
  d.append(el('p', 'muted', 'The failed audit stays on record. Fixing the Case later does not rewrite it. Names are declared on a shared token in this prototype; they are not authenticated identities.'));
  return d;
}

function s5() {
  const f = S.f, ev = S.ev, d = el('div');
  d.append(el('h2', '', 'Fixed, then checked again with the same plan.'));
  const ol = el('ol', 'tl');
  const item = (t, w, x) => { const li = el('li'); li.append(el('b', '', t), el('span', 'when', ' · ' + w)); if (x) li.append(el('p', 'muted', x)); ol.append(li); };
  item('Correction recorded', utc(ev('fix_recorded').at) + ' · ' + ev('fix_recorded').actor, ev('fix_recorded').note);
  item('New audit, same approved plan', utc(S.second.generated_at), 'Plan ' + S.second.plan_hash.slice(0, 17) + '… · the Case now passes all three conditions.');
  item('Closed with evidence', utc(ev('closed').at) + ' · ' + ev('closed').actor, 'Both audits are kept, the one that found the problem and the one that cleared it.');
  d.append(ol);
  d.append(el('p', 'muted st-gap', 'The same Case in the second audit:'));
  d.append(checkTable(S.good));
  const links = el('div', 'st-links');
  const a = el('a', 'primary linkbtn', 'Open the evidence dossier and verify it'); a.href = '#/acceptance';
  const b = el('a', 'secondary linkbtn', S.run ? 'See the ' + S.run.totals.evaluated + ' real agent Cases (Vultr and Agentforce)' : 'See the results'); b.href = '#/';
  links.append(a, b); d.append(links);
  d.append(el('p', 'muted', 'What this shows: the verifier caught a Case that did not meet the rule, a person took it, and a new audit confirmed the fix. What it does not show: a real agent failing, or whether the agent’s behavior was corrected in a new run. Owner preservation is not verifiable from the final state.'));
  return d;
}

function render() {
  const root = $('#story'); root.replaceChildren();
  if (!S) { root.append(el('p', 'muted', 'The recorded walkthrough is not available yet. You can still open the results.')); const a = el('a', 'quiet linkbtn', 'Open results'); a.href = '#/'; root.append(a); return; }
  if (step === 0) { root.append(hero()); root.append(foot()); return; }
  const nav = el('nav', 'chain'); nav.setAttribute('aria-label', 'Walkthrough steps');
  NAMES.forEach((n, i) => { const b = el('button', 'node' + (i + 1 === step ? ' on' : '') + (i + 1 < step ? ' done' : ''), (i + 1) + ' · ' + n); b.type = 'button'; if (i + 1 === step) b.setAttribute('aria-current', 'step'); b.onclick = () => go(i + 1); nav.append(b); });
  root.append(nav);
  const body = el('section', 'st-body'); body.append([null, s1, s2, s3, s4, s5][step]()); root.append(body);
  const pn = el('div', 'st-pn');
  const prev = el('button', 'quiet', step === 1 ? 'Back to start' : 'Previous'); prev.type = 'button'; prev.onclick = () => go(step - 1);
  pn.append(prev);
  if (step < 5) { const next = el('button', 'primary', 'Next: ' + NAMES[step]); next.type = 'button'; next.onclick = () => go(step + 1); pn.append(next); }
  root.append(pn); root.append(foot());
}

function foot() { return el('p', 'muted st-foot', 'Recorded run · synthetic Cases in a Salesforce developer org · fault injected by us · ' + (S ? S.first.policy.all_observed + ' of ' + S.first.policy.all_total + ' plan conditions observed by the audit' : '')); }

function go(n) { step = n; render(); window.scrollTo(0, 0); const h = $('#story h1, #story h2'); if (h) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); } }

let loaded = false;
async function show() {
  if (!loaded) {
    loaded = true;
    try {
      const [fr, rr] = await Promise.all([fetch('/api/recorded-flow', { cache: 'no-store' }), fetch('/api/recorded-run', { cache: 'no-store' })]);
      if (fr.ok) S = derive(await fr.json(), rr.ok ? await rr.json() : null);
    } catch (e) { S = null; }
  }
  render();
}

window.AG = Object.assign(window.AG || {}, { showStory: show });
if (!location.hash || location.hash.startsWith('#/story')) show();
})();
