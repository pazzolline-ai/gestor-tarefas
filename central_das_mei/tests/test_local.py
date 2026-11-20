import io
import json
from pathlib import Path

import httpx
import pytest

from dasmei.cnpj import formatar
from dasmei.local import GestorLocal
from dasmei.motor import Motor
from dasmei.web import ServidorWeb
from tests.apoio import CNPJ_A, CNPJ_B, CNPJ_C, pdf_das
from tests.conftest import HOJE


@pytest.fixture
def local(banco):
    return GestorLocal(banco)


def test_cadastro_e_duplicidade(local):
    eid = local.salvar_empresa({"cnpj": CNPJ_A, "razao": "ALFA LTDA", "fantasia": "Alfa", "whatsapp": "(62) 99999-0000"})
    e = local.ler_doc("empresas", eid)
    assert e["regime"] == "MEI" and e["cnpj"] == "11.222.333/0001-81" and e["guiaMensal"] is True
    with pytest.raises(ValueError, match="Já existe"):
        local.salvar_empresa({"cnpj": CNPJ_A, "razao": "Outra"})
    with pytest.raises(ValueError, match="CNPJ inválido"):
        local.salvar_empresa({"cnpj": "123", "razao": "X"})
    local.salvar_empresa({"cnpj": CNPJ_A, "razao": "ALFA ME", "inativa": True}, eid)
    assert local.ler_doc("empresas", eid)["inativa"] is True
    assert local.clientes_mei() == ([], [])


def test_importar_csv_ponto_e_virgula_cp1252(local):
    csv = ("Razão Social;CNPJ;Nome Fantasia;WhatsApp;Responsável\n"
           f"José Doces;{CNPJ_A};Doces do Zé;62999990000;José\n"
           f"Beta;{CNPJ_B};;;\n"
           "Ruim;123;;;\n").encode("cp1252")
    r = local.importar("clientes.csv", csv)
    assert r["novos"] == 2 and r["atualizados"] == 0 and len(r["erros"]) == 1 and "linha 4" in r["erros"][0]
    nomes = sorted(e["razao"] for _, e in local.ler_col("empresas"))
    assert nomes == ["Beta", "José Doces"]
    r2 = local.importar("clientes.csv", csv)          # reimportar não duplica
    assert r2["novos"] == 0 and r2["atualizados"] == 2 and len(local.ler_col("empresas")) == 2


def test_importar_xlsx(local):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.append(["Cliente", "CNPJ do MEI", "Telefone"])
    ws.append(["Gama Unhas", formatar(CNPJ_C), "62988887777"])
    b = io.BytesIO()
    wb.save(b)
    r = local.importar("lista.xlsx", b.getvalue())
    assert r == {"novos": 1, "atualizados": 0, "erros": []}
    e = local.ler_col("empresas")[0][1]
    assert e["razao"] == "Gama Unhas" and e["whatsapp"] == "62988887777"


def test_importar_sem_coluna_cnpj(local):
    assert "CNPJ" in local.importar("x.csv", b"Nome;Telefone\nA;1\n")["erros"][0]


def test_robo_funciona_com_cadastro_local(cfg, banco, local, fabrica):
    local.salvar_empresa({"cnpj": CNPJ_A, "fantasia": "Alfa"})
    local.salvar_empresa({"cnpj": CNPJ_B, "fantasia": "Beta"})
    r = Motor(cfg, banco, local, fabrica, hoje=lambda: HOJE, dormir=lambda s: None, aleatorio=lambda a, b: a).executar("manual")
    assert r["processados"] == 2 and r["guias_emitidas"] == 6
    assert len(local.ler_col("dasmei_clientes")) == 2 and local.ler_doc("dasmei_execucoes", r["id"])


# ---------------- tela local ----------------
@pytest.fixture
def web(cfg, local):
    acordou = []
    s = ServidorWeb(cfg, local, porta=0, token="T" * 40, acordar=lambda: acordou.append(1), usuario="thais").iniciar()
    s.acordou = acordou
    yield s
    s.parar()


def cli(web, cookie=True):
    c = httpx.Client(base_url=f"http://127.0.0.1:{web.porta}", follow_redirects=False)
    if cookie:
        c.cookies.set("dm", web.token)
    return c


def post(c, rota, dados=None, **kw):
    return c.post(rota, json=dados, headers={"X-DM": "1"}, **kw)


def test_acesso_exige_chave(web):
    c = cli(web, cookie=False)
    assert c.get("/").status_code == 401 and c.get("/api/estado").status_code == 401
    assert c.get("/?t=errada").status_code == 403
    r = c.get(f"/?t={web.token}")
    assert r.status_code == 303 and "HttpOnly" in r.headers["set-cookie"] and "SameSite=Strict" in r.headers["set-cookie"]
    assert cli(web).get("/").status_code == 200 and "Central de DAS MEI" in cli(web).get("/").text


def test_post_exige_cabecalho_anti_csrf(web):
    c = cli(web)
    assert c.post("/api/empresa", json={"cnpj": CNPJ_A, "razao": "A"}).status_code == 403
    assert cli(web, cookie=False).post("/api/empresa", json={}, headers={"X-DM": "1"}).status_code == 403


def test_fluxo_da_tela(web, local):
    c = cli(web)
    assert post(c, "/api/empresa", {"cnpj": CNPJ_A, "razao": "Alfa"}).json()["ok"]
    assert post(c, "/api/empresa", {"cnpj": "1", "razao": "x"}).status_code == 400
    r = c.post("/api/importar?nome=a.csv", content=f"CNPJ;Nome\n{CNPJ_B};Beta\n".encode(), headers={"X-DM": "1"})
    assert r.json()["novos"] == 1
    est = c.get("/api/estado").json()
    assert len(est["empresas"]) == 2 and est["robo"]["config"]["horario"] == "07:00" and est["modo"] == "automatico"
    eid = est["empresas"][0]["id"]
    assert post(c, "/api/config", {"horario": "06:15", "dias_semana": [0, 1, 2, 3, 4]}).status_code == 200
    assert local.ler_doc("dasmei_robo", "config")["horario"] == "06:15"
    assert post(c, "/api/config", {"horario": "29:00"}).status_code == 400
    assert post(c, "/api/comando", {"acao": "assistido", "empresaIds": [eid]}).json()["ok"] and web.acordou
    assert post(c, "/api/comando", {"acao": "executar"}).status_code == 400      # já tem pedido
    assert post(c, "/api/comando", {"acao": "rm -rf"}).status_code == 400
    assert post(c, "/api/pagamento", {"empresaId": eid, "comp": "2026-10", "data": "2026-11-10", "valor": 81.05}).json()["ok"]
    pg = local.ler_doc("dasmei_pagamentos", f"{eid}_2026-10")
    assert pg["por"] == "thais" and pg["valor"] == 81.05
    assert post(c, "/api/pagamento", {"empresaId": eid, "comp": "outubro", "data": "x"}).status_code == 400
    assert post(c, "/api/pagamento/apagar", {"id": f"{eid}_2026-10"}).json()["ok"]
    assert not local.ler_doc("dasmei_pagamentos", f"{eid}_2026-10")


def test_pdf_so_dentro_da_pasta(web, cfg, tmp_path):
    base = Path(cfg.pasta_documentos)
    p = base / CNPJ_A / "2026" / "OUTUBRO" / "g.pdf"
    p.parent.mkdir(parents=True)
    p.write_bytes(pdf_das(CNPJ_A, 2026, 10, "2026-11-20", 81.05, "07202000000000001"))
    fora = tmp_path / "segredo.pdf"
    fora.write_bytes(b"%PDF segredo")
    c = cli(web)
    r = c.get("/arquivo", params={"caminho": str(p)})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert c.get("/arquivo", params={"caminho": str(fora)}).status_code == 404
    assert c.get("/arquivo", params={"caminho": str(base / ".." / "segredo.pdf")}).status_code == 404
    assert post(c, "/api/abrir", {"caminho": str(fora)}).status_code == 400
    assert post(c, "/api/abrir", {"caminho": str(p)}).json()["pasta"] == str(p.parent.resolve())


def test_relatorio_html(web, local):
    local.gravar("dasmei_execucoes", "x1", {"id": "x1", "inicio": "2026-11-19T07:00:00", "fim": "2026-11-19T07:05:00",
                                            "origem": "agendada", "estado": "concluida", "total_clientes": 1, "processados": 1,
                                            "consultas_ok": 1, "guias_emitidas": 1, "pdfs_baixados": 1,
                                            "competencias_pendentes": 0, "das_vencidos": 0, "pagamentos_confirmados": 0,
                                            "aguardando_autenticacao_n": 0, "aguardando_autenticacao": [], "erros_n": 0,
                                            "erros": [], "revisao_n": 0, "revisao": [], "alertas": []})
    r = cli(web).get("/relatorio/x1")
    assert r.status_code == 200 and "relatório da rotina" in r.text
