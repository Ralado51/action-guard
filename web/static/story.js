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

function hero() {
  const d = el('section', 'st-hero');
  d.append(el('h1', '', 'An AI agent says the work is done. Would you accept it?'));
  d.append(el('p', 'st-lead', 'Action Guard checks the Salesforce record against the agreed rule, not the agent’s word, and keeps a record of the decision to accept the result or investigate it.'));
  const b = el('button', 'primary', 'Walk through one Case in 60 seconds'); b.type = 'button'; b.onclick = () => go(1);
  d.append(b);
  const tl = el('a', 'quiet linkbtn', 'Try it on a live Case'); tl.href = '#/live'; tl.hidden = true; d.append(tl);
  fetch('/api/live/status', { cache: 'no-store' }).then(r => r.json()).then(j => { tl.hidden = !j.enabled; }).catch(() => {});
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
