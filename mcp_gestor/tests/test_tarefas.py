import datetime as dt
import json

import anyio
import httpx
import pytest
from mcp import Client

from gestor_mcp.banco import BancoMemoria, BancoSupabase, ErroGestor
from gestor_mcp.servidor import criar_servidor
from gestor_mcp.tarefas import Tarefas

ONTEM = (dt.date.today() - dt.timedelta(days=1)).isoformat()
AMANHA = (dt.date.today() + dt.timedelta(days=1)).isoformat()


def banco():
    return BancoMemoria({
        "empresas": {"e1": {"fantasia": "Padaria Sol", "cnpj": "12345678000190", "regime": "MEI"},
                     "e2": {"razao": "Antiga Ltda", "inativa": True}},
        "equipe": {"p1": {"nome": "Ana", "ativo": True}, "p2": {"nome": "Bia", "ativo": False}},
        "tarefas": {
            "t1": {"titulo": "Emitir DAS", "status": "afazer", "responsavel": "Ana", "prazo": ONTEM, "empresaId": "e1"},
            "t2": {"titulo": "Alvará", "status": "andamento", "responsavel": "Lucas", "prazo": AMANHA},
            "t3": {"titulo": "Velha", "status": "concluida", "responsavel": "Ana"},
        },
    }, nome_usuario="Lucas")


def test_listar_filtra_e_ordena():
    t = Tarefas(banco())
    assert [r["id"] for r in t.listar()] == ["t1", "t2"]
    assert t.listar()[0]["atrasada"] and t.listar()[0]["empresa"] == "Padaria Sol"
    assert [r["id"] for r in t.listar(responsavel="ana")] == ["t1"]
    assert [r["id"] for r in t.listar(somente_atrasadas=True)] == ["t1"]
    assert len(t.listar(incluir_concluidas=True)) == 3
    assert [r["id"] for r in t.listar(status="concluida")] == ["t3"]


def test_criar_no_formato_da_tela():
    b = banco()
    r = Tarefas(b).criar("Nova", prazo=AMANHA, empresa_id="e1", prioridade="alta")
    d = b.docs["tarefas"][r["id"]]
    assert d["status"] == "afazer" and d["responsavel"] == "Lucas" and d["solicitante"] == "Lucas"
    assert d["hist"][0]["tipo"] == "criada" and d["concluidoEm"] == ""
    with pytest.raises(ErroGestor):
        Tarefas(b).criar("X", prazo="31/12/2026")
    with pytest.raises(ErroGestor):
        Tarefas(b).criar("X", empresa_id="nao-existe")


def test_status_edicao_nota():
    b = banco()
    t = Tarefas(b)
    r = t.mudar_status("t1", "concluida", "feito")
    assert r["status"] == "concluida" and r["concluidoEm"] and "feito" in r["historico"][-1]["txt"]
    assert t.mudar_status("t1", "afazer")["concluidoEm"] == ""
    assert t.editar("t2", prazo="")["prazo"] == ""
    assert t.anotar("t2", "liguei")["historico"][-1]["tipo"] == "nota"
    with pytest.raises(ErroGestor):
        t.mudar_status("t1", "xyz")
    with pytest.raises(ErroGestor):
        t.ver("nada")


def test_resumo_empresas_equipe():
    t = Tarefas(banco())
    r = t.resumo()
    assert r["abertas"] == 2 and r["atrasadas"] == 1
    assert [e["id"] for e in t.empresas()] == ["e1"]
    assert t.equipe() == [{"nome": "Ana", "departamento": ""}]


def test_pelo_protocolo_mcp():
    async def go():
        async with Client(criar_servidor(banco())) as c:
            nomes = {x.name for x in (await c.list_tools()).tools}
            assert {"listar_tarefas", "criar_tarefa", "mudar_status", "resumo_tarefas"} <= nomes
            res = await c.call_tool("resumo_tarefas", {})
            assert not res.is_error
            assert json.loads(res.content[0].text)["atrasadas"] == 1
            res = await c.call_tool("mudar_status", {"id": "t1", "status": "inexistente"})
            assert res.is_error
            res = await c.call_tool("ver_tarefa", {"id": "nada"})
            assert res.is_error and "não encontrada" in res.content[0].text
    anyio.run(go)


def test_supabase_login_e_gravacao():
    chamadas = []

    def h(req: httpx.Request):
        chamadas.append((req.method, req.url.path))
        if req.url.path == "/auth/v1/token":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600, "user": {"id": "u1"}})
        if req.url.path == "/rest/v1/membros":
            return httpx.Response(200, json=[{"org_id": "o1", "nome": "Lucas Silva", "ativo": True}])
        if req.method == "POST":
            assert json.loads(req.content)["org_id"] == "o1"
            return httpx.Response(201)
        return httpx.Response(200, json=[])
    b = BancoSupabase("https://x.supabase.co", "anon", "a@b.c", "s", transport=httpx.MockTransport(h))
    Tarefas(b).criar("Teste")
    assert b.nome_usuario == "Lucas" and ("POST", "/rest/v1/docs") in chamadas
    with pytest.raises(ErroGestor):
        BancoSupabase("", "", "", "")
