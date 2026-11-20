import base64
import datetime as dt
import json

import httpx
import pytest

from dasmei import serpro
from dasmei.serpro import (ErroAutorizacao, ErroCredencial, ErroNegocio, ErroTemporario, IntegraContador,
                           classificar)
from tests.apoio import CNPJ_A, SerproFalsa


def cliente(transport, **kw):
    return IntegraContador(ambiente="producao", contratante="11222333000181", consumer_key="ck",
                           consumer_secret="cs", transport=transport, intervalo_min=0, dormir=lambda s: None, **kw)


def test_autenticacao_e_corpo_do_pedido():
    vistos = []

    def h(req):
        vistos.append(req)
        if req.url.path.endswith("/authenticate"):
            return httpx.Response(200, json={"access_token": "AT", "jwt_token": "JWT", "expires_in": 2008})
        return httpx.Response(200, json={"status": 200, "mensagens": [], "dados": "[]"})
    c = cliente(httpx.MockTransport(h))
    c.gerar_das_pdf(CNPJ_A, "202603")
    auth, req = vistos
    assert str(auth.url) == serpro.URL_AUTH
    assert auth.headers["Authorization"] == "Basic " + base64.b64encode(b"ck:cs").decode()
    assert auth.headers["Role-Type"] == "TERCEIROS" and auth.content == b"grant_type=client_credentials"
    assert str(req.url) == "https://gateway.apiserpro.serpro.gov.br/integra-contador/v1/Emitir"
    assert req.headers["Authorization"] == "Bearer AT" and req.headers["jwt_token"] == "JWT"
    corpo = json.loads(req.content)
    assert corpo["contratante"] == {"numero": "11222333000181", "tipo": 2}
    assert corpo["autorPedidoDados"] == {"numero": "11222333000181", "tipo": 2}
    assert corpo["contribuinte"] == {"numero": CNPJ_A, "tipo": 2}
    assert corpo["pedidoDados"] == {"idSistema": "PGMEI", "idServico": "GERARDASPDF21", "versaoSistema": "1.0",
                                    "dados": '{"periodoApuracao":"202603"}'}


def test_token_reaproveitado_e_reautentica_em_401():
    f = SerproFalsa()
    estado = {"n": 0}

    def h(req):
        if not req.url.path.endswith("/authenticate"):
            estado["n"] += 1
            if estado["n"] == 2:
                return httpx.Response(401, json={})
        return f.handler(req)
    c = cliente(httpx.MockTransport(h))
    c.gerar_das_pdf(CNPJ_A, "202603")
    c.gerar_das_pdf(CNPJ_A, "202604")
    assert f.auth == 2   # 1 inicial + 1 renovação após o 401


def test_servico_fora_da_lista_e_bloqueado():
    c = cliente(httpx.MockTransport(lambda r: httpx.Response(200, json={})))
    with pytest.raises(PermissionError):
        c._post("PGMEI", "ATUBENEFICIO23", CNPJ_A, {})
    with pytest.raises(PermissionError):
        c._post("PGDASD", "TRANSDECLARACAO11", CNPJ_A, {})


def test_parse_gerar_das():
    f = SerproFalsa()
    c = cliente(f.transporte())
    g = c.gerar_das_pdf(CNPJ_A, "202603")
    d = g[0].detalhes[0]
    assert g[0].pdf.startswith(b"%PDF") and g[0].cnpj == CNPJ_A
    assert d.periodo_apuracao == "202603" and d.data_vencimento == "2026-04-20" and d.total == 81.05
    assert d.data_limite == "2099-12-31" and d.numero_documento


def test_pagamentos_paginacao_e_formato():
    f = SerproFalsa()
    pag = [{"numeroDocumento": f"0720{i:013d}", "tipo": {"codigo": "DAS", "descricao": "DAS"},
            "periodoApuracao": "2026-03-01", "dataArrecadacao": "2026-04-15", "dataVencimento": "2026-04-20",
            "receitaPrincipal": {"codigo": "1001", "descricao": "SIMEI"}, "valorTotal": 81.05,
            "valorPrincipal": 81.05, "desmembramentos": []} for i in range(3)]
    f.pagamentos[CNPJ_A] = pag
    c = cliente(f.transporte())
    r = c.consultar_pagamentos(CNPJ_A, dt.date(2026, 1, 1), dt.date(2026, 11, 19), tamanho=2)
    assert len(f.chamadas) == 2 and len(r) == 3   # 3 pagamentos em páginas de 2
    assert r[0].pa == "202603" and r[0].data_arrecadacao == "2026-04-15" and r[0].valor_total == 81.05
    _, servico, _, dados = f.chamadas[0]
    assert servico == "PAGAMENTOS71"
    assert dados["intervaloDataArrecadacao"] == {"dataInicial": "2026-01-01", "dataFinal": "2026-11-19"}
    assert dados["primeiroDaPagina"] == 0 and dados["tamanhoDaPagina"] == 2


@pytest.mark.parametrize("st,corpo,tipo", [
    (401, {}, ErroCredencial),
    (403, {"mensagens": [{"codigo": "x", "texto": "sem procuração"}]}, ErroAutorizacao),
    (400, {"mensagens": [{"codigo": "[Erro]", "texto": "Procuração eletrônica não localizada"}]}, ErroAutorizacao),
    (429, {}, ErroTemporario), (500, {}, ErroTemporario), (503, {}, ErroTemporario),
    (400, {"mensagens": [{"codigo": "[EntradaIncorreta]", "texto": "Período inválido"}]}, ErroNegocio),
    (200, {"status": 200, "mensagens": [{"codigo": "[Erro-PGMEI]", "texto": "Serviço temporariamente indisponível"}]}, ErroTemporario),
])
def test_classificacao_de_erros(st, corpo, tipo):
    assert isinstance(classificar(st, corpo), tipo)


def test_sucesso_nao_e_erro():
    assert classificar(200, {"status": 200, "mensagens": [{"codigo": "[Sucesso-PGMEI]", "texto": "ok"}]}) is None


def test_falha_de_rede_e_temporaria():
    def h(req):
        raise httpx.ConnectTimeout("timeout", request=req)
    with pytest.raises(ErroTemporario):
        cliente(httpx.MockTransport(h)).autenticar()


def test_limite_de_requisicoes():
    esperas = []
    f = SerproFalsa()
    c = IntegraContador(ambiente="producao", contratante="11222333000181", consumer_key="k", consumer_secret="s",
                        transport=f.transporte(), intervalo_min=5, dormir=esperas.append)
    c.gerar_das_pdf(CNPJ_A, "202601")
    c.gerar_das_pdf(CNPJ_A, "202602")
    assert esperas and 4 < esperas[-1] <= 5


def test_producao_sem_certificado_recusa():
    with pytest.raises(ErroCredencial):
        IntegraContador(ambiente="producao", contratante="11222333000181", consumer_key="k", consumer_secret="s")


def test_certificado_pfx(tmp_path):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "ESCRITORIO FICTICIO:11222333000181")])
    agora = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(nome).issuer_name(nome).public_key(k.public_key())
            .serial_number(1).not_valid_before(agora - dt.timedelta(days=1))
            .not_valid_after(agora + dt.timedelta(days=90)).sign(k, hashes.SHA256()))
    pfx = pkcs12.serialize_key_and_certificates(b"x", k, cert, None, serialization.BestAvailableEncryption(b"senha"))
    i = serpro.info_certificado(pfx, "senha")
    assert "ESCRITORIO FICTICIO" in i["titular"] and 88 <= i["dias_restantes"] <= 90
    ctx = serpro.contexto_tls(pfx, "senha")
    assert ctx is not None
    import tempfile, glob, os
    assert not glob.glob(os.path.join(tempfile.gettempdir(), "dasmei_*.pem"))   # temporário apagado
    with pytest.raises(ErroCredencial):
        serpro.contexto_tls(pfx, "errada")
