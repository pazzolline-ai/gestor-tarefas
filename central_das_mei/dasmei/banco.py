"""Banco local (SQLite): fila, operações, guias, auditoria e histórico.

O SQLite fica no perfil do usuário do Windows (%LOCALAPPDATA%\\CentralDasMei),
separado dos PDFs. O gestor (Supabase) recebe um resumo para a tela.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
import uuid
from pathlib import Path

ESQUEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS clientes(
  empresa_id TEXT PRIMARY KEY, cnpj TEXT NOT NULL, nome TEXT, situacao TEXT, mensagem TEXT,
  ultima_consulta TEXT, atualizado TEXT);
CREATE TABLE IF NOT EXISTS competencias(
  cnpj TEXT NOT NULL, pa TEXT NOT NULL, status TEXT NOT NULL, vencimento TEXT, mensagem TEXT,
  pago_em TEXT, pago_valor REAL, pago_documento TEXT, pago_evidencia TEXT, atualizado TEXT,
  PRIMARY KEY(cnpj, pa));
CREATE TABLE IF NOT EXISTS guias(
  id INTEGER PRIMARY KEY AUTOINCREMENT, cnpj TEXT NOT NULL, pa TEXT NOT NULL,
  numero_documento TEXT NOT NULL UNIQUE, status TEXT NOT NULL, vencimento TEXT, data_limite TEXT,
  principal REAL, multa REAL, juros REAL, total REAL, arquivo TEXT, sha256 TEXT, tamanho INTEGER,
  extracao TEXT, emitida_em TEXT, substituida INTEGER NOT NULL DEFAULT 0, operacao_id TEXT);
CREATE INDEX IF NOT EXISTS ix_guias_cnpj_pa ON guias(cnpj, pa);
CREATE TABLE IF NOT EXISTS execucoes(
  id TEXT PRIMARY KEY, inicio TEXT, fim TEXT, origem TEXT, estado TEXT, resumo TEXT);
CREATE TABLE IF NOT EXISTS fila(
  execucao_id TEXT NOT NULL, ordem INTEGER NOT NULL, empresa_id TEXT NOT NULL, cnpj TEXT, nome TEXT,
  estado TEXT NOT NULL DEFAULT 'pendente', tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT,
  PRIMARY KEY(execucao_id, empresa_id));
CREATE TABLE IF NOT EXISTS operacoes(
  id TEXT PRIMARY KEY, execucao_id TEXT, chave TEXT NOT NULL, tipo TEXT NOT NULL, cnpj TEXT, pa TEXT,
  estado TEXT NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0, erro TEXT, inicio TEXT, fim TEXT);
CREATE INDEX IF NOT EXISTS ix_op_chave ON operacoes(chave, estado);
CREATE TABLE IF NOT EXISTS auditoria(
  id INTEGER PRIMARY KEY AUTOINCREMENT, quando TEXT NOT NULL, execucao_id TEXT, operacao_id TEXT,
  acao TEXT NOT NULL, cnpj TEXT, detalhe TEXT);
"""


def agora() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def novo_id() -> str:
    return uuid.uuid4().hex


class Banco:
    def __init__(self, caminho: Path | str):
        self.caminho = str(caminho)
        if self.caminho != ":memory:":
            Path(self.caminho).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.con = sqlite3.connect(self.caminho, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(ESQUEMA)

    # ---------- utilidades ----------
    def _x(self, sql, args=()):
        with self._lock:
            return self.con.execute(sql, args)

    def um(self, sql, args=()):
        r = self._x(sql, args).fetchone()
        return dict(r) if r else None

    def todos(self, sql, args=()):
        return [dict(r) for r in self._x(sql, args).fetchall()]

    def fechar(self):
        with self._lock:
            self.con.close()

    # ---------- auditoria ----------
    def auditar(self, acao, cnpj=None, detalhe=None, execucao_id=None, operacao_id=None):
        if isinstance(detalhe, (dict, list)):
            detalhe = json.dumps(detalhe, ensure_ascii=False)
        self._x("INSERT INTO auditoria(quando,execucao_id,operacao_id,acao,cnpj,detalhe) VALUES(?,?,?,?,?,?)",
                (agora(), execucao_id, operacao_id, acao, cnpj, detalhe))

    # ---------- execuções e fila ----------
    def execucao_aberta(self):
        """Rotina automática interrompida (sessões assistidas não são retomadas sozinhas)."""
        return self.um("SELECT * FROM execucoes WHERE estado='em_andamento' AND origem<>'assistida' "
                       "ORDER BY inicio DESC LIMIT 1")

    def fechar_assistidas_abertas(self):
        self._x("UPDATE execucoes SET estado='interrompida', fim=? WHERE estado='em_andamento' AND origem='assistida'",
                (agora(),))

    def nova_execucao(self, origem: str, itens: list[dict]) -> str:
        eid = novo_id()
        with self._lock:
            self.con.execute("BEGIN")
            try:
                self.con.execute("INSERT INTO execucoes(id,inicio,origem,estado) VALUES(?,?,?,?)",
                                 (eid, agora(), origem, "em_andamento"))
                for i, it in enumerate(itens):
                    self.con.execute("INSERT INTO fila(execucao_id,ordem,empresa_id,cnpj,nome) VALUES(?,?,?,?,?)",
                                     (eid, i, it["empresa_id"], it["cnpj"], it.get("nome")))
                self.con.execute("COMMIT")
            except Exception:
                self.con.execute("ROLLBACK")
                raise
        self.auditar("execucao_iniciada", detalhe={"origem": origem, "clientes": len(itens)}, execucao_id=eid)
        return eid

    def fila_pendente(self, eid):
        return self.todos("SELECT * FROM fila WHERE execucao_id=? AND estado='pendente' ORDER BY ordem", (eid,))

    def fila_total(self, eid):
        return self.todos("SELECT * FROM fila WHERE execucao_id=? ORDER BY ordem", (eid,))

    def fila_marcar(self, eid, empresa_id, estado, erro=None):
        self._x("UPDATE fila SET estado=?, erro=?, tentativas=tentativas+1 WHERE execucao_id=? AND empresa_id=?",
                (estado, erro, eid, empresa_id))

    def finalizar_execucao(self, eid, estado, resumo: dict):
        self._x("UPDATE execucoes SET fim=?, estado=?, resumo=? WHERE id=?",
                (agora(), estado, json.dumps(resumo, ensure_ascii=False), eid))
        self.auditar("execucao_" + estado, execucao_id=eid)

    # ---------- operações (identificador único + idempotência) ----------
    def operacao_concluida(self, chave) -> dict | None:
        return self.um("SELECT * FROM operacoes WHERE chave=? AND estado='concluida' ORDER BY fim DESC LIMIT 1", (chave,))

    def iniciar_operacao(self, eid, chave, tipo, cnpj=None, pa=None) -> str:
        oid = novo_id()
        self._x("INSERT INTO operacoes(id,execucao_id,chave,tipo,cnpj,pa,estado,inicio) VALUES(?,?,?,?,?,?,?,?)",
                (oid, eid, chave, tipo, cnpj, pa, "iniciada", agora()))
        return oid

    def concluir_operacao(self, oid, estado="concluida", erro=None, tentativas=1):
        self._x("UPDATE operacoes SET estado=?, erro=?, tentativas=?, fim=? WHERE id=?",
                (estado, erro, tentativas, agora(), oid))

    def operacoes_execucao(self, eid):
        return self.todos("SELECT * FROM operacoes WHERE execucao_id=?", (eid,))

    # ---------- clientes / competências / guias ----------
    def salvar_cliente(self, empresa_id, cnpj, nome, situacao, mensagem=None, consultado=False):
        atual = self.um("SELECT ultima_consulta FROM clientes WHERE empresa_id=?", (empresa_id,))
        uc = agora() if consultado else (atual or {}).get("ultima_consulta")
        self._x("""INSERT INTO clientes(empresa_id,cnpj,nome,situacao,mensagem,ultima_consulta,atualizado)
                   VALUES(?,?,?,?,?,?,?) ON CONFLICT(empresa_id) DO UPDATE SET cnpj=excluded.cnpj,
                   nome=excluded.nome, situacao=excluded.situacao, mensagem=excluded.mensagem,
                   ultima_consulta=excluded.ultima_consulta, atualizado=excluded.atualizado""",
                (empresa_id, cnpj, nome, situacao, mensagem, uc, agora()))

    def cliente(self, empresa_id):
        return self.um("SELECT * FROM clientes WHERE empresa_id=?", (empresa_id,))

    def competencia(self, cnpj, pa):
        return self.um("SELECT * FROM competencias WHERE cnpj=? AND pa=?", (cnpj, pa))

    def competencias(self, cnpj):
        return self.todos("SELECT * FROM competencias WHERE cnpj=? ORDER BY pa", (cnpj,))

    def salvar_competencia(self, cnpj, pa, status, vencimento=None, mensagem=None, pagamento: dict | None = None):
        p = pagamento or {}
        self._x("""INSERT INTO competencias(cnpj,pa,status,vencimento,mensagem,pago_em,pago_valor,pago_documento,pago_evidencia,atualizado)
                   VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(cnpj,pa) DO UPDATE SET status=excluded.status,
                   vencimento=COALESCE(excluded.vencimento, competencias.vencimento), mensagem=excluded.mensagem,
                   pago_em=COALESCE(excluded.pago_em, competencias.pago_em),
                   pago_valor=COALESCE(excluded.pago_valor, competencias.pago_valor),
                   pago_documento=COALESCE(excluded.pago_documento, competencias.pago_documento),
                   pago_evidencia=COALESCE(excluded.pago_evidencia, competencias.pago_evidencia),
                   atualizado=excluded.atualizado""",
                (cnpj, pa, str(status.value if hasattr(status, "value") else status), vencimento, mensagem,
                 p.get("data"), p.get("valor"), p.get("documento"), p.get("evidencia"), agora()))

    def guias(self, cnpj, pa=None, ativas=False):
        sql, a = "SELECT * FROM guias WHERE cnpj=?", [cnpj]
        if pa:
            sql += " AND pa=?"
            a.append(pa)
        if ativas:
            sql += " AND substituida=0"
        return self.todos(sql + " ORDER BY id", a)

    def guia_por_documento(self, numero):
        return self.um("SELECT * FROM guias WHERE numero_documento=?", (numero,))

    def inserir_guia(self, **g) -> int:
        cols = ",".join(g)
        cur = self._x(f"INSERT INTO guias({cols}) VALUES({','.join('?' * len(g))})", tuple(g.values()))
        return cur.lastrowid

    def atualizar_guia(self, gid, **campos):
        sets = ",".join(f"{k}=?" for k in campos)
        self._x(f"UPDATE guias SET {sets} WHERE id=?", (*campos.values(), gid))

    def substituir_guias(self, cnpj, pa, exceto_id):
        self._x("UPDATE guias SET substituida=1 WHERE cnpj=? AND pa=? AND id<>?", (cnpj, pa, exceto_id))

    # ---------- backup ----------
    def backup(self, destino: Path):
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            alvo = sqlite3.connect(str(destino))
            try:
                self.con.backup(alvo)
            finally:
                alvo.close()
        return destino
