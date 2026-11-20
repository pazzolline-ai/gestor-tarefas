"""Integração com o Gestor de Tarefas (Supabase).

O robô entra como um usuário próprio ("Robô DAS"), passando pelas mesmas
regras de acesso (RLS) dos demais usuários — sem chave de administrador.
Usa a mesma tabela `docs` do sistema, então a tela atualiza em tempo real:

  empresas              (leitura)   cadastro de clientes já existente
  das                   (mescla)    painel "Guias DAS-MEI" do Início: marca 'emitida'
  dasmei_clientes       (escrita)   situação de cada cliente MEI
  dasmei_execucoes      (escrita)   relatório de cada rotina
  dasmei_robo           (escrita)   'status' (heartbeat) | leitura: 'config'
  dasmei_comandos       (leitura/escrita) pedidos de execução manual pela tela
  dasmei_pagamentos     (leitura)   pagamentos informados na tela, com comprovante conferido
"""
from __future__ import annotations

import datetime as dt
import time

import httpx

from . import cnpj as cnpjmod

COL_EMPRESAS, COL_DAS = "empresas", "das"
COL_CLIENTES, COL_EXEC, COL_ROBO, COL_CMD = "dasmei_clientes", "dasmei_execucoes", "dasmei_robo", "dasmei_comandos"
COL_PAG = "dasmei_pagamentos"   # pagamentos informados na tela (comprovante conferido por uma pessoa)


class ErroGestor(Exception):
    pass


def filtrar_mei(empresas: list[tuple[str, dict]], excluidos=(), somente=()) -> tuple[list[dict], list[dict]]:
    """Separa clientes MEI aptos e os que têm problema de cadastro."""
    aptos, problemas = [], []
    for eid, e in empresas:
        if not isinstance(e, dict) or e.get("regime") != "MEI" or e.get("inativa"):
            continue
        if e.get("guiaMensal") is False or eid in set(excluidos or ()):
            continue
        if somente and eid not in set(somente):
            continue
        nome = e.get("fantasia") or e.get("razao") or "(sem nome)"
        c = cnpjmod.limpar(e.get("cnpj"))
        item = {"empresa_id": eid, "cnpj": c, "nome": nome}
        if not cnpjmod.valido(c):
            item["problema"] = "CNPJ ausente ou inválido no cadastro da empresa"
            problemas.append(item)
        else:
            aptos.append(item)
    aptos.sort(key=lambda x: x["nome"].lower())
    return aptos, problemas


class GestorBase:
    def ler_col(self, col) -> list[tuple[str, dict]]: ...
    def ler_doc(self, col, did) -> dict | None: ...
    def gravar(self, col, did, data: dict): ...

    def mesclar(self, col, did, parcial: dict):
        atual = self.ler_doc(col, did) or {}
        atual.update(parcial)
        self.gravar(col, did, atual)

    # ---- alto nível ----
    def config_remota(self) -> dict:
        return self.ler_doc(COL_ROBO, "config") or {}

    def clientes_mei(self, excluidos=(), somente=()):
        return filtrar_mei(self.ler_col(COL_EMPRESAS), excluidos, somente)

    def marcar_das_painel(self, empresa_id, comp_iso, info: dict):
        """Alimenta o painel antigo 'Guias DAS-MEI' sem apagar o 'enviada'."""
        did = f"{empresa_id}_{comp_iso}"
        atual = self.ler_doc(COL_DAS, did) or {"empresaId": empresa_id, "comp": comp_iso}
        if not atual.get("emitida"):
            atual["emitida"] = dt.datetime.now().strftime("%Y-%m-%dT%H:%M")
        atual["robo"] = info
        self.gravar(COL_DAS, did, atual)

    def pagamentos_manuais(self) -> dict:
        return {i: d for i, d in self.ler_col(COL_PAG) if isinstance(d, dict) and d.get("data")}

    def comandos_pendentes(self):
        return [(i, d) for i, d in self.ler_col(COL_CMD) if isinstance(d, dict) and d.get("status") == "pendente"]


class GestorSupabase(GestorBase):
    def __init__(self, url, anon_key, email, senha, transport: httpx.BaseTransport | None = None, timeout=30):
        if not (url and anon_key and email and senha):
            raise ErroGestor("Dados de acesso ao gestor incompletos (URL, chave pública, e-mail ou senha)")
        self.url = url.rstrip("/")
        self._key, self._email, self._senha = anon_key, email, senha
        kw = {"timeout": timeout}
        if transport:
            kw["transport"] = transport
        self._http = httpx.Client(**kw)
        self._tok = None
        self._exp = 0
        self.uid = None
        self.org_id = None

    def fechar(self):
        self._http.close()

    def _auth(self):
        if self._tok and time.time() < self._exp:
            return self._tok
        r = self._http.post(f"{self.url}/auth/v1/token", params={"grant_type": "password"},
                            headers={"apikey": self._key}, json={"email": self._email, "password": self._senha})
        if r.status_code != 200:
            raise ErroGestor(f"Login do robô no gestor recusado (HTTP {r.status_code}). Confira e-mail/senha do usuário Robô DAS.")
        j = r.json()
        self._tok, self._exp = j["access_token"], time.time() + int(j.get("expires_in", 3600)) - 120
        self.uid = j.get("user", {}).get("id")
        if not self.org_id:
            m = self._req("GET", "/rest/v1/membros", params={"select": "org_id,ativo", "user_id": f"eq.{self.uid}"})
            if not m or not m[0].get("ativo", True):
                raise ErroGestor("O usuário do robô não está ativo no gestor (Equipe › Usuários)")
            self.org_id = m[0]["org_id"]
        return self._tok

    def _req(self, metodo, caminho, **kw):
        tok = self._tok if caminho.startswith("/rest/v1/membros") else self._auth()
        h = {"apikey": self._key, "Authorization": f"Bearer {tok}"}
        h.update(kw.pop("headers", {}))
        for t in range(3):
            try:
                r = self._http.request(metodo, self.url + caminho, headers=h, **kw)
            except httpx.TransportError as e:
                if t == 2:
                    raise ErroGestor(f"Sem conexão com o gestor: {e.__class__.__name__}") from e
                time.sleep(2 * (t + 1))
                continue
            if r.status_code >= 500 and t < 2:
                time.sleep(2 * (t + 1))
                continue
            if r.status_code >= 400:
                raise ErroGestor(f"Gestor recusou {metodo} {caminho.split('?')[0]} (HTTP {r.status_code}): {r.text[:200]}")
            return r.json() if r.content else None

    def ler_col(self, col):
        out, de = [], 0
        while True:
            rows = self._req("GET", "/rest/v1/docs", params={"select": "id,data", "col": f"eq.{col}",
                                                             "limit": 1000, "offset": de}) or []
            out.extend((r["id"], r["data"]) for r in rows)
            if len(rows) < 1000:
                return out
            de += 1000

    def ler_doc(self, col, did):
        rows = self._req("GET", "/rest/v1/docs", params={"select": "data", "col": f"eq.{col}", "id": f"eq.{did}"}) or []
        return rows[0]["data"] if rows else None

    def gravar(self, col, did, data):
        self._auth()
        self._req("POST", "/rest/v1/docs", params={"on_conflict": "org_id,col,id"},
                  headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                  json={"org_id": self.org_id, "col": col, "id": did, "data": data})


class GestorMemoria(GestorBase):
    """Gestor em memória (testes e modo simulação)."""
    def __init__(self, docs: dict | None = None):
        self.docs = {c: dict(v) for c, v in (docs or {}).items()}
        self.escritas = []

    def ler_col(self, col):
        return list(self.docs.get(col, {}).items())

    def ler_doc(self, col, did):
        d = self.docs.get(col, {}).get(did)
        return dict(d) if isinstance(d, dict) else d

    def gravar(self, col, did, data):
        self.docs.setdefault(col, {})[did] = data
        self.escritas.append((col, did))
