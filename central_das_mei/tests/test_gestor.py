import json

import httpx
import pytest

from dasmei.gestor import ErroGestor, GestorSupabase, filtrar_mei
from tests.apoio import CNPJ_A, CNPJ_B


def test_filtrar_mei(gestor):
    aptos, probl = gestor.clientes_mei()
    assert [a["empresa_id"] for a in aptos] == ["e1", "e2"]
    assert [p["empresa_id"] for p in probl] == ["e4"] and "CNPJ" in probl[0]["problema"]
    aptos, _ = gestor.clientes_mei(excluidos=["e1"])
    assert [a["empresa_id"] for a in aptos] == ["e2"]
    aptos, _ = gestor.clientes_mei(somente=["e1"])
    assert [a["empresa_id"] for a in aptos] == ["e1"]


def test_painel_das_preserva_enviada(gestor):
    gestor.gravar("das", "e1_2026-10", {"empresaId": "e1", "comp": "2026-10", "enviada": "2026-11-05T10:00"})
    gestor.marcar_das_painel("e1", "2026-10", {"documento": "1"})
    d = gestor.ler_doc("das", "e1_2026-10")
    assert d["enviada"] == "2026-11-05T10:00" and d["emitida"] and d["robo"]["documento"] == "1"


class SupaFalso:
    def __init__(self):
        self.docs = {("empresas", f"id{i}"): {"regime": "MEI", "cnpj": CNPJ_A} for i in range(1500)}
        self.posts = []

    def __call__(self, req):
        p = req.url.path
        if p == "/auth/v1/token":
            b = json.loads(req.content)
            if b["password"] != "certa":
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "TOK", "expires_in": 3600, "user": {"id": "u-robo"}})
        assert req.headers["apikey"] == "anon" and req.headers["Authorization"] == "Bearer TOK"
        q = dict(req.url.params)
        if p == "/rest/v1/membros":
            assert q["user_id"] == "eq.u-robo"
            return httpx.Response(200, json=[{"org_id": "org-1", "ativo": True}])
        if p == "/rest/v1/docs" and req.method == "GET":
            col = q["col"][3:]
            rows = [{"id": i, "data": d} for (c, i), d in self.docs.items() if c == col]
            if "id" in q:
                rows = [r for r in rows if r["id"] == q["id"][3:]]
            de, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
            return httpx.Response(200, json=rows[de:de + lim])
        if p == "/rest/v1/docs" and req.method == "POST":
            assert q["on_conflict"] == "org_id,col,id" and "merge-duplicates" in req.headers["Prefer"]
            b = json.loads(req.content)
            self.posts.append(b)
            self.docs[(b["col"], b["id"])] = b["data"]
            return httpx.Response(201)
        return httpx.Response(404)


def test_supabase_login_paginacao_e_gravacao():
    s = SupaFalso()
    g = GestorSupabase("https://x.supabase.co", "anon", "robo@x", "certa", transport=httpx.MockTransport(s))
    assert len(g.ler_col("empresas")) == 1500           # paginou 1000 + 500
    g.gravar("dasmei_clientes", "e1", {"a": 1})
    assert s.posts[-1] == {"org_id": "org-1", "col": "dasmei_clientes", "id": "e1", "data": {"a": 1}}
    assert g.ler_doc("dasmei_clientes", "e1") == {"a": 1}


def test_supabase_senha_errada():
    g = GestorSupabase("https://x.supabase.co", "anon", "robo@x", "errada", transport=httpx.MockTransport(SupaFalso()))
    with pytest.raises(ErroGestor):
        g.ler_col("empresas")
