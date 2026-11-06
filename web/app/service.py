"""Durable single-operator workflow. Secrets stay in the trusted backend."""
import copy
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

from connector.agent_api import AgentClient
from connector.auth import get_token
from connector.config import ConfigError, SalesforceConfig
from connector.ids import key15
from connector.rest import SalesforceRest
from connector.snapshot import utc_now
from connector.transport import UrllibTransport
from contracts.plan_hash import approval_is_valid, compute_plan_hash, with_hash
from connector.auth import AuthError
from orchestrator.run import RunBlocked, execute_run
from orchestrator.store import EvidenceStore
from planner import bind_case, create_plan, ready_for_approval
from planner import policy
from planner.context import parse_action, parse_metadata
from planner.service import _validators
from .mode import demo_mode
from audit.explain import explain as audit_explain
from audit.run import AuditBlocked, run_audit
from planner.client import VultrChatClient
from planner.config import PlannerConfig
from planner.errors import PlannerError


class WorkflowError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Workflow:
    def __init__(self, root=None, generate=None, execute=None):
        self.root = Path(root or os.environ.get('ACTION_GUARD_DATA_DIR', 'runs/web'))
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.db = self.root / 'workflow.sqlite3'
        self.generate = generate or self._generate
        self.execute = execute or self._execute
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, target TEXT UNIQUE NOT NULL,
                body TEXT NOT NULL);
            ''')
        self.db.chmod(0o600)

    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        db.execute('PRAGMA busy_timeout=10000')
        return db

    def _get(self, db, table, key):
        row = db.execute(f'SELECT body FROM {table} WHERE id=?', (key,)).fetchone()
        if not row:
            raise WorkflowError(404, 'Record not found.')
        return json.loads(row[0])

    def _put(self, db, table, key, body):
        db.execute(f'UPDATE {table} SET body=? WHERE id=?', (json.dumps(body), key))

    def metadata(self):
        path = os.environ.get('SF_METADATA_PATH')
        if not path:
            raise WorkflowError(503, 'Configure SF_METADATA_PATH no servidor.')
        try:
            raw = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            raise WorkflowError(503, 'Metadata file missing or unreadable on the server.') from None
        if not isinstance(raw, dict) or raw.get('source') != 'salesforce_describe':
            raise WorkflowError(422, 'This flow requires Salesforce Describe metadata.')
        parse_metadata(raw)
        return raw

    def _generate(self, rule, meta, action):
        res = create_plan(rule, meta, action, UrllibTransport())
        return res.plan, {'model': res.model, 'served_model': res.served_model,
                          'usage': res.usage, 'calls': res.calls, 'warnings': res.warnings,
                          'metadata_source': res.metadata_source, 'metadata_collected_at': res.metadata_collected_at}

    def create(self, text, reason):
        meta = self.metadata()
        action = {'process': 'close_case', 'closure_reason': reason,
                  'task_subject': 'Action Guard - Case closure follow-up'}
        rule = {'schema_version': '1.0', 'rule_id': 'rule-' + uuid.uuid4().hex,
                'process': 'close_case', 'text_pt': text}
        plan, generation = self.generate(rule, meta, action)
        plan = copy.deepcopy(plan)
        plan['approval'] = None
        plan = with_hash(plan)
        entry = {'plan': plan, 'generation': generation, 'metadata': meta, 'action': action}
        self.validate(entry, plan)
        with self.connect() as db:
            db.execute('INSERT INTO plans VALUES (?,?)', (plan['plan_id'], json.dumps(entry)))
        return plan

    def get(self, key):
        with self.connect() as db:
            return self._get(db, 'plans', key)['plan']

    def info(self, key):
        with self.connect() as db:
            entry = self._get(db, 'plans', key)
        return {'generation': entry['generation'], 'pending': ready_for_approval(entry['plan'])}

    def validate(self, entry, plan):
        schema, sem = policy.validate(plan, parse_metadata(entry['metadata']), parse_action(entry['action']),
                                      _validators()['test_plan'])
        if schema or sem:
            raise WorkflowError(422, 'Invalid plan: ' + '; '.join((schema + sem)[:5]))
        _, issues, _ = policy.assemble(plan, {'rule_id': plan['rule_id']}, parse_action(entry['action']),
                                       plan_id=plan['plan_id'])
        if issues:
            raise WorkflowError(422, 'The plan must preserve the process invariants.')

    def edit(self, key, expected_hash, proposed=None, case_id=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            entry = self._get(db, 'plans', key)
            old = entry['plan']
            if old['plan_hash'] != expected_hash:
                raise WorkflowError(409, 'The plan changed. Reload before editing.')
            if case_id is not None:
                plan = bind_case(old, case_id)
            else:
                plan = copy.deepcopy(proposed)
                plan.update(plan_id=key, rule_id=old['rule_id'], plan_version=old['plan_version'] + 1, approval=None)
                # Action and target are server-owned; binding has its own explicit route.
                if plan.get('preconditions') != old.get('preconditions'):
                    raise WorkflowError(422, 'Mandatory preconditions must be preserved.')
                if plan.get('rule_coverage') != old.get('rule_coverage'):
                    raise WorkflowError(422, 'Rule coverage is assigned by the server and cannot be edited.')
                if plan.get('action') != old['action']:
                    raise WorkflowError(422, 'The action and the reason are fixed. Generate another plan to change the reason.')
                plan = with_hash(plan)
            self.validate(entry, plan)
            entry['plan'] = plan
            self._put(db, 'plans', key, entry)
        return plan

    def approve(self, key, expected_hash, actor, acknowledged=()):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            entry = self._get(db, 'plans', key)
            plan = entry['plan']
            if plan['plan_hash'] != expected_hash or compute_plan_hash(plan) != expected_hash:
                raise WorkflowError(409, 'The hash changed. Review the current plan.')
            if ready_for_approval(plan):
                raise WorkflowError(409, 'Bind a Case before approval.')
            self.validate(entry, plan)
            clauses = sorted(i['clause_id'] for i in plan.get('rule_coverage') or [])
            if sorted(set(acknowledged)) != clauses:
                raise WorkflowError(409, 'Confirm the handling of every clause of the rule (covered, not verified or in conflict) before approving.')
            plan['approval'] = {'approved_by': actor, 'approved_at': utc_now(), 'approved_plan_hash': expected_hash}
            if clauses:
                plan['approval']['coverage_acknowledged'] = clauses
            self._put(db, 'plans', key, entry)
        return plan

    def audit(self, key, case_ids, since, modified_by, limit, explain):
        """Auditoria SOMENTE LEITURA com o plano aprovado como modelo da regra. Nao reserva Case nem executa acao."""
        with self.connect() as db:
            plan = self._get(db, 'plans', key)['plan']
        if not approval_is_valid(plan):
            raise WorkflowError(409, 'Approve the current plan version before auditing.')
        cfg = SalesforceConfig.from_env()
        http = UrllibTransport()
        try:
            rest = SalesforceRest(cfg, get_token(cfg, http), http)
            report = run_audit(plan, rest, case_ids=case_ids, since=since, modified_by=modified_by, limit=limit)
        except AuditBlocked as e:
            raise WorkflowError(422, str(e)) from None
        except ValueError as e:
            raise WorkflowError(422, str(e)) from None
        except AuthError:
            raise WorkflowError(502, 'Salesforce authentication failed.') from None
        if explain:
            try:
                audit_explain(report, VultrChatClient(PlannerConfig.from_env(), http))
            except PlannerError as e:
                report['summary']['model_error'] = e.category
        EvidenceStore(self.root / 'audits', report['audit_id']).save('audit_report', report)
        return report

    def reserve(self, key, expected_hash):
        if demo_mode():
            raise WorkflowError(403, "Demo mode: real execution is disabled.")
        # Configuration must be present before a durable reservation is consumed.
        cfg = SalesforceConfig.from_env()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            entry = self._get(db, 'plans', key)
            plan = entry['plan']
            if plan['plan_hash'] != expected_hash or not approval_is_valid(plan):
                raise WorkflowError(409, 'Run only the current approved hash.')
            self.validate(entry, plan)
            if ready_for_approval(plan):
                raise WorkflowError(409, 'The plan cannot be run yet.')
            run_id = 'run-' + uuid.uuid4().hex
            record = {'run_id': run_id, 'state': 'queued', 'plan': plan, 'generation': entry['generation']}
            target = cfg.my_domain + '|' + key15(plan['action']['input']['case_id'])
            try:
                db.execute('INSERT INTO runs VALUES (?,?,?)', (run_id, target, json.dumps(record)))
            except sqlite3.IntegrityError:
                raise WorkflowError(409, 'An attempt already exists for this Case. Check the evidence; do not repeat.')
        return run_id

    def work(self, run_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = self._get(db, 'runs', run_id)
            if record['state'] != 'queued':
                return
            record['state'] = 'running'
            self._put(db, 'runs', run_id, record)
        try:
            if demo_mode():
                raise RunBlocked('Demo mode: real execution is disabled.')
            record['report'] = self.execute(record['plan'], run_id)
            record['state'] = 'completed'
        except Exception as e:
            sent = self._maybe_sent(run_id, e)
            if sent is False:
                # Nenhum pedido chegou ao agente: a reserva e liberada (o historico fica) para uma nova tentativa.
                record['state'] = 'blocked'
                record['sent'] = False
                record['error'] = 'Run blocked before sending; no action was sent to the agent.'
                if isinstance(e, RunBlocked):
                    record['blocked_reason'] = str(e)[:300]
                self._release(run_id)
            else:
                # Possivelmente enviada: nunca expor excecao bruta nem repetir a acao.
                record['state'] = 'error'
                record['sent'] = True
                record['error'] = 'Run interrupted after possible sending; reconcile the evidence before a new attempt.'
        with self.connect() as db:
            self._put(db, 'runs', run_id, record)

    def _maybe_sent(self, run_id, exc):
        """False somente quando ha base: RunBlocked (portoes anteriores ao envio) ou OAuth/config antes de qualquer pedido."""
        if isinstance(exc, (RunBlocked, AuthError, ConfigError)):
            request_saved = (self.root / 'evidence' / run_id / 'agent_request.json').exists()
            return None if request_saved else False
        return None

    def _release(self, run_id):
        with self.connect() as db:
            db.execute('UPDATE runs SET target = target || ? WHERE id = ?', ('#released:' + run_id, run_id))

    def _execute(self, plan, run_id):
        if demo_mode():
            raise RunBlocked("Demo mode: real execution is disabled.")
        cfg = SalesforceConfig.from_env()
        transport = UrllibTransport()
        token = get_token(cfg, transport)
        store = EvidenceStore(self.root / 'evidence', run_id)
        return execute_run(plan, case_id=plan['action']['input']['case_id'], run_id=run_id,
                           rest=SalesforceRest(cfg, token, transport),
                           agent=AgentClient(cfg, token, transport, utc_now), store=store, sleep=time.sleep)

    def history(self, key):
        with self.connect() as db:
            self._get(db, 'plans', key)
            records = [json.loads(row[0]) for row in db.execute('SELECT body FROM runs ORDER BY rowid DESC')]
        return [{'run_id': r['run_id'], 'state': r['state']}
                for r in records if r['plan']['plan_id'] == key]

    def run(self, key):
        with self.connect() as db:
            item = self._get(db, 'runs', key)
        return {k: v for k, v in item.items() if k not in ('plan', 'generation')}
