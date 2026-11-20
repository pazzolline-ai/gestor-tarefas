"""Versão separada: o "gestor" vira um armazenamento local no próprio SQLite.

Mesma interface do GestorSupabase (coleções de documentos JSON), então o motor,
a sessão assistida e o agendador funcionam igual. O cadastro de clientes fica na
coleção `empresas`, com os mesmos campos do Gestor de Tarefas:
  regime ("MEI"), cnpj, razao, fantasia, whatsapp, responsavel, inativa, guiaMensal
"""
from __future__ import annotations

import csv
import io
import json
import re
import uuid

from . import cnpj as cnpjmod
from .banco import Banco, agora
from .gestor import COL_EMPRESAS, GestorBase


class GestorLocal(GestorBase):
    def __init__(self, banco: Banco):
        self.banco = banco
        banco.con.executescript("CREATE TABLE IF NOT EXISTS docs(col TEXT NOT NULL, id TEXT NOT NULL, "
                                "data TEXT NOT NULL, atualizado TEXT, PRIMARY KEY(col, id));")

    def ler_col(self, col):
        return [(r["id"], json.loads(r["data"])) for r in self.banco.todos("SELECT id, data FROM docs WHERE col=?", (col,))]

    def ler_doc(self, col, did):
        r = self.banco.um("SELECT data FROM docs WHERE col=? AND id=?", (col, did))
        return json.loads(r["data"]) if r else None

    def gravar(self, col, did, data):
        self.banco._x("INSERT INTO docs(col,id,data,atualizado) VALUES(?,?,?,?) ON CONFLICT(col,id) DO UPDATE SET "
                      "data=excluded.data, atualizado=excluded.atualizado",
                      (col, did, json.dumps(data, ensure_ascii=False), agora()))

    def apagar(self, col, did):
        self.banco._x("DELETE FROM docs WHERE col=? AND id=?", (col, did))

    # ---------- cadastro de clientes ----------
    def salvar_empresa(self, dados: dict, eid: str | None = None) -> str:
        c = cnpjmod.limpar(dados.get("cnpj"))
        if not cnpjmod.valido(c):
            raise ValueError("CNPJ inválido")
        if not (dados.get("razao") or dados.get("fantasia")):
            raise ValueError("Informe o nome do cliente")
        for i, e in self.ler_col(COL_EMPRESAS):
            if i != eid and cnpjmod.limpar(e.get("cnpj")) == c and not e.get("inativa"):
                raise ValueError(f"Já existe um cliente com este CNPJ ({e.get('fantasia') or e.get('razao')})")
        atual = self.ler_doc(COL_EMPRESAS, eid) if eid else None
        eid = eid or uuid.uuid4().hex[:12]
        d = dict(atual or {"criadoEm": agora()})
        for k in ("razao", "fantasia", "whatsapp", "responsavel", "email", "obs"):
            if k in dados:
                d[k] = str(dados.get(k) or "").strip()
        d.update(cnpj=cnpjmod.formatar(c), regime="MEI", inativa=bool(dados.get("inativa", d.get("inativa", False))),
                 guiaMensal=dados.get("guiaMensal", d.get("guiaMensal", True)) is not False, atualizadoEm=agora())
        self.gravar(COL_EMPRESAS, eid, d)
        self.banco.auditar("cliente_salvo", c, {"id": eid})
        return eid

    def importar(self, nome_arquivo: str, conteudo: bytes) -> dict:
        """Importa CSV ou XLSX. Colunas reconhecidas: CNPJ, Razão social/Nome, Nome fantasia,
        WhatsApp/Telefone, Responsável, E-mail. CNPJ repetido atualiza o cadastro."""
        linhas = _ler_planilha(nome_arquivo, conteudo)
        if not linhas:
            return {"novos": 0, "atualizados": 0, "erros": ["Planilha vazia"]}
        mapa = _mapear(linhas[0])
        if "cnpj" not in mapa:
            return {"novos": 0, "atualizados": 0, "erros": ["Não encontrei a coluna CNPJ na primeira linha"]}
        existentes = {cnpjmod.limpar(e.get("cnpj")): i for i, e in self.ler_col(COL_EMPRESAS) if not e.get("inativa")}
        novos = atualizados = 0
        erros = []
        for n, ln in enumerate(linhas[1:], start=2):
            dados = {k: (ln[i] if i < len(ln) else "") for k, i in mapa.items()}
            if not any(str(v).strip() for v in dados.values()):
                continue
            c = cnpjmod.limpar(dados.get("cnpj"))
            if not dados.get("razao") and not dados.get("fantasia"):
                dados["razao"] = cnpjmod.formatar(c)
            try:
                eid = existentes.get(c)
                nid = self.salvar_empresa(dados, eid)
                existentes[c] = nid
                atualizados += bool(eid)
                novos += not eid
            except ValueError as e:
                erros.append(f"linha {n}: {e}")
        return {"novos": novos, "atualizados": atualizados, "erros": erros}


_COLS = {
    "cnpj": r"cnpj",
    "fantasia": r"fantasia",
    "razao": r"raz[aã]o|nome empresarial|^nome$|^cliente$|^empresa$",
    "whatsapp": r"whats|celular|telefone|fone",
    "responsavel": r"respons|contato|titular",
    "email": r"e-?mail",
}


def _mapear(cab):
    mapa = {}
    for i, h in enumerate(cab):
        t = str(h or "").strip().lower()
        for campo, rx in _COLS.items():
            if campo not in mapa and re.search(rx, t):
                mapa[campo] = i
                break
    return mapa


def _ler_planilha(nome, conteudo):
    if nome.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        return [["" if v is None else str(v) for v in r] for r in ws.iter_rows(values_only=True)]
    texto = None
    for enc in ("utf-8-sig", "cp1252"):
        try:
            texto = conteudo.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if texto is None:
        raise ValueError("Arquivo não é CSV/XLSX legível")
    dialeto = ";" if texto.count(";") >= texto.count(",") else ","
    return [r for r in csv.reader(io.StringIO(texto), delimiter=dialeto)]
