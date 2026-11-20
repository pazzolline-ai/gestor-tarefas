"""Sessão assistida contra um PGMEI FALSO local (o captcha é 'resolvido' pelo próprio site de teste)."""
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from dasmei.assistido import SessaoAssistida
from dasmei.motor import Motor
from tests.apoio import CNPJ_A, CNPJ_B, CNPJ_C, pdf_das
from tests.conftest import HOJE

pytest.importorskip("playwright")
EXE = os.environ.get("DASMEI_TEST_CHROMIUM", "/opt/pw-browsers/chromium")


def abrir(pw):
    return pw.chromium.launch(executable_path=EXE) if Path(EXE).exists() else pw.chromium.launch()


IDENT = """<html><body><h1>PGMEI (falso)</h1><input id="cnpj" name="cnpj"><div id="captcha">captcha</div>
<script>setTimeout(()=>{const v=document.getElementById('cnpj').value.replace(/\\D/g,'');
 if(v.length===14) location.href='/emitir?cnpj='+v},600)</script></body></html>"""


class _Site:
    """PGMEI falso servido por HTTP de verdade em 127.0.0.1 (downloads reais)."""
    def __init__(self):
        import http.server
        import threading
        self.modo = {}
        site = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _env(self, ct, corpo, extra=None):
                self.send_response(200)
                self.send_header("Content-Type", ct)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path == "/Identificacao":
                    return self._env("text/html", IDENT.encode())
                if u.path == "/emitir":
                    m = site.modo.get(q["cnpj"], "inline")
                    js = {"inline": "location.href='/das.pdf?cnpj=%s'",
                          "download": "const a=document.createElement('a');a.href='/das.pdf?d=1&cnpj=%s';a.download='das.pdf';document.body.appendChild(a);a.click()",
                          "outro": "location.href='/das.pdf?outro=1&cnpj=%s'", "nada": ""}[m] % q["cnpj"]
                    return self._env("text/html", f"<html><body>Emitir<script>setTimeout(()=>{{{js}}},300)</script></body></html>".encode())
                if u.path == "/das.pdf":
                    c = CNPJ_C if q.get("outro") else q["cnpj"]
                    h = {"Content-Disposition": "attachment; filename=das.pdf"} if q.get("d") else {}
                    return self._env("application/pdf", pdf_das(c, 2026, 10, "2026-11-20", 81.05, "07202" + c[:12]), h)
                self.send_response(404)
                self.end_headers()

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


@pytest.fixture(scope="module")
def pgmei():
    s = _Site()
    yield s
    s.srv.shutdown()


def sessao(cfg, banco, gestor, pgmei, modo, **kw):
    pgmei.modo = modo
    return SessaoAssistida(cfg, banco, gestor, url=pgmei.url + "/Identificacao", abrir=abrir,
                           preparar_contexto=lambda ctx: None, hoje=lambda: HOJE, espera_proximo=0.5,
                           timeout_cliente=kw.pop("timeout", 20), **kw)


def test_sessao_captura_pdf_visualizado_e_baixado(cfg, banco, gestor, pgmei):
    cfg.serpro_ambiente = "nenhum"
    r = sessao(cfg, banco, gestor, pgmei, {CNPJ_A: "inline", CNPJ_B: "download"}).executar()
    assert r["estado"] == "concluida" and r["processados"] == 2 and r["pdfs_baixados"] == 2
    for c in (CNPJ_A, CNPJ_B):
        g = banco.guias(c, "202610")
        assert len(g) == 1 and g[0]["status"] == "guia_baixada" and g[0]["vencimento"] == "2026-11-20"
        p = Path(g[0]["arquivo"])
        assert p.exists() and p.parts[-4:-1] == (c, "2026", "OUTUBRO")
        assert banco.competencia(c, "202610")["status"] == "pendente"      # baixada ≠ paga
    d = gestor.ler_doc("dasmei_clientes", "e1")
    assert d["ultimaConsulta"] and d["guiasBaixadas"] == 1 and d["precisaGuia"] == []
    assert gestor.ler_doc("das", "e1_2026-10")["emitida"]
    assert gestor.ler_doc("dasmei_execucoes", r["id"])["origem"] == "assistida"
    assert r["revisao_n"] == 1     # e4 com CNPJ inválido no cadastro


def test_pdf_de_outro_cnpj_e_recusado(cfg, banco, gestor, pgmei):
    r = sessao(cfg, banco, gestor, pgmei, {CNPJ_A: "outro"}, timeout=4).executar(somente=["e1"])
    assert not banco.guias(CNPJ_A) and not banco.guias(CNPJ_C)
    assert not list(Path(cfg.pasta_documentos).rglob("*.pdf"))
    assert r["processados"] == 0 and {f["estado"] for f in banco.fila_total(r["id"])} == {"pulado"}


def test_fila_pula_quem_ja_tem_guia_ou_pagou(cfg, banco, gestor, pgmei):
    s = sessao(cfg, banco, gestor, pgmei, {})
    s.executar(somente=["e1"])
    gestor.gravar("dasmei_pagamentos", "e2_2026-10", {"data": "2026-11-10", "por": "Thais", "em": "2026-11-19T09:00"})
    fila, _, _ = sessao(cfg, banco, gestor, pgmei, {}).montar_fila()
    assert fila == []


def test_barra_de_instrucoes_aparece(cfg, banco, gestor, pgmei):
    from playwright.sync_api import sync_playwright
    s = sessao(cfg, banco, gestor, pgmei, {})
    s._ui = {"titulo": "cliente 1 de 1", "nome": "Alfa <Doces>", "cnpj": "11.222.333/0001-81", "instrucao": "faça X",
             "botoes": ["pular", "parar"]}
    with sync_playwright() as pw:
        nav = abrir(pw)
        ctx = nav.new_context()
        from dasmei.assistido import BARRA_JS
        ctx.expose_binding("dasmeiEstado", s._estado)
        ctx.expose_binding("dasmeiAcao", s._set_acao)
        ctx.add_init_script(BARRA_JS)
        pg = ctx.new_page()
        pg.goto(pgmei.url + "/Identificacao")
        pg.wait_for_selector("#dasmei-barra")
        txt = pg.inner_text("#dasmei-barra")
        assert "Alfa <Doces>" in txt and "11.222.333/0001-81" in txt and "Pular cliente" in txt
        pg.click("#dasmei-barra button[data-a=pular]")
        pg.wait_for_timeout(200)
        assert s._acao == "pular"
        assert pg.input_value("#cnpj") == ""       # a barra não mexe no formulário do PGMEI
        nav.close()


# ---------- rotina diária sem SERPRO ----------
def test_rotina_sem_serpro(cfg, banco, gestor):
    cfg.serpro_ambiente = "nenhum"
    m = Motor(cfg, banco, gestor, lambda: None, hoje=lambda: HOJE, dormir=lambda s: None, aleatorio=lambda a, b: a)
    r = m.executar("agendada")
    assert r["estado"] == "concluida" and r["guias_emitidas"] == 0 and r["guias_para_sessao_assistida"] == 2
    cs = {x["pa"]: x["status"] for x in banco.competencias(CNPJ_A)}
    assert cs == {"202608": "nao_consultado", "202609": "nao_consultado", "202610": "pendente"}
    d = gestor.ler_doc("dasmei_clientes", "e1")
    assert d["situacao"] == "pendente" and d["precisaGuia"] == ["2026-10"] and not d["ultimaConsulta"]


def test_pagamento_informado_na_tela_e_desfeito(cfg, banco, gestor):
    cfg.serpro_ambiente = "nenhum"
    mk = lambda: Motor(cfg, banco, gestor, lambda: None, hoje=lambda: HOJE, dormir=lambda s: None, aleatorio=lambda a, b: a)
    gestor.gravar("dasmei_pagamentos", "e1_2026-10", {"data": "2026-11-15", "valor": 81.05, "por": "Thais",
                                                     "em": "2026-11-19T10:00", "obs": "comprovante no WhatsApp"})
    mk().executar("manual")
    c = banco.competencia(CNPJ_A, "202610")
    assert c["status"] == "pago_confirmado" and c["pago_em"] == "2026-11-15" and "Thais" in c["pago_evidencia"]
    d = gestor.ler_doc("dasmei_clientes", "e1")
    assert d["situacao"] == "consultado" and d["precisaGuia"] == []
    del gestor.docs["dasmei_pagamentos"]["e1_2026-10"]
    mk().executar("manual")
    c = banco.competencia(CNPJ_A, "202610")
    assert c["status"] == "pendente" and not c["pago_em"]
