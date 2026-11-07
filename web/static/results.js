'use strict';
(() => {
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const WORD = { correct: 'Passed all checks', incorrect: 'Failed a check', inconclusive: 'Cannot be confirmed' };
const CHECK = { passed: 'Passed', failed: 'Failed', inconclusive: 'Not confirmed' };
const SRC = { 'vultr-agent': 'Vultr agent', agentforce: 'Agentforce agent' };
const srcName = c => (c.agent && SRC[c.agent.source]) || null;
let data = null, filter = 'all';

function pct(r) { return r === null || r === undefined ? '—' : (r * 100).toFixed(1).replace(/\.0$/, '') + '%'; }

let source = null, recorded = null, hasRecorded = false;

async function loadSource(name) {
  if (name === 'live' && data && !data.synthetic) return data;
  if (name === 'real') {
    if (!recorded) { const r = await fetch('/api/recorded-run', { cache: 'no-store' }); if (!r.ok) throw Error('No recorded run is published.'); recorded = fromReport(await r.json()); recorded.recordedNote = true; }
    return (data = recorded);
  }
  const r = await fetch('/api/demo/audit', { cache: 'no-store' });
  if (!r.ok) throw Error('The demonstration could not be loaded.');
  return (data = await r.json());
}

async function probeRecorded() {
  try { const r = await fetch('/api/recorded-run', { method: 'HEAD', cache: 'no-store' }); hasRecorded = r.ok || r.status === 405; if (r.status === 405) { const g = await fetch('/api/recorded-run', { cache: 'no-store' }); hasRecorded = g.ok; } } catch { hasRecorded = false; }
}

function drawSwitch() {
  const box = $('#source-switch'); box.replaceChildren();
  box.hidden = !hasRecorded || source === 'live';
  if (box.hidden) return;
  [['real', 'Recorded real run'], ['demo', 'Synthetic demonstration']].forEach(([k, t]) => {
    const b = el('button', 'chip' + (source === k ? ' on' : ''), t); b.type = 'button'; b.setAttribute('aria-pressed', source === k);
    b.onclick = () => { source = k; filter = 'all'; location.hash = '#/'; route(); };
    box.append(b);
  });
}

// Real audit reports list only failing records; the rest are anonymous "met the rule" cells.
function fromReport(r) {
  const t = r.totals, by = Object.fromEntries(r.by_check.map(c => [c.check_id, c.description]));
  const cases = r.cases.map(c => {
    const checks = c.checks || [...c.failed_checks.map(x => ({ check_id: x, description: by[x] || x, status: 'failed', expected: '—', found: JSON.stringify((c.evidence || {})[x] ?? '') })),
                                ...c.inconclusive_checks.map(x => ({ check_id: x, description: by[x] || x, status: 'inconclusive', expected: '—', found: 'Could not be read' }))];
    const nFailed = checks.filter(k => k.status === 'failed').length;
    const ag = c.agent || null, said = ag && ag.outcome === 'finished';
    const lead = said ? 'The agent said it was done, but ' : 'Reported as closed, but ';
    return { case_id: c.case_id, subject: null, status: c.status, agent_claim: said ? ag.final_message : null, agent: ag, checks,
      finding: c.status === 'correct' ? 'Every auditable check passed.'
        : c.status === 'incorrect' ? lead + (nFailed === 1 ? 'a required check failed.' : nFailed + ' required checks failed.')
        : lead + 'the data could not be read well enough to confirm the outcome.' };
  });
  const sel = r.selection.mode === 'case_ids' ? 'List of Cases reported by the agent' : 'Window of closed Cases';
  const hasAgent = cases.some(c => c.agent);
  return { synthetic: false, label: hasAgent ? 'Recorded real run: agents acted on synthetic Cases in a Salesforce developer org; Action Guard then audited the records read-only. The executor of each Case is labeled. Salesforce Ids are masked. Small runs, and the two agents received different instructions: this is not a comparison of quality.' : null,
           agent_reported: t.evaluated, totals: t, outcome_rate: r.outcome_rate, by_check: r.by_check,
           not_auditable: r.not_auditable, limitations: r.limitations.concat(r.collection_errors || []), cases, onlyListed: !r.all_cases_listed, summary: r.summary,
           basis: { plan_version: r.plan_version, plan_hash: r.plan_hash, generated_at: r.generated_at, selection: sel } };
}

function strip(d) {
  const list = el('ol', 'strip');
  list.setAttribute('aria-label', 'One cell per Case the agent reported');
  const shown = d.cases.slice();
  const anon = d.onlyListed ? d.totals.correct : 0;
  shown.forEach((c, i) => {
    const li = el('li'), a = el(c.case_id ? 'a' : 'span', 'cell ' + c.status, String(d.onlyListed ? '' : i + 1));
    a.href = '#/case/' + c.case_id; a.title = WORD[c.status]; a.setAttribute('aria-label', 'Case ' + (i + 1) + ': ' + WORD[c.status]);
    li.append(a); list.append(li);
  });
  for (let i = 0; i < anon; i++) { const li = el('li'); li.append(el('span', 'cell correct', '')); list.append(li); }
  return list;
}

function failuresByRule(d) {
  const box = el('section', 'block');
  box.append(el('h2', '', d.totals.incorrect + d.totals.inconclusive ? 'Where the agent fell short' : 'What each check found'));
  const rows = d.by_check.slice().sort((a, b) => (b.failed + b.inconclusive) - (a.failed + a.inconclusive));
  const total = d.totals.evaluated || 1;
  rows.forEach(c => {
    const row = el('div', 'rule-row');
    const bad = c.failed + c.inconclusive;
    row.append(el('div', 'rule-name', c.description));
    const bar = el('div', 'bar'); bar.setAttribute('aria-hidden', 'true');
    const f = el('span', 'f'); f.style.width = (100 * c.failed / total) + '%';
    const i = el('span', 'i'); i.style.width = (100 * c.inconclusive / total) + '%';
    bar.append(f, i);
    const n = bad === 0 ? 'All ' + total + ' passed' : [c.failed ? c.failed + ' failed' : '', c.inconclusive ? c.inconclusive + ' not confirmed' : ''].filter(Boolean).join(', ');
    row.append(bar, el('div', 'rule-n' + (bad ? ' bad' : ''), n));
    box.append(row);
  });
  if (d.not_auditable && d.not_auditable.length) {
    const det = el('details', 'notver');
    det.append(el('summary', '', d.not_auditable.length + ' checks in the plan are not verified here'));
    d.not_auditable.forEach(x => det.append(el('p', '', x.check_id.replace(/^chk_/, '').replace(/_/g, ' ') + ': ' + x.reason)));
    box.append(det);
  }
  return box;
}

function records(d) {
  const box = el('section', 'block');
  box.append(el('h2', '', 'Records'));
  const bar = el('div', 'filters');
  [['all', 'All'], ['incorrect', 'Failed a check'], ['inconclusive', 'Cannot be confirmed'], ['correct', 'Passed all checks']].forEach(([k, t]) => {
    if (d.onlyListed && k === 'correct') return;
    const n = k === 'all' ? d.cases.length : d.cases.filter(c => c.status === k).length;
    const b = el('button', 'chip' + (filter === k ? ' on' : ''), t + ' · ' + n);
    b.type = 'button'; b.setAttribute('aria-pressed', filter === k);
    b.onclick = () => { filter = k; render(); };
    bar.append(b);
  });
  box.append(bar);
  const ul = el('ul', 'recs');
  const rank = { incorrect: 0, inconclusive: 1, correct: 2 };
  const view = d.cases.map((c, i) => [c, i]).filter(([c]) => filter === 'all' || c.status === filter).sort((x, y) => rank[x[0].status] - rank[y[0].status] || x[1] - y[1]);
  if (!view.length) ul.append(el('li', 'empty', 'No records in this group.'));
  view.forEach(([c, i]) => {
    const li = el('li'), a = el('a', 'rec ' + c.status);
    a.href = '#/case/' + c.case_id;
    a.append(el('span', 'dot'), el('span', 'rec-main', c.subject || 'Case ' + c.case_id),
             el('span', 'rec-find', (srcName(c) ? srcName(c) + ' · ' : '') + (c.status === 'correct' ? WORD.correct : c.finding.replace(/^(The agent reported success|Reported as closed), but /, '').replace(/^./, m => m.toUpperCase()))));
    li.append(a); ul.append(li);
  });
  box.append(ul);
  if (d.onlyListed) box.append(el('p', 'muted', 'Only records that failed or could not be confirmed are listed; the other ' + d.totals.correct + ' met every auditable check.'));
  return box;
}

function basisLine(d) {
  const b = d.basis || {}, p = el('p', 'basis');
  const bits = [];
  if (b.plan_version) bits.push('Plan v' + b.plan_version);
  if (b.plan_hash) bits.push(b.plan_hash.slice(0, 14) + '…');
  if (b.generated_at) bits.push('audited ' + b.generated_at.replace('T', ' ').replace('Z', ' UTC'));
  if (b.selection) bits.push(b.selection);
  p.textContent = 'Basis: ' + (bits.join(' · ') || '—') + (b.note ? '. ' + b.note : '');
  return p;
}

function executors(d) {
  const by = {};
  d.cases.forEach(c => { const n = srcName(c); if (n) { by[n] = by[n] || { n: 0, ok: 0 }; by[n].n++; if (c.status === 'correct') by[n].ok++; } });
  const names = Object.keys(by).sort();
  if (names.length < 2) return null;
  const box = el('section', 'block execs');
  box.append(el('h2', '', 'Executors in this audit'));
  names.forEach(n => { const r = el('div', 'exec-row'); r.append(el('b', '', n), el('span', '', by[n].n + ' Cases · ' + by[n].ok + ' passed every auditable check')); box.append(r); });
  box.append(el('p', 'muted', 'Counts only, by design: the samples are small and the agents were given different instructions. This is not a ranking.'));
  return box;
}

function overview(d) {
  const root = $('#results'); root.replaceChildren();
  const t = d.totals, bad = t.incorrect, unc = t.inconclusive;
  const head = el('div', 'verdict');
  const many = new Set(d.cases.map(srcName).filter(Boolean)).size > 1;
  head.append(el('p', 'said', (many ? 'Your agents reported ' : 'Your agent reported ') + d.agent_reported + ' Cases closed.'));
  head.append(el('h1', '', (t.correct === d.agent_reported ? 'All ' + t.correct : t.correct) + ' passed every auditable check.'));
  const sub = [];
  if (bad) sub.push(bad + ' failed at least one');
  if (unc) sub.push(unc + ' cannot be confirmed');
  head.append(el('p', 'tally', (sub.length ? sub.join(' and ') + '. ' : '') + 'Rate: ' + pct(d.outcome_rate) + '. Unconfirmed Cases never count as correct.' + (d.not_auditable && d.not_auditable.length ? ' ' + d.not_auditable.length + ' checks in the plan are not verified here, so this is not a full verdict on the rule.' : '')));
  const stats = el('div', 'vstats'); const nObs = d.by_check.length, nNot = (d.not_auditable || []).length;
  [[String(d.agent_reported), 'Cases verified'], [String(bad + unc), 'divergences' + (unc ? ' or unconfirmed' : '')], [nObs + ' of ' + (nObs + nNot), 'plan conditions verified']].forEach(([n, l]) => { const x = el('div', 'vstat'); x.append(el('b', '', n), el('span', '', l)); stats.append(x); });
  head.append(stats);
  root.append(head);
  root.append(basisLine(d));
  root.append(strip(d));
  const legend = el('p', 'legend');
  [['correct', 'Passed all checks'], ['incorrect', 'Failed a check'], ['inconclusive', 'Cannot be confirmed']].forEach(([k, t2]) => { const s = el('span', 'key'); s.append(el('i', 'sw ' + k), document.createTextNode(t2)); legend.append(s); });
  root.append(legend);
  const ex = executors(d); if (ex) root.append(ex);
  if (d.summary && d.summary.text) root.append(el('p', 'summary', d.summary.text));
  const grid = el('div', 'cols'); grid.append(failuresByRule(d), records(d)); root.append(grid);
  const lim = el('details', 'limits'); lim.append(el('summary', '', 'What this audit does not tell you'));
  d.limitations.forEach(x => lim.append(el('p', '', x))); root.append(lim);
}

function detail(id) {
  const root = $('#case-detail'); root.replaceChildren();
  const back = el('a', 'back', 'Back to results'); back.href = '#/'; root.append(back);
  const idx = data ? data.cases.findIndex(c => c.case_id === id) : -1;
  if (idx < 0) { root.append(el('h1', '', 'Record not found'), el('p', 'muted', 'Open the results first, then choose a record.')); return; }
  const c = data.cases[idx];
  root.append(el('p', 'said', (c.subject || 'Case') + ' · ' + c.case_id + (srcName(c) ? ' · ' + srcName(c) : '') + (data.synthetic ? ' · synthetic' : '')));
  root.append(el('h1', c.status, c.status === 'correct' ? 'This Case passed every auditable check.' : c.finding));
  if (c.agent_claim || c.status !== 'correct') {
    const two = el('div', 'versus');
    const l = el('div', 'side'); l.append(el('h2', '', 'What the agent said'), el('p', 'quote', c.agent_claim ? '“' + c.agent_claim + '”' : (c.agent ? 'The agent run ended without a final report (' + c.agent.outcome + ').' : 'No agent response is attached to this audit. The Case was on the list of Cases reported as closed.')));
    const r = el('div', 'side ' + c.status); r.append(el('h2', '', 'What the data shows'));
    if (c.status === 'correct') r.append(el('p', '', 'Every auditable check passed.'));
    else if (data.synthetic) r.append(el('p', '', c.finding.replace(/^The agent reported success, but /, '').replace(/^./, m => m.toUpperCase())));
    else c.checks.filter(k => k.status !== 'passed').forEach(k => r.append(el('p', 'miss', k.description.replace(/\.$/, '') + ': expected ' + (k.expected || '—') + ', found ' + k.found + '.')));
    two.append(l, r); root.append(two);
  }
  const tbl = el('table', 'ef');
  const cap = el('caption', '', 'Expected against found, check by check');
  tbl.append(cap);
  const hr = el('tr'); ['Check', 'Expected', 'Found', 'Result'].forEach(h => hr.append(el('th', '', h))); const th = el('thead'); th.append(hr); tbl.append(th);
  const tb = el('tbody');
  c.checks.forEach(k => {
    const tr = el('tr', k.status);
    tr.append(el('td', '', k.description), el('td', '', k.expected || '—'), el('td', 'found', k.found), el('td', 'res', CHECK[k.status] || k.status));
    tb.append(tr);
  });
  tbl.append(tb); root.append(tbl);
  if (c.agent && c.agent.steps && c.agent.steps.length) {
    const det = el('details', 'trace'); det.append(el('summary', '', 'What the agent did, step by step (' + c.agent.steps.length + ')'));
    const ol = el('ol'); c.agent.steps.forEach(x => ol.append(el('li', '', x.at.replace('T', ' ').replace('Z', ' UTC') + ' · ' + x.tool + (x.result ? ' → ' + x.result : ''))));
    det.append(ol); root.append(det);
  }
  if (data.not_auditable && data.not_auditable.length) root.append(el('p', 'muted', data.not_auditable.length + ' other checks of the plan need the state before the agent acted, so this audit does not claim them.'));
  const nav = el('div', 'pager');
  if (idx > 0) { const p = el('a', '', 'Previous record'); p.href = '#/case/' + data.cases[idx - 1].case_id; nav.append(p); }
  if (idx < data.cases.length - 1) { const n = el('a', '', 'Next record'); n.href = '#/case/' + data.cases[idx + 1].case_id; nav.append(n); }
  root.append(nav);
}

function render() { if (data) overview(data); }

async function route() {
  const h = location.hash;
  const view = (!h || h.startsWith('#/story')) ? 'story' : h.startsWith('#/live') ? 'live' : h.startsWith('#/setup') ? 'setup' : h.startsWith('#/acceptance') ? 'acceptance' : h.startsWith('#/case/') ? 'case' : 'results';
  ['story', 'live', 'results', 'case', 'setup', 'acceptance'].forEach(v => { $('#view-' + v).hidden = v !== view; });
  ['story', 'live', 'results', 'acceptance', 'setup'].forEach(t => { const on = (t === 'results') ? (view === 'results' || view === 'case') : view === t; $('#tab-' + t).classList.toggle('on', on); $('#tab-' + t).toggleAttribute('aria-current', on); });
  if (view === 'setup') return;
  if (view === 'live') { window.AG && window.AG.showLive && window.AG.showLive(); return; }
  if (view === 'story') { window.AG && window.AG.showStory && window.AG.showStory(); return; }
  if (view === 'acceptance') { window.AG && window.AG.showAcceptance && window.AG.showAcceptance(); window.scrollTo(0, 0); return; }
  try {
    if (source === null) { await probeRecorded(); source = hasRecorded ? 'real' : 'demo'; }
    if (!(data && source === 'live')) await loadSource(source);
  } catch (e) { $('#results').replaceChildren(el('p', 'muted', e.message)); return; }
  drawSwitch();
  const flag = $('#synthetic-flag'); flag.hidden = !data.label; flag.textContent = data.label || '';
  if (view === 'case') detail(decodeURIComponent(h.slice(7))); else { overview(data); }
  window.scrollTo(0, 0);
}

window.AG = { showReal(report) { data = fromReport(report); source = 'live'; filter = 'all'; location.hash = '#/'; route(); },
              showDemo() { source = null; data = null; filter = 'all'; route(); } };
window.addEventListener('hashchange', route);
route();
})();
