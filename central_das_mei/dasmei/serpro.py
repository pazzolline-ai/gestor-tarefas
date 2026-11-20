"""Cliente da API oficial Integra Contador (SERPRO / Receita Federal).

Somente leitura e emissão de guia. Serviços liberados (lista fechada):
  PGMEI/GERARDASPDF21    Emitir  — gera o DAS-MEI em PDF de um período
  PAGTOWEB/PAGAMENTOS71  Consultar — pagamentos (evidência oficial de pagamento)
Nenhum serviço que declare, transmita ou altere dados (ex.: ATUBENEFICIO23,
/Declarar) é permitido por este cliente.

Autenticação (produção): POST https://autenticacao.sapi.serpro.gov.br/authenticate
com o e-CNPJ do escritório (TLS mútuo), Authorization Basic(consumerKey:consumerSecret),
'Role-Type: TERCEIROS' e corpo grant_type=client_credentials; a resposta traz
access_token e jwt_token, enviados em toda chamada ao gateway.
Cada cliente MEI precisa ter dado procuração eletrônica (e-CAC) ao escritório.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import secrets
import ssl
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .arquivos import apagar_seguro

URL_AUTH = "https://autenticacao.sapi.serpro.gov.br/authenticate"
URL_GATEWAY = {
    "producao": "https://gateway.apiserpro.serpro.gov.br/integra-contador/v1",
    "trial": "https://gateway.apiserpro.serpro.gov.br/integra-contador-trial/v1",
}
# Ambiente de demonstração da SERPRO: token fixo público, sem certificado.
TOKEN_TRIAL = "06aef429-a981-3ec5-a1f8-71d38d86481e"

SERVICOS_PERMITIDOS = {
    ("PGMEI", "GERARDASPDF21"): "/Emitir",
    ("PAGTOWEB", "PAGAMENTOS71"): "/Consultar",
}


# ---------------- erros ----------------
class ErroSerpro(Exception):
    def __init__(self, msg, http_status=None, mensagens=None):
        super().__init__(msg)
        self.http_status = http_status
        self.mensagens = mensagens or []


class ErroTemporario(ErroSerpro):
    """Rede, timeout, 429, 5xx: tentar de novo mais tarde."""


class ErroCredencial(ErroSerpro):
    """Problema do ESCRITÓRIO (chaves, certificado, contrato): para o lote inteiro."""


class ErroAutorizacao(ErroSerpro):
    """Problema do CLIENTE: sem procuração/permissão. Vai para 'Aguardando autenticação'."""


class ErroNegocio(ErroSerpro):
    """A Receita recusou o pedido (ex.: período não permitido). Exige revisão humana."""


_RE_AUTORIZ = re.compile(r"(?i)procura[çc][ãa]o|outorg|n[ãa]o autoriz|sem autoriza|permiss[ãa]o|acesso negado")
_RE_TEMP = re.compile(r"(?i)indispon|tente novamente|tempor[áa]ri|timeout|time-out|sobrecarg")


def _texto_msgs(msgs):
    return " | ".join(f"{m.get('codigo', '')} {m.get('texto', '')}".strip() for m in (msgs or []) if isinstance(m, dict))


def classificar(http_status: int, corpo: dict | None) -> ErroSerpro | None:
    """Transforma resposta HTTP + envelope em exceção (ou None se sucesso)."""
    msgs = (corpo or {}).get("mensagens") if isinstance(corpo, dict) else None
    if isinstance(msgs, str):
        msgs = [{"codigo": "", "texto": msgs}]
    txt = _texto_msgs(msgs) or f"HTTP {http_status}"
    tem_erro = any(re.search(r"(?i)erro", str(m.get("codigo", ""))) for m in (msgs or []) if isinstance(m, dict))
    st_env = (corpo or {}).get("status") if isinstance(corpo, dict) else None
    if 200 <= http_status < 300 and not tem_erro and (st_env in (None, 200, "200")):
        return None
    if http_status == 401:
        return ErroCredencial("Credenciais SERPRO recusadas: " + txt, http_status, msgs)
    if http_status == 403 or _RE_AUTORIZ.search(txt):
        return ErroAutorizacao("Sem autorização para este contribuinte: " + txt, http_status, msgs)
    if http_status in (408, 425, 429) or http_status >= 500 or _RE_TEMP.search(txt):
        return ErroTemporario("Serviço indisponível no momento: " + txt, http_status, msgs)
    return ErroNegocio("Pedido recusado pela Receita: " + txt, http_status, msgs)


# ---------------- modelos ----------------
def data_iso(s) -> str | None:
    if not s:
        return None
    d = re.sub(r"\D", "", str(s))
    if len(d) >= 8:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return None


def pa_norm(s) -> str | None:
    d = re.sub(r"\D", "", str(s or ""))
    return d[:6] if len(d) >= 6 else None


def _num(v):
    try:
        return float(str(v).replace(",", ".")) if v not in (None, "") else None
    except ValueError:
        return None


@dataclass
class DetalheDas:
    periodo_apuracao: str          # AAAAMM
    numero_documento: str
    data_vencimento: str | None    # AAAA-MM-DD
    data_limite: str | None        # AAAA-MM-DD (até quando a guia pode ser paga)
    principal: float | None
    multa: float | None
    juros: float | None
    total: float | None
    observacoes: list = field(default_factory=list)


@dataclass
class DasGerado:
    pdf: bytes
    cnpj: str
    razao_social: str | None
    detalhes: list[DetalheDas]


@dataclass
class Pagamento:
    numero_documento: str
    tipo: str
    pa: str | None
    pas_desmembrados: list
    data_arrecadacao: str | None
    data_vencimento: str | None
    valor_total: float | None
    receita: str


def _dados_json(corpo):
    d = corpo.get("dados") if isinstance(corpo, dict) else None
    if d in (None, ""):
        return None
    if isinstance(d, str):
        try:
            return json.loads(d)
        except json.JSONDecodeError as e:
            raise ErroNegocio(f"Resposta da Receita em formato inesperado: {e}") from e
    return d


def parse_gerar_das(corpo) -> list[DasGerado]:
    dados = _dados_json(corpo)
    if dados is None:
        return []
    if isinstance(dados, dict):
        dados = [dados]
    out = []
    for item in dados:
        pdf_b64 = item.get("pdf") or ""
        try:
            pdf = base64.b64decode(pdf_b64, validate=False)
        except (ValueError, TypeError) as e:
            raise ErroNegocio("PDF da guia veio corrompido (base64)") from e
        dets = []
        for d in item.get("detalhamento") or []:
            v = d.get("valores") or {}
            dets.append(DetalheDas(
                periodo_apuracao=pa_norm(d.get("periodoApuracao")) or "",
                numero_documento=re.sub(r"\D", "", str(d.get("numeroDocumento") or "")),
                data_vencimento=data_iso(d.get("dataVencimento")),
                data_limite=data_iso(d.get("dataLimiteAcolhimento")),
                principal=_num(v.get("principal")), multa=_num(v.get("multa")),
                juros=_num(v.get("juros")), total=_num(v.get("total")),
                observacoes=[d.get(k) for k in ("observacao1", "observacao2", "observacao3") if d.get(k)],
            ))
        out.append(DasGerado(pdf=pdf, cnpj=re.sub(r"\D", "", str(item.get("cnpjCompleto") or "")),
                             razao_social=item.get("razaoSocial"), detalhes=dets))
    return out


def parse_pagamentos(corpo) -> list[Pagamento]:
    dados = _dados_json(corpo) or []
    out = []
    for d in dados if isinstance(dados, list) else [dados]:
        tipo = d.get("tipo") or {}
        rec = d.get("receitaPrincipal") or {}
        des = [pa_norm(x.get("periodoApuracao")) for x in (d.get("desmembramentos") or []) if isinstance(x, dict)]
        out.append(Pagamento(
            numero_documento=re.sub(r"\D", "", str(d.get("numeroDocumento") or "")),
            tipo=" ".join(str(tipo.get(k, "")) for k in ("codigo", "descricaoAbreviada", "descricao")).strip(),
            pa=pa_norm(d.get("periodoApuracao")),
            pas_desmembrados=[p for p in des if p],
            data_arrecadacao=data_iso(d.get("dataArrecadacao")),
            data_vencimento=data_iso(d.get("dataVencimento")),
            valor_total=_num(d.get("valorTotal")),
            receita=" ".join(str(rec.get(k, "")) for k in ("codigo", "descricao")).strip(),
        ))
    return out


# ---------------- certificado ----------------
def info_certificado(pfx: bytes, senha: str) -> dict:
    from cryptography.hazmat.primitives.serialization import pkcs12
    _, cert, _ = pkcs12.load_key_and_certificates(pfx, senha.encode() if senha else None)
    if cert is None:
        raise ErroCredencial("Certificado sem chave/certificado válido")
    fim = cert.not_valid_after_utc
    return {"titular": cert.subject.rfc4514_string(), "valido_ate": fim.date().isoformat(),
            "dias_restantes": (fim - dt.datetime.now(dt.timezone.utc)).days}


def contexto_tls(pfx: bytes, senha: str) -> ssl.SSLContext:
    """Monta o TLS mútuo a partir do .pfx sem nunca gravar a chave aberta no disco:
    a chave vai para um temporário cifrado com senha aleatória, é carregada e o
    temporário é apagado com sobrescrita."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    try:
        chave, cert, cadeia = pkcs12.load_key_and_certificates(pfx, senha.encode() if senha else None)
    except ValueError as e:
        raise ErroCredencial("Senha do certificado incorreta ou arquivo inválido") from e
    if chave is None or cert is None:
        raise ErroCredencial("O arquivo do certificado não contém chave privada")
    if cert.not_valid_after_utc < dt.datetime.now(dt.timezone.utc):
        raise ErroCredencial("Certificado digital do escritório vencido")
    frase = secrets.token_urlsafe(32).encode()
    pem = chave.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.BestAvailableEncryption(frase))
    pem += cert.public_bytes(serialization.Encoding.PEM)
    for c in cadeia or []:
        pem += c.public_bytes(serialization.Encoding.PEM)
    ctx = ssl.create_default_context()
    fd, tmp = tempfile.mkstemp(prefix="dasmei_", suffix=".pem")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        ctx.load_cert_chain(tmp, password=frase)
    finally:
        apagar_seguro(Path(tmp))
    return ctx


# ---------------- cliente ----------------
class IntegraContador:
    def __init__(self, *, ambiente: str, contratante: str, autor: str | None = None,
                 consumer_key: str = "", consumer_secret: str = "", pfx: bytes | None = None,
                 pfx_senha: str = "", intervalo_min: float = 3.0, timeout: float = 60.0,
                 transport: httpx.BaseTransport | None = None, dormir=time.sleep):
        if ambiente not in URL_GATEWAY:
            raise ValueError("ambiente deve ser 'producao' ou 'trial'")
        self.ambiente = ambiente
        self.contratante = re.sub(r"\D", "", contratante)
        self.autor = re.sub(r"\D", "", autor or contratante)
        self._ck, self._cs = consumer_key, consumer_secret
        self._intervalo = float(intervalo_min)
        self._dormir = dormir
        self._ultimo = 0.0
        self._lock = threading.Lock()
        self._token = None
        self._expira = 0.0
        kw = {"timeout": timeout}
        if transport is not None:
            kw["transport"] = transport
        elif ambiente == "producao":
            if not pfx:
                raise ErroCredencial("Certificado digital (e-CNPJ) do escritório não configurado")
            kw["verify"] = contexto_tls(pfx, pfx_senha)
        self._http = httpx.Client(**kw)

    def fechar(self):
        self._http.close()

    # limite de requisições: no mínimo `intervalo_min` segundos entre chamadas
    def _respeitar_limite(self):
        with self._lock:
            espera = self._ultimo + self._intervalo - time.monotonic()
            if espera > 0:
                self._dormir(espera)
            self._ultimo = time.monotonic()

    def autenticar(self, forcar=False):
        if not forcar and self._token and time.monotonic() < self._expira:
            return self._token
        if self.ambiente == "trial":
            self._token = (TOKEN_TRIAL, TOKEN_TRIAL)
            self._expira = time.monotonic() + 3600
            return self._token
        if not (self._ck and self._cs):
            raise ErroCredencial("Consumer Key/Secret da SERPRO não configurados")
        basic = base64.b64encode(f"{self._ck}:{self._cs}".encode()).decode()
        try:
            r = self._http.post(URL_AUTH, headers={
                "Authorization": f"Basic {basic}", "Role-Type": "TERCEIROS",
                "Content-Type": "application/x-www-form-urlencoded"}, content="grant_type=client_credentials")
        except httpx.TransportError as e:
            raise ErroTemporario(f"Falha de rede ao autenticar na SERPRO: {e.__class__.__name__}") from e
        if r.status_code in (400, 401, 403):
            raise ErroCredencial(f"SERPRO recusou a autenticação do escritório (HTTP {r.status_code})", r.status_code)
        if r.status_code >= 500 or r.status_code == 429:
            raise ErroTemporario(f"Autenticação SERPRO indisponível (HTTP {r.status_code})", r.status_code)
        try:
            j = r.json()
            self._token = (j["access_token"], j["jwt_token"])
            self._expira = time.monotonic() + max(60, int(j.get("expires_in", 3600)) - 120)
        except (ValueError, KeyError) as e:
            raise ErroCredencial("Resposta de autenticação da SERPRO sem tokens") from e
        return self._token

    def _post(self, id_sistema, id_servico, contribuinte, dados: dict, versao="1.0"):
        rota = SERVICOS_PERMITIDOS.get((id_sistema, id_servico))
        if not rota:
            raise PermissionError(f"Serviço {id_sistema}/{id_servico} não é permitido neste robô")
        corpo = {
            "contratante": {"numero": self.contratante, "tipo": 2},
            "autorPedidoDados": {"numero": self.autor, "tipo": 2 if len(self.autor) == 14 else 1},
            "contribuinte": {"numero": re.sub(r"\D", "", contribuinte), "tipo": 2},
            "pedidoDados": {"idSistema": id_sistema, "idServico": id_servico, "versaoSistema": versao,
                            "dados": json.dumps(dados, separators=(",", ":"))},
        }
        for tentativa in (1, 2):
            access, jwt = self.autenticar(forcar=tentativa == 2)
            self._respeitar_limite()
            try:
                r = self._http.post(URL_GATEWAY[self.ambiente] + rota, json=corpo, headers={
                    "Authorization": f"Bearer {access}", "jwt_token": jwt, "Content-Type": "application/json"})
            except httpx.TransportError as e:
                raise ErroTemporario(f"Falha de rede com a SERPRO: {e.__class__.__name__}") from e
            if r.status_code == 401 and tentativa == 1:
                continue  # token expirado: autentica de novo uma vez
            break
        if r.status_code == 204:
            return {"status": 204, "mensagens": [], "dados": None}
        try:
            j = r.json() if r.content else {}
        except ValueError:
            j = {}
        erro = classificar(r.status_code, j)
        if erro:
            raise erro
        return j

    # ----- serviços -----
    def gerar_das_pdf(self, cnpj: str, pa: str) -> list[DasGerado]:
        if not re.fullmatch(r"\d{6}", pa):
            raise ValueError("período deve ser AAAAMM")
        return parse_gerar_das(self._post("PGMEI", "GERARDASPDF21", cnpj, {"periodoApuracao": pa}))

    def consultar_pagamentos(self, cnpj: str, data_inicial: dt.date, data_final: dt.date,
                             tamanho=100, max_paginas=20) -> list[Pagamento]:
        out, primeiro = [], 0
        for _ in range(max_paginas):
            dados = {"intervaloDataArrecadacao": {"dataInicial": data_inicial.isoformat(),
                                                  "dataFinal": data_final.isoformat()},
                     "primeiroDaPagina": primeiro, "tamanhoDaPagina": tamanho}
            pg = parse_pagamentos(self._post("PAGTOWEB", "PAGAMENTOS71", cnpj, dados))
            out.extend(pg)
            if len(pg) < tamanho:
                break
            primeiro += tamanho
        return out
