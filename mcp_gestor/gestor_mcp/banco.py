"""Acesso aos dados do Gestor de Tarefas (Supabase, tabela `docs`).

Entra como um usuário comum (e-mail e senha), passando pelas mesmas regras de
acesso (RLS) da tela: sem chave de administrador. Cada registro da tela é uma
linha de `docs` com (org_id, col, id, data).
"""
from __future__ import annotations

import time

import httpx
from mcp.server.mcpserver.exceptions import ToolError


class ErroGestor(ToolError):
    """Erro com mensagem clara, repassada ao Claude."""


class Banco:
    """Interface mínima usada pelas ferramentas."""
    nome_usuario = "Claude"

    def ler_col(self, col: str) -> list[tuple[str, dict]]: ...
    def ler_doc(self, col: str, did: str) -> dict | None: ...
    def gravar(self, col: str, did: str, data: dict) -> None: ...


class BancoSupabase(Banco):
    def __init__(self, url, anon_key, email, senha, transport: httpx.BaseTransport | None = None, timeout=30):
        if not (url and anon_key and email and senha):
            raise ErroGestor("Faltam dados de acesso: GESTOR_URL, GESTOR_CHAVE, GESTOR_EMAIL e GESTOR_SENHA")
        self.url = url.rstrip("/")
        self._key, self._email, self._senha = anon_key, email, senha
        kw = {"timeout": timeout}
        if transport:
            kw["transport"] = transport
        self._http = httpx.Client(**kw)
        self._tok, self._exp = None, 0.0
        self.uid = self.org_id = None

    def _auth(self) -> str:
        if self._tok and time.time() < self._exp:
            return self._tok
        r = self._http.post(f"{self.url}/auth/v1/token", params={"grant_type": "password"},
                            headers={"apikey": self._key}, json={"email": self._email, "password": self._senha})
        if r.status_code != 200:
            raise ErroGestor(f"Login no gestor recusado (HTTP {r.status_code}). Confira e-mail e senha.")
        j = r.json()
        self._tok, self._exp = j["access_token"], time.time() + int(j.get("expires_in", 3600)) - 120
        self.uid = (j.get("user") or {}).get("id")
        if not self.org_id:
            m = self._req("GET", "/rest/v1/membros", params={"select": "org_id,nome,ativo", "user_id": f"eq.{self.uid}"},
                          tok=self._tok)
            if not m or not m[0].get("ativo", True):
                raise ErroGestor("Este usuário não está ativo no gestor (Equipe › Usuários)")
            self.org_id = m[0]["org_id"]
            if m[0].get("nome"):
                self.nome_usuario = m[0]["nome"].split(" ")[0]
        return self._tok

    def _req(self, metodo, caminho, tok=None, **kw):
        tok = tok or self._auth()
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
                raise ErroGestor(f"Gestor recusou {metodo} {caminho} (HTTP {r.status_code}): {r.text[:200]}")
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


class BancoMemoria(Banco):
    """Banco em memória (testes)."""
    def __init__(self, docs: dict | None = None, nome_usuario="Claude"):
        self.docs = {c: dict(v) for c, v in (docs or {}).items()}
        self.nome_usuario = nome_usuario

    def ler_col(self, col):
        return list(self.docs.get(col, {}).items())

    def ler_doc(self, col, did):
        d = self.docs.get(col, {}).get(did)
        return dict(d) if isinstance(d, dict) else d

    def gravar(self, col, did, data):
        self.docs.setdefault(col, {})[did] = data
