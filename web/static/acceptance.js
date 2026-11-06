'use strict';
(() => {
const $ = s => document.querySelector(s);
const el = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
const STATE = { open: 'Open', assigned: 'Assigned', fix_recorded: 'Correction recorded', revalidated: 'Revalidated', revalidation_failed: 'Revalidation failed', closed: 'Closed with evidence', risk_accepted: 'Risk accepted, unresolved' };
const EVENT = { opened: 'Detected by the audit', assigned: 'Assigned', fix_recorded: 'Correction recorded', revalidated: 'Revalidated by a new audit', closed: 'Closed', risk_accepted: 'Risk accepted' };
let flow = null;

// Same canonical form as the Python side: sorted keys, no spaces, integral floats as integers.
function canon(v) {
  if (Array.isArray(v)) return '[' + v.map(canon).join(',') + ']';
  if (v && typeof v === 'object') return '{' + Object.keys(v).sort().map(k => JSON.stringify(k) + ':' + canon(v[k])).join(',') + '}';
  return JSON.stringify(v);
}
async function sha(v) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(canon(v)));
  return 'sha256:' + [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}
async function verify(b) {
  const bad = [], m = b.manifest;
  for (const [k, v] of Object.entries(b.files)) if (m.files[k] !== await sha(v)) bad.push('Hash mismatch: ' + k);
  if (Object.keys(m.files).length !== Object.keys(b.files).length) bad.push('The manifest and the files list different entries.');
  if (m.manifest_sha256 !== await sha({ files: m.files, masked: !!m.masked })) bad.push('Manifest hash mismatch.');
  return bad;
}

function calibration(c) {
  const box = el('section', 'acc-block');
  box.append(el('h2', '', 'Does the verifier catch real problems?'));
  box.append(el('p', 'lead', 'We put ' + c.injected + ' known faults and ' + c.controls + ' correct Cases into the Salesforce developer org and audited them with the same approved plan. It flagged ' + c.detected + ' of ' + c.injected + ' faults and ' + c.false_alarms + ' of ' + c.controls + ' correct Cases.'));
  const t = el('table', 'ef');
  const hr = el('tr'); ['Case', 'What we injected', 'Expected', 'Verifier said'].forEach(h => hr.append(el('th', '', h))); const th = el('thead'); th.append(hr); t.append(th);
  const tb = el('tbody');
  c.cases.forEach(x => { const tr = el('tr', x.ok ? 'passed' : 'failed'); tr.append(el('td', '', x.label.replace(/_/g, ' ')), el('td', '', x.fault || 'Nothing (control)'), el('td', '', x.expected), el('td', 'res', x.detected_status + (x.failed_checks.length ? ' · ' + x.failed_checks.map(i => i.replace('chk_', '').replace(/_/g, ' ')).join(', ') : ''))); tb.append(tr); });
  t.append(tb); box.append(t);
  box.append(el('p', 'muted', 'Audited ' + c.audited_at.replace('T', ' ').replace('Z', ' UTC') + '. The faults were seeded by us, with a known answer. This shows how the verifier behaves on known faults; it does not say how often a real agent fails.'));
  return box;
}

function policyBlock(rep) {
  if (!rep || !rep.policy) return null;
  const p = rep.policy, box = el('section', 'acc-block');
  box.append(el('h2', '', 'What the policy covers'));
  box.append(el('p', 'lead', p.critical_observed + ' of ' + p.critical_total + ' critical conditions and ' + p.all_observed + ' of ' + p.all_total + ' conditions are observed by this audit. There is no single score: a critical condition that is not observed stays listed.'));
  const t = el('table', 'ef'); const hr = el('tr'); ['Condition', 'Severity', 'Observed'].forEach(h => hr.append(el('th', '', h))); const th = el('thead'); th.append(hr); t.append(th);
  const tb = el('tbody');
  p.conditions.forEach(c => { const tr = el('tr', c.observed ? '' : 'inconclusive'); tr.append(el('td', '', c.description), el('td', '', c.severity), el('td', 'res', c.observed ? 'Yes' : 'No · ' + (c.why_not_observed || ''))); tb.append(tr); });
  t.append(tb); box.append(t);
  return box;
}

function timeline(f) {
  const ol = el('ol', 'tl');
  f.events.forEach(e => {
    const li = el('li');
    li.append(el('b', '', EVENT[e.type] || e.type), el('span', 'when', ' · ' + e.at.replace('T', ' ').replace('Z', ' UTC') + (e.type === 'opened' ? '' : ' · ' + e.actor)));
    let detail = e.note || '';
    if (e.type === 'opened') detail = (e.data.failed_checks.length ? 'Failed: ' + e.data.failed_checks.map(i => i.replace('chk_', '').replace(/_/g, ' ')).join(', ') + '. ' : '') + Object.entries(e.data.found || {}).map(([k, v]) => 'Found: ' + v).join('; ');
    if (e.type === 'assigned') detail = 'To ' + e.data.assignee + ' by ' + e.actor;
    if (e.type === 'revalidated') detail = (e.data.passed ? 'Passed' : 'Still failing') + ' in a new audit.';
    if (e.type === 'risk_accepted') detail = e.note + ' (recorded as unresolved)';
    if (detail) li.append(el('p', 'muted', detail));
    ol.append(li);
  });
  return ol;
}

function finding(b) {
  const f = b.files.finding, card = el('article', 'finding ' + f.state);
  const head = el('div', 'f-head'); head.append(el('b', '', f.finding_id + ' · Case ' + f.case_id), el('span', 'pill', f.severity));
  card.append(head, el('p', 'f-state', STATE[f.state] || f.state), timeline(f));
  const act = el('div', 'f-actions');
  const out = el('p', 'muted', ''); out.setAttribute('role', 'status');
  const v = el('button', 'secondary', 'Verify integrity in this browser'); v.type = 'button';
  v.onclick = async () => { v.disabled = true; try { const bad = await verify(b); out.textContent = bad.length ? 'Problems: ' + bad.join(' ') : 'Integrity confirmed: every file matches the manifest (' + Object.keys(b.files).length + ' files). This shows the files were not changed after export; it does not prove who produced them.'; out.className = bad.length ? 'muted bad' : 'muted ok'; } catch (e) { out.textContent = 'Verification is not available in this browser.'; } v.disabled = false; };
  const d = el('button', 'quiet', 'Download dossier (JSON)'); d.type = 'button';
  d.onclick = () => { const u = URL.createObjectURL(new Blob([JSON.stringify(b)], { type: 'application/json' })); const a = el('a'); a.href = u; a.download = 'dossier-' + f.finding_id + '.json'; a.click(); URL.revokeObjectURL(u); };
  act.append(v, d); card.append(act, out);
  card.append(el('p', 'muted cli', 'Offline: python -m acceptance verify --bundle dossier-' + f.finding_id + '.json'));
  return card;
}

function render() {
  const root = $('#acceptance'); root.replaceChildren();
  const head = el('div', 'verdict');
  head.append(el('p', 'said', 'Acceptance of agent results'), el('h1', '', 'From a detected problem to a closed one, with evidence.'));
  head.append(el('p', 'tally', 'Every divergence becomes a finding with an owner. It closes only after a new audit passes, or when someone accepts the risk in writing. The original failure stays on record.'));
  root.append(head);
  const flag = el('p', 'synthetic-flag', 'Recorded run in a Salesforce developer org with synthetic Cases whose faults were injected by us. Roles are a prototype: names are declared on a shared token, not authenticated identities. Salesforce Ids are masked.');
  root.append(flag);
  if (flow.calibration) root.append(calibration(flow.calibration));
  const rep = flow.bundles.flatMap(b => Object.entries(b.files).filter(([k]) => k.startsWith('report:')).map(([, v]) => v))[0];
  const pb = policyBlock(rep); if (pb) root.append(pb);
  const sec = el('section', 'acc-block'); sec.append(el('h2', '', 'Findings and their dossiers'));
  flow.bundles.forEach(b => sec.append(finding(b)));
  sec.append(el('p', 'muted', 'Hashes show a file matches the manifest. They do not prove authorship and do not stop someone replacing the whole bundle; that would need a signature, which this prototype does not claim.'));
  root.append(sec);
}

async function show() {
  const root = $('#acceptance');
  if (!flow) {
    try { const r = await fetch('/api/recorded-flow', { cache: 'no-store' }); if (!r.ok) throw Error(); flow = await r.json(); }
    catch { root.replaceChildren(el('p', 'muted', 'No recorded acceptance flow has been published yet.')); return; }
  }
  render();
}

window.AG = Object.assign(window.AG || {}, { showAcceptance: show });
if (location.hash.startsWith('#/acceptance')) show();
})();
