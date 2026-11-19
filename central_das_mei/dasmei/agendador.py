"""Serviço em segundo plano.

- Agenda a rotina (padrão: todo dia às 07:00) com APScheduler;
- a cada minuto: envia sinal de vida ao gestor, atende o botão "Executar agora"
  da tela, recarrega a configuração da tela e retoma rotinas interrompidas;
- faz backup diário do banco local (mantém 30);
- impede duas cópias do serviço ao mesmo tempo.
O Agendador de Tarefas do Windows inicia este serviço ao entrar no Windows.
"""
from __future__ import annotations

import datetime as dt
import logging
import socket
import threading
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .banco import Banco, agora
from .gestor import COL_CMD
from .motor import Motor

log = logging.getLogger("dasmei")
DIAS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
PORTA_TRAVA = 47851


def gatilho(rotina) -> CronTrigger:
    h, m = (int(x) for x in rotina.horario.split(":"))
    dias = ",".join(DIAS[int(d)] for d in sorted(set(rotina.dias_semana)))
    return CronTrigger(hour=h, minute=m, day_of_week=dias)


def trava_instancia():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORTA_TRAVA))
    except OSError:
        s.close()
        return None
    s.listen(1)
    return s


def backup_diario(banco: Banco, pasta: Path, hoje: dt.date, manter=30) -> Path | None:
    pasta = Path(pasta)
    alvo = pasta / f"dasmei-{hoje:%Y%m%d}.db"
    if alvo.exists():
        return None
    banco.backup(alvo)
    antigos = sorted(pasta.glob("dasmei-*.db"))
    for p in antigos[:-manter]:
        p.unlink(missing_ok=True)
    return alvo


class Servico:
    def __init__(self, cfg, banco: Banco, gestor, fabrica_serpro, intervalo=60):
        self.cfg, self.banco, self.gestor, self.fabrica = cfg, banco, gestor, fabrica_serpro
        self.intervalo = intervalo
        self.sched = BackgroundScheduler(timezone="America/Sao_Paulo")
        self._rodando = threading.Lock()
        self._assinatura = None
        self._ultima_retomada = 0.0
        self.parar = threading.Event()

    def motor(self):
        return Motor(self.cfg, self.banco, self.gestor, self.fabrica)

    def executar(self, origem="agendada", somente=None):
        if not self._rodando.acquire(blocking=False):
            log.info("Já existe uma rotina em andamento; pedido '%s' ignorado.", origem)
            return None
        try:
            return self.motor().executar(origem, somente)
        except Exception:  # noqa: BLE001 - o serviço nunca cai por causa de uma rotina
            log.exception("Rotina '%s' falhou", origem)
            return None
        finally:
            self._rodando.release()

    def reagendar(self):
        rotina = self.motor().rotina()
        ass = (rotina.horario, tuple(sorted(rotina.dias_semana)))
        if ass != self._assinatura:
            if self.sched.get_job("rotina"):
                self.sched.remove_job("rotina")
            self.sched.add_job(self.executar, gatilho(rotina), id="rotina", kwargs={"origem": "agendada"},
                               misfire_grace_time=3 * 3600, coalesce=True, max_instances=1)
            self._assinatura = ass
            log.info("Rotina agendada: %s nos dias %s", rotina.horario, ass[1])

    def proxima(self):
        j = self.sched.get_job("rotina")
        return j.next_run_time.isoformat(timespec="minutes") if j and j.next_run_time else None

    def ciclo(self):
        try:
            self.reagendar()
        except Exception as e:  # noqa: BLE001
            log.warning("Não consegui ler a configuração da tela: %s", e)
        m = self.motor()
        m.status_robo(proximaExecucao=self.proxima(), servicoAtivo=True)
        try:
            backup_diario(self.banco, self.cfg.pasta_backup, dt.date.today())
        except Exception as e:  # noqa: BLE001
            log.error("Backup diário falhou: %s", e)
        # retoma rotina interrompida (portal fora do ar) a cada 30 min
        if self.banco.execucao_aberta() and time.time() - self._ultima_retomada > 1800 and not self._rodando.locked():
            self._ultima_retomada = time.time()
            threading.Thread(target=self.executar, kwargs={"origem": "retomada"}, daemon=True).start()
        # botão "Executar agora" da tela
        try:
            for cid, cmd in self.gestor.comandos_pendentes():
                if cmd.get("acao") != "executar" or self._rodando.locked():
                    continue
                cmd.update(status="em_andamento", inicio=agora())
                self.gestor.gravar(COL_CMD, cid, cmd)
                threading.Thread(target=self._atender, args=(cid, cmd), daemon=True).start()
                break
        except Exception as e:  # noqa: BLE001
            log.warning("Falha ao ler pedidos da tela: %s", e)

    def _atender(self, cid, cmd):
        somente = cmd.get("empresaIds") or None
        r = self.executar("manual", somente)
        cmd.update(status="concluido" if r else "erro", fim=agora(), execucaoId=(r or {}).get("id"))
        try:
            self.gestor.gravar(COL_CMD, cid, cmd)
        except Exception as e:  # noqa: BLE001
            log.warning("Pedido %s concluído, mas não consegui avisar a tela: %s", cid, e)

    def rodar(self):
        self.sched.start()
        log.info("Serviço Central de DAS MEI iniciado.")
        try:
            while not self.parar.is_set():
                self.ciclo()
                self.parar.wait(self.intervalo)
        finally:
            self.sched.shutdown(wait=False)
            try:
                self.motor().status_robo(servicoAtivo=False, executando=False)
            except Exception:  # noqa: BLE001
                pass
