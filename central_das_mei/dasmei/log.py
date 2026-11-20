"""Logs em arquivo com rotação. Tokens, senhas e PDFs nunca são registrados."""
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SENSIVEL = re.compile(r"(?i)(bearer\s+|jwt_token[\"':=\s]+|access_token[\"':=\s]+|password[\"':=\s]+|senha[\"':=\s]+)[^\s,\"'}]+")


class _Mascara(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        limpo = _SENSIVEL.sub(r"\1***", msg)
        if limpo != msg:
            record.msg, record.args = limpo, ()
        return True


def configurar(pasta: Path, nivel=logging.INFO) -> logging.Logger:
    pasta = Path(pasta) / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    lg = logging.getLogger("dasmei")
    lg.setLevel(nivel)
    if not lg.handlers:
        h = RotatingFileHandler(pasta / "dasmei.log", maxBytes=2_000_000, backupCount=10, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        h.addFilter(_Mascara())
        lg.addHandler(h)
        if sys.stderr is not None:          # pythonw (serviço sem janela) não tem console
            c = logging.StreamHandler()
            c.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
            c.addFilter(_Mascara())
            lg.addHandler(c)
    return lg
