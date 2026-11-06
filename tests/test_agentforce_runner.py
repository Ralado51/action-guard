import json

from agentforce_runner.__main__ import main
from connector.ids import to_sfid18
from connector.transport import Response
from tests.test_salesforce_integration import ENV

CASE = to_sfid18("500SYN000000001")


class Fake:
    def __init__(self, subject="[SYNTHETIC] x", message_status=200):
        self.subject, self.message_status, self.sent = subject, message_status, 0

    def request(self, method, url, *, headers=None, body=None, timeout=30.0):
        if url.endswith("/services/oauth2/token"):
            return Response(200, {"access_token": "T", "instance_url": "https://x.my.salesforce.com"})
        if method == "GET":
            return Response(200, {"done": True, "records": [{"Subject": self.subject}]})
        if url.endswith("/sessions"):
            return Response(200, {"sessionId": "s1"})
        if url.endswith("/messages"):
            self.sent += 1
            return Response(self.message_status, {"messages": [{"type": "Inform", "message": "Done."}]})
        return Response(200, None)


def env(monkeypatch, tmp_path):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SF_CLIENT_ID", "i"); monkeypatch.setenv("SF_CLIENT_SECRET", "s")
    (tmp_path / "a.json").write_text(json.dumps({"case_ids": [CASE]}))
    return str(tmp_path / "a.json")


def test_refuses_without_confirm_write(monkeypatch, tmp_path, capsys):
    a = env(monkeypatch, tmp_path); f = Fake()
    assert main(["run", "--authorized", a], transport=f) == 1 and f.sent == 0


def test_sends_once_and_records_source_and_claim(monkeypatch, tmp_path):
    a = env(monkeypatch, tmp_path); f = Fake()
    assert main(["run", "--authorized", a, "--confirm-write"], transport=f) == 0
    claims = json.loads(next(tmp_path.glob("agentforce-run-*/claims.json")).read_text())
    assert f.sent == 1 and claims[CASE]["source"] == "agentforce" and claims[CASE]["final_message"] == "Done."


def test_unmarked_case_is_never_sent(monkeypatch, tmp_path):
    a = env(monkeypatch, tmp_path); f = Fake(subject="Real customer")
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    assert f.sent == 0


def test_server_error_after_send_is_uncertain_and_stops(monkeypatch, tmp_path, capsys):
    a = env(monkeypatch, tmp_path); f = Fake(message_status=500)
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    assert f.sent == 1 and "uncertain" in capsys.readouterr().out


def test_second_run_never_resends_the_same_case(monkeypatch, tmp_path):
    a = env(monkeypatch, tmp_path); f = Fake()
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    assert f.sent == 1


def test_cases_from_earlier_runs_are_imported_as_already_handled(monkeypatch, tmp_path):
    a = env(monkeypatch, tmp_path); f = Fake()
    old = tmp_path / "vultr-run-abcd1234"; old.mkdir()
    (old / (CASE[:15] + ".json")).write_text("{}")
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    assert f.sent == 0


def test_crash_after_reservation_still_blocks_reuse(monkeypatch, tmp_path):
    from connector.ledger import Ledger
    a = env(monkeypatch, tmp_path); f = Fake()
    assert Ledger(tmp_path).reserve(CASE, "agentforce")          # reserved, then the process "died"
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    assert f.sent == 0


def test_rejection_after_send_is_not_called_proof_of_no_action(monkeypatch, tmp_path, capsys):
    a = env(monkeypatch, tmp_path); f = Fake(message_status=400)
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    out = capsys.readouterr().out
    assert "does not prove that no action ran" in out and "before the action ran" not in out


def test_rejection_without_session_says_nothing_was_sent(monkeypatch, tmp_path, capsys):
    a = env(monkeypatch, tmp_path)

    class NoSession(Fake):
        def request(self, method, url, **kw):
            if url.endswith("/sessions") and method == "POST":
                return Response(403, {"message": "no"})
            return super().request(method, url, **kw)
    f = NoSession()
    main(["run", "--authorized", a, "--confirm-write"], transport=f)
    assert f.sent == 0 and "no message was sent" in capsys.readouterr().out
