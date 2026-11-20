"""Tela da versão separada: servidor local em http://127.0.0.1:<porta>.

- Só escuta no próprio PC (127.0.0.1).
- Acesso por chave aleatória: o atalho "Central de DAS MEI" abre o navegador com
  ?t=<chave>, que vira um cookie HttpOnly/SameSite=Strict. Sem a chave: acesso negado.
- Pedidos que alteram dados exigem o cabeçalho X-DM (proteção contra CSRF).
- PDFs e pastas só são servidos/abertos se estiverem dentro de CENTRAL_DAS_MEI.
"""
from __future__ import annotations

import getpass
import http.server
import json
import logging
import os
import secrets
import sys
import threading
import uuid
from dataclasses import replace
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .banco import agora
from .config import Rotina
from .gestor import COL_CLIENTES, COL_CMD, COL_EMPRESAS, COL_EXEC, COL_PAG, COL_ROBO
from .local import GestorLocal
from .relatorio import html_relatorio

log = logging.getLogger("dasmei")
PAGINA = Path(__file__).with_name("web") / "central.html"
CAMPOS_CONFIG = {"horario", "dias_semana", "meses_retroativos", "emitir_competencia_atual", "emitir_vencidos",
                 "consultar_pagamentos", "pausado", "excluidos"}


def arquivo_token(pasta_app: Path) -> Path:
    return Path(pasta_app) / "web_token"


def obter_token(pasta_app: Path) -> str:
    p = arquivo_token(pasta_app)
    if p.exists():
        t = p.read_text(encoding="utf-8").strip()
        if len(t) >= 32:
            return t
    t = secrets.token_urlsafe(32)
    p.write_text(t, encoding="utf-8")
    return t


class ServidorWeb:
    def __init__(self, cfg, gestor: GestorLocal, *, porta=8777, token=None, acordar=None, usuario=None):
        self.cfg, self.gestor = cfg, gestor
        self.token = token or obter_token(cfg.pasta_sistema)
        self.acordar = acordar or (lambda: None)
        self.usuario = usuario or getpass.getuser()
        self.base = Path(cfg.pasta_documentos).resolve()
        srv = self

        class H(http.server.BaseHTTPRequestHandler):
            server_version = "CentralDasMei"

            def log_message(self, *a):
                pass

            def _cookie_ok(self):
                c = SimpleCookie(self.headers.get("Cookie") or "")
                return "dm" in c and secrets.compare_digest(c["dm"].value, srv.token)

            def _enviar(self, status, corpo: bytes, ct="application/json; charset=utf-8", extra=None):
                self.send_response(status)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(corpo)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(corpo)

            def _json(self, obj, status=200):
                self._enviar(status, json.dumps(obj, ensure_ascii=False).encode())

            def _corpo(self):
                n = int(self.headers.get("Content-Length") or 0)
                if n > 20_000_000:
                    raise ValueError("arquivo grande demais")
                return self.rfile.read(n) if n else b""

            def do_GET(self):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                if u.path == "/" and q.get("t"):
                    if secrets.compare_digest(q["t"], srv.token):
                        return self._enviar(303, b"", "text/plain", {
                            "Location": "/", "Set-Cookie": f"dm={srv.token}; HttpOnly; SameSite=Strict; Path=/"})
                    return self._enviar(403, b"Chave invalida", "text/plain")
                if not self._cookie_ok():
                    return self._enviar(401, "<h3>Abra pelo atalho “Central de DAS MEI” da área de trabalho.</h3>".encode(),
                                        "text/html; charset=utf-8")
                if u.path == "/":
                    return self._enviar(200, PAGINA.read_bytes(), "text/html; charset=utf-8",
                                        {"Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; "
                                                                    "script-src 'self' 'unsafe-inline'; img-src 'self' data:"})
                if u.path == "/api/estado":
                    return self._json(srv.estado())
                if u.path == "/arquivo":
                    p = srv.dentro_da_base(q.get("caminho", ""))
                    if not p or p.suffix.lower() != ".pdf" or not p.is_file():
                        return self._enviar(404, b"Arquivo nao encontrado", "text/plain")
                    return self._enviar(200, p.read_bytes(), "application/pdf",
                                        {"Content-Disposition": f'inline; filename="{p.name}"'})
                if u.path.startswith("/relatorio/"):
                    r = srv.gestor.ler_doc(COL_EXEC, u.path.rsplit("/", 1)[-1])
                    if not r:
                        return self._enviar(404, b"Relatorio nao encontrado", "text/plain")
                    return self._enviar(200, html_relatorio(r).encode(), "text/html; charset=utf-8")
                self._enviar(404, b"", "text/plain")

            def do_POST(self):
                if not self._cookie_ok() or self.headers.get("X-DM") != "1":
                    return self._json({"erro": "acesso negado"}, 403)
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                try:
                    corpo = self._corpo()
                    if u.path == "/api/importar":
                        return self._json(srv.gestor.importar(q.get("nome", "planilha.csv"), corpo))
                    d = json.loads(corpo or b"{}")
                    rota = {"/api/empresa": srv.salvar_empresa, "/api/config": srv.salvar_config,
                            "/api/comando": srv.comando, "/api/pagamento": srv.pagamento,
                            "/api/pagamento/apagar": srv.apagar_pagamento, "/api/abrir": srv.abrir_pasta}.get(u.path)
                    if not rota:
                        return self._json({"erro": "rota inexistente"}, 404)
                    return self._json(rota(d))
                except ValueError as e:
                    return self._json({"erro": str(e)}, 400)
                except Exception as e:  # noqa: BLE001
                    log.exception("Erro na tela local")
                    return self._json({"erro": f"erro interno: {e.__class__.__name__}"}, 500)

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", porta), H)
        self.porta = self.httpd.server_address[1]

    # ------------------------------------------------------------ dados
    def url(self, com_token=True):
        return f"http://127.0.0.1:{self.porta}/" + (f"?t={self.token}" if com_token else "")

    def estado(self):
        g = self.gestor
        execs = sorted((d for _, d in g.ler_col(COL_EXEC)), key=lambda x: x.get("inicio") or "", reverse=True)[:15]
        return {
            "versao": __version__, "usuario": self.usuario, "pasta": str(self.base),
            "modo": "assistido" if self.cfg.modo_assistido else "automatico",
            "empresas": [{"id": i, **e} for i, e in g.ler_col(COL_EMPRESAS)],
            "clientes": dict(g.ler_col(COL_CLIENTES)),
            "execucoes": [{k: v for k, v in x.items()} for x in execs],
            "robo": {"status": g.ler_doc(COL_ROBO, "status") or {},
                     "config": {**Rotina().__dict__, **self.cfg.rotina.__dict__, **(g.ler_doc(COL_ROBO, "config") or {})}},
            "comandos": [d for _, d in g.ler_col(COL_CMD) if d.get("status") in ("pendente", "em_andamento")],
            "pagamentos": dict(g.ler_col(COL_PAG)),
        }

    def salvar_empresa(self, d):
        eid = self.gestor.salvar_empresa(d, d.get("id") or None)
        return {"ok": True, "id": eid}

    def salvar_config(self, d):
        atual = self.gestor.ler_doc(COL_ROBO, "config") or {}
        novo = {**atual, **{k: v for k, v in d.items() if k in CAMPOS_CONFIG}}
        try:
            r = replace(Rotina(), **{k: v for k, v in novo.items() if k in CAMPOS_CONFIG})
            r.validar()
        except (TypeError, ValueError) as e:
            raise ValueError(f"configuração inválida: {e}") from e
        novo.update(alteradoPor=self.usuario, alteradoEm=agora())
        self.gestor.gravar(COL_ROBO, "config", novo)
        self.acordar()
        return {"ok": True}

    def comando(self, d):
        acao = d.get("acao")
        if acao not in ("executar", "assistido"):
            raise ValueError("ação inválida")
        if any(c.get("status") in ("pendente", "em_andamento") for _, c in self.gestor.ler_col(COL_CMD)):
            raise ValueError("Já existe um pedido em andamento")
        ids = d.get("empresaIds") or None
        self.gestor.gravar(COL_CMD, uuid.uuid4().hex, {"acao": acao, "status": "pendente", "empresaIds": ids,
                                                       "pedidoPor": self.usuario, "criado": agora()})
        self.acordar()
        return {"ok": True}

    def pagamento(self, d):
        eid, comp, data = d.get("empresaId"), str(d.get("comp") or ""), str(d.get("data") or "")
        if not self.gestor.ler_doc(COL_EMPRESAS, eid or ""):
            raise ValueError("cliente inexistente")
        import re
        if not re.fullmatch(r"\d{4}-\d{2}", comp) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", data):
            raise ValueError("competência ou data inválida")
        v = d.get("valor")
        self.gestor.gravar(COL_PAG, f"{eid}_{comp}", {"empresaId": eid, "comp": comp, "data": data,
                                                     "valor": float(v) if v not in (None, "") else None,
                                                     "obs": str(d.get("obs") or "")[:300], "por": self.usuario, "em": agora()})
        self.gestor.banco.auditar("pagamento_informado_tela", None, {"empresaId": eid, "comp": comp, "por": self.usuario})
        return {"ok": True}

    def apagar_pagamento(self, d):
        self.gestor.apagar(COL_PAG, str(d.get("id") or ""))
        self.gestor.banco.auditar("pagamento_informado_apagado", None, {"id": d.get("id"), "por": self.usuario})
        return {"ok": True}

    def dentro_da_base(self, caminho) -> Path | None:
        try:
            p = Path(caminho).resolve()
        except (OSError, ValueError):
            return None
        return p if p == self.base or self.base in p.parents else None

    def abrir_pasta(self, d):
        p = self.dentro_da_base(d.get("caminho", ""))
        if not p:
            raise ValueError("pasta fora de CENTRAL_DAS_MEI")
        alvo = p if p.is_dir() else p.parent
        if sys.platform == "win32":
            os.startfile(str(alvo))  # noqa: S606 - só pastas dentro de CENTRAL_DAS_MEI
        return {"ok": True, "pasta": str(alvo)}

    # ------------------------------------------------------------ ciclo de vida
    def iniciar(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        log.info("Tela local em %s", self.url(False))
        return self

    def parar(self):
        self.httpd.shutdown()
