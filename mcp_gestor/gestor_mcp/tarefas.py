"""Regras das tarefas, no mesmo formato que a tela grava."""
from __future__ import annotations

import datetime as dt
import random
import string
import time

from .banco import Banco, ErroGestor

STATUS = {
    "afazer": "A fazer",
    "andamento": "Em andamento",
    "aguard_cliente": "Aguardando cliente",
    "aguard_orgao": "Aguardando órgão",
    "concluida": "Concluída",
}
PRIORIDADES = ("normal", "media", "alta", "urgente")


def agora() -> str:
    return dt.datetime.now().strftime("%Y-%m-%dT%H:%M")


def hoje() -> str:
    return dt.date.today().isoformat()


def novo_id() -> str:
    """Mesmo formato do uid() da tela: base36 do horário + 5 caracteres."""
    n, b36 = int(time.time() * 1000), ""
    dig = string.digits + string.ascii_lowercase
    while n:
        n, r = divmod(n, 36)
        b36 = dig[r] + b36
    return b36 + "".join(random.choices(dig, k=5))


def _norm(s) -> str:
    return str(s or "").strip().lower()


def _validar_data(d: str | None, campo="prazo") -> str:
    if not d:
        return ""
    try:
        return dt.date.fromisoformat(d[:10]).isoformat()
    except ValueError:
        raise ErroGestor(f"{campo} inválido: use AAAA-MM-DD (recebido: {d!r})")


class Tarefas:
    def __init__(self, banco: Banco):
        self.b = banco

    # ---------- apoio ----------
    def _empresas(self) -> dict[str, dict]:
        return {i: d for i, d in self.b.ler_col("empresas") if isinstance(d, dict)}

    @staticmethod
    def _nome_empresa(e: dict | None) -> str:
        return (e or {}).get("fantasia") or (e or {}).get("razao") or ""

    def _resumo(self, tid: str, t: dict, emps: dict) -> dict:
        prazo = t.get("prazo") or ""
        return {
            "id": tid,
            "titulo": t.get("titulo", ""),
            "status": t.get("status", ""),
            "responsavel": t.get("responsavel", ""),
            "prazo": prazo,
            "atrasada": bool(prazo) and t.get("status") != "concluida" and prazo[:10] < hoje(),
            "prioridade": t.get("prioridade", ""),
            "empresa": self._nome_empresa(emps.get(t.get("empresaId"))) if t.get("empresaId") else "",
            "categoria": t.get("categoria", ""),
        }

    def _ler(self, tid: str) -> dict:
        t = self.b.ler_doc("tarefas", tid)
        if not isinstance(t, dict):
            raise ErroGestor(f"Tarefa {tid!r} não encontrada")
        return t

    def _salvar(self, tid: str, t: dict, tipo: str, txt: str):
        now = agora()
        t["atualizadoEm"] = now
        t.setdefault("hist", []).append({"em": now, "tipo": tipo, "txt": txt, "por": self.b.nome_usuario})
        self.b.gravar("tarefas", tid, t)

    # ---------- leitura ----------
    def listar(self, status=None, responsavel=None, empresa=None, texto=None,
               somente_atrasadas=False, incluir_concluidas=False, limite=50) -> list[dict]:
        emps = self._empresas()
        out = []
        for tid, t in self.b.ler_col("tarefas"):
            if not isinstance(t, dict) or t.get("excluida"):
                continue
            r = self._resumo(tid, t, emps)
            if status:
                if r["status"] != status:
                    continue
            elif not incluir_concluidas and r["status"] == "concluida":
                continue
            if responsavel and _norm(responsavel) not in _norm(r["responsavel"]):
                continue
            if empresa and _norm(empresa) not in _norm(r["empresa"]):
                continue
            if texto and _norm(texto) not in _norm(t.get("titulo")) + " " + _norm(t.get("descricao")):
                continue
            if somente_atrasadas and not r["atrasada"]:
                continue
            out.append(r)
        out.sort(key=lambda r: (r["prazo"] or "9999", r["titulo"].lower()))
        return out[: max(1, min(int(limite), 500))]

    def ver(self, tid: str) -> dict:
        t = self._ler(tid)
        r = self._resumo(tid, t, self._empresas())
        r.update({k: t.get(k, "") for k in ("descricao", "obs", "solicitante", "departamento",
                                           "criadoEm", "atualizadoEm", "concluidoEm")})
        r["historico"] = (t.get("hist") or [])[-20:]
        return r

    def resumo(self) -> dict:
        abertas = self.listar(limite=500)
        por_status, por_resp = {}, {}
        for r in abertas:
            por_status[STATUS.get(r["status"], r["status"])] = por_status.get(STATUS.get(r["status"], r["status"]), 0) + 1
            k = r["responsavel"] or "(sem responsável)"
            por_resp[k] = por_resp.get(k, 0) + 1
        return {
            "abertas": len(abertas),
            "atrasadas": sum(r["atrasada"] for r in abertas),
            "vencem_hoje": sum(r["prazo"][:10] == hoje() for r in abertas),
            "por_status": por_status,
            "por_responsavel": dict(sorted(por_resp.items(), key=lambda x: -x[1])),
        }

    def empresas(self, texto=None, limite=30) -> list[dict]:
        out = []
        for i, e in self._empresas().items():
            if e.get("inativa"):
                continue
            nome = self._nome_empresa(e)
            if texto and _norm(texto) not in _norm(nome) + " " + _norm(e.get("razao")) + " " + _norm(e.get("cnpj")):
                continue
            out.append({"id": i, "nome": nome, "razao": e.get("razao", ""), "cnpj": e.get("cnpj", ""),
                        "regime": e.get("regime", "")})
        out.sort(key=lambda x: x["nome"].lower())
        return out[:limite]

    def equipe(self) -> list[dict]:
        out = [{"nome": p.get("nome", ""), "departamento": p.get("departamento", "")}
               for _, p in self.b.ler_col("equipe") if isinstance(p, dict) and p.get("ativo", True)]
        return sorted(out, key=lambda x: x["nome"].lower())

    # ---------- escrita ----------
    def criar(self, titulo, responsavel=None, prazo=None, prioridade="normal", empresa_id=None,
              descricao="", categoria="") -> dict:
        titulo = (titulo or "").strip()
        if not titulo:
            raise ErroGestor("Informe o título da tarefa")
        if prioridade and prioridade not in PRIORIDADES:
            raise ErroGestor(f"Prioridade inválida. Use: {', '.join(PRIORIDADES)}")
        if empresa_id and empresa_id not in self._empresas():
            raise ErroGestor(f"Empresa {empresa_id!r} não encontrada (use listar_empresas)")
        now, me = agora(), self.b.nome_usuario
        t = {
            "titulo": titulo, "status": "afazer", "categoria": categoria or "", "solicitante": me,
            "responsavel": responsavel or me, "departamento": "", "descricao": descricao or "", "obs": "",
            "prazo": _validar_data(prazo), "prioridade": prioridade or "normal", "empresaId": empresa_id or None,
            "criadoEm": now, "atualizadoEm": now, "concluidoEm": "",
            "hist": [{"em": now, "tipo": "criada", "txt": "Tarefa criada pelo Claude (MCP)", "por": me}],
        }
        tid = novo_id()
        self.b.gravar("tarefas", tid, t)
        return {"id": tid, **self._resumo(tid, t, self._empresas())}

    def mudar_status(self, tid, status, observacao="") -> dict:
        if status not in STATUS:
            raise ErroGestor(f"Status inválido. Use: {', '.join(STATUS)}")
        t = self._ler(tid)
        anterior = t.get("status")
        t["status"] = status
        t["concluidoEm"] = agora() if status == "concluida" else ""
        txt = f"{STATUS.get(anterior, anterior)} → {STATUS[status]}" + (f": {observacao}" if observacao else "")
        self._salvar(tid, t, "status", txt)
        return self.ver(tid)

    def editar(self, tid, titulo=None, responsavel=None, prazo=None, prioridade=None, descricao=None) -> dict:
        t = self._ler(tid)
        mud = []
        if titulo is not None and titulo.strip():
            t["titulo"] = titulo.strip(); mud.append("título")
        if responsavel is not None:
            t["responsavel"] = responsavel; mud.append(f"responsável: {responsavel}")
        if prazo is not None:
            t["prazo"] = _validar_data(prazo); mud.append(f"prazo: {t['prazo'] or 'sem prazo'}")
        if prioridade is not None:
            if prioridade not in PRIORIDADES:
                raise ErroGestor(f"Prioridade inválida. Use: {', '.join(PRIORIDADES)}")
            t["prioridade"] = prioridade; mud.append(f"prioridade: {prioridade}")
        if descricao is not None:
            t["descricao"] = descricao; mud.append("descrição")
        if not mud:
            raise ErroGestor("Nada para alterar")
        self._salvar(tid, t, "editada", "Alterado " + ", ".join(mud))
        return self.ver(tid)

    def anotar(self, tid, texto) -> dict:
        if not (texto or "").strip():
            raise ErroGestor("Escreva a anotação")
        t = self._ler(tid)
        self._salvar(tid, t, "nota", texto.strip())
        return self.ver(tid)
