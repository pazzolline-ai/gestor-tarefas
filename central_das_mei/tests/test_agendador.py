import datetime as dt
from zoneinfo import ZoneInfo

from dasmei.agendador import Servico, backup_diario, gatilho, trava_instancia
from dasmei.config import Rotina


def test_gatilho_padrao_7h():
    t = gatilho(Rotina())
    tz = ZoneInfo("America/Sao_Paulo")
    prox = t.get_next_fire_time(None, dt.datetime(2026, 11, 19, 8, 0, tzinfo=tz))
    assert (prox.date(), prox.hour, prox.minute) == (dt.date(2026, 11, 20), 7, 0)


def test_gatilho_dias_uteis():
    t = gatilho(Rotina(horario="06:30", dias_semana=[0, 1, 2, 3, 4]))
    tz = ZoneInfo("America/Sao_Paulo")
    prox = t.get_next_fire_time(None, dt.datetime(2026, 11, 20, 7, 0, tzinfo=tz))   # sexta depois do horário
    assert prox.weekday() == 0 and (prox.hour, prox.minute) == (6, 30)


def test_rotina_invalida_da_tela_e_ignorada():
    r = Rotina().mesclar({"horario": "25:99"})
    assert r.horario == "07:00"
    assert Rotina().mesclar({"horario": "06:15", "campo_estranho": 1}).horario == "06:15"


def test_backup_rotativo(banco, tmp_path):
    for i in range(35):
        backup_diario(banco, tmp_path / "bk", dt.date(2026, 1, 1) + dt.timedelta(days=i))
    assert len(list((tmp_path / "bk").glob("dasmei-*.db"))) == 30
    assert backup_diario(banco, tmp_path / "bk", dt.date(2026, 2, 4)) is None   # já existe hoje


def test_servico_atende_botao_executar_agora(cfg, banco, gestor, fabrica):
    gestor.gravar("dasmei_comandos", "c1", {"acao": "executar", "status": "pendente", "empresaIds": ["e2"]})
    s = Servico(cfg, banco, gestor, fabrica)
    s.sched.start(paused=True)
    try:
        s.ciclo()
        import time
        for _ in range(100):
            if gestor.ler_doc("dasmei_comandos", "c1")["status"] in ("concluido", "erro"):
                break
            time.sleep(0.05)
    finally:
        s.sched.shutdown(wait=False)
    cmd = gestor.ler_doc("dasmei_comandos", "c1")
    assert cmd["status"] == "concluido" and cmd["execucaoId"]
    st = gestor.ler_doc("dasmei_robo", "status")
    assert st["servicoAtivo"] and st["proximaExecucao"]
    assert list(cfg.pasta_backup.glob("dasmei-*.db"))


def test_reagenda_quando_tela_muda_horario(cfg, banco, gestor, fabrica):
    s = Servico(cfg, banco, gestor, fabrica)
    s.sched.start(paused=True)
    try:
        s.reagendar()
        assert s.sched.get_job("rotina").trigger.fields[5].expressions[0].first == 7
        gestor.gravar("dasmei_robo", "config", {"horario": "05:45"})
        s.reagendar()
        assert s.sched.get_job("rotina").trigger.fields[5].expressions[0].first == 5
    finally:
        s.sched.shutdown(wait=False)


def test_uma_instancia_so():
    a = trava_instancia()
    try:
        assert a is not None and trava_instancia() is None
    finally:
        a.close()


def test_servico_abre_sessao_assistida_pelo_pedido_da_tela(cfg, banco, gestor, fabrica, monkeypatch):
    import time
    from dasmei import assistido
    chamadas = []

    class Falsa:
        def __init__(self, *a, **k):
            pass

        def executar(self, somente=None):
            chamadas.append(somente)
            return {"id": "sessao-1"}
    monkeypatch.setattr(assistido, "SessaoAssistida", Falsa)
    gestor.gravar("dasmei_comandos", "c9", {"acao": "assistido", "status": "pendente", "empresaIds": ["e1"]})
    s = Servico(cfg, banco, gestor, fabrica)
    s.sched.start(paused=True)
    try:
        s.ciclo()
        for _ in range(100):
            if gestor.ler_doc("dasmei_comandos", "c9")["status"] == "concluido":
                break
            time.sleep(0.05)
    finally:
        s.sched.shutdown(wait=False)
    assert chamadas == [["e1"]] and gestor.ler_doc("dasmei_comandos", "c9")["execucaoId"] == "sessao-1"
