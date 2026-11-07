'use strict';
(() => {
const el = (t, c, x) => { const n = document.createElement(t); if (c) n.className = c; if (x !== undefined) n.textContent = x; return n; };
const WORDS = { read_case: 'Reads the Case', create_followup_task: 'Creates the follow-up Task', close_case: 'Closes the Case with a reason', final: 'Reports that it is done' };
const played = new Set();
const STEP_MS = 1300;

function parse(r) { try { return JSON.parse(r); } catch (e) { return null; } }

// Turns recorded steps into [{label, who, dir, apply}] where apply(state) mutates the Case card.
function plan(kind, steps) {
  if (kind === 'fault') return [
    { label: 'Action Guard sets Status to Closed, with no closure reason', dir: 'w', apply: s => { s.status = 'Closed'; } },
    { label: 'Action Guard creates the follow-up Task', dir: 'w', apply: s => { s.tasks = 1; } },
  ];
  const reads = steps.filter(x => x.tool === 'read_case').map(x => parse(x.result)).filter(Boolean);
  const out = [];
  steps.forEach(st => {
    const r = parse(st.result) || {};
    if (st.tool === 'read_case') out.push({ label: WORDS.read_case + ': ' + (r.status || 'unknown') + (r.closure_reason ? ', reason “' + r.closure_reason + '”' : '') + ', ' + (r.linked_task_subjects ? r.linked_task_subjects.length : 0) + ' Task(s)', dir: 'r', apply: s => { if (r.status) s.status = r.status; s.reason = r.closure_reason || s.reason; if (r.linked_task_subjects) s.tasks = r.linked_task_subjects.length; } });
    else if (st.tool === 'create_followup_task') out.push({ label: WORDS[st.tool] + (r.ok === false ? ' (failed)' : ''), dir: 'w', apply: s => { if (r.ok !== false) s.tasks += 1; } });
    else if (st.tool === 'close_case') { const later = reads.filter(x => x.status === 'Closed').pop(); out.push({ label: WORDS[st.tool] + (r.ok === false ? ' (failed)' : ''), dir: 'w', apply: s => { if (r.ok !== false) { s.status = 'Closed'; s.reason = later && later.closure_reason ? later.closure_reason : s.reason; } } }); }
    else if (st.tool === 'final') out.push({ label: WORDS.final, dir: null, apply: () => {} });
  });
  return out;
}

function replay(opts) {
  const kind = opts.kind, key = opts.key, steps = plan(kind, opts.steps || []);
  const box = el('div', 'rp'); const st = { status: 'New', reason: '', tasks: 0 };
  const who = kind === 'fault' ? 'Action Guard' : 'Vultr agent';
  box.append(el('p', 'rp-note', kind === 'fault' ? 'Replay of the controlled fault. No agent was involved: Action Guard applied it on purpose.' : 'Replay of the steps the agent recorded. It plays after the agent finished; it is not a live feed.'));
  const stage = el('div', 'rp-stage');
  const a = el('div', 'rp-agent'); a.append(el('b', '', who), el('span', '', kind === 'fault' ? 'applies the fault' : 'acts on the Case'));
  const wire = el('div', 'rp-wire'); wire.setAttribute('aria-hidden', 'true'); const dot = el('span', 'rp-dot'); wire.append(dot);
  const card = el('div', 'rp-case'); card.append(el('b', '', 'Case in Salesforce'));
  const cells = {};
  [['status', 'Status'], ['reason', 'Closure reason'], ['tasks', 'Follow-up Tasks']].forEach(([k, l]) => { const r = el('div', 'rp-row'); r.append(el('span', '', l)); cells[k] = el('b', '', ''); r.append(cells[k]); card.append(r); });
  stage.append(a, wire, card);
  const log = el('ol', 'rp-log'); log.setAttribute('aria-label', kind === 'fault' ? 'Fault steps' : 'Agent steps');
  const live = el('p', 'sr-only'); live.setAttribute('aria-live', 'polite');
  const bar = el('div', 'rp-bar'); const again = el('button', 'quiet', 'Replay'); again.type = 'button'; const skip = el('button', 'quiet', 'Show final state'); skip.type = 'button'; bar.append(again, skip);
  box.append(stage, log, live, bar);
  let timer = null, i = 0;
  const paint = () => { cells.status.textContent = st.status; cells.reason.textContent = st.reason || '—'; cells.tasks.textContent = String(st.tasks); cells.status.className = st.status === 'Closed' ? 'closed' : ''; cells.reason.className = st.reason ? '' : (st.status === 'Closed' ? 'missing' : ''); };
  const flash = () => { card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash'); };
  const send = dir => { if (!dir) return; wire.className = 'rp-wire ' + dir; dot.style.animation = 'none'; void dot.offsetWidth; dot.style.animation = ''; };
  const add = (s, n) => { const li = el('li', 'on'); li.append(el('i', '', String(n)), document.createTextNode(s.label)); log.append(li); live.textContent = s.label; };
  const step = () => { if (i >= steps.length) { timer = null; played.add(key); return; } const s = steps[i++]; add(s, i); send(s.dir); s.apply(st); setTimeout(() => { paint(); flash(); }, 650); timer = setTimeout(step, STEP_MS); };
  const reset = () => { clearTimeout(timer); i = 0; st.status = 'New'; st.reason = ''; st.tasks = 0; log.replaceChildren(); wire.className = 'rp-wire'; paint(); };
  const final = () => { clearTimeout(timer); reset(); steps.forEach((s, n) => { add(s, n + 1); s.apply(st); }); i = steps.length; paint(); played.add(key); };
  again.onclick = () => { reset(); timer = setTimeout(step, 300); };
  skip.onclick = final;
  paint();
  if (played.has(key)) final(); else { setTimeout(() => { if (box.isConnected) box.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 120); timer = setTimeout(step, 900); }
  return box;
}

window.AG = Object.assign(window.AG || {}, { replay });
})();
