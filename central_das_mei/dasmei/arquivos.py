"""Organização dos PDFs: CENTRAL_DAS_MEI/<CNPJ>/<ANO>/<MES>/

- nunca sobrescreve: se já existe arquivo igual (mesmo SHA-256) reaproveita;
  se existe arquivo diferente com o mesmo nome, grava como _v2, _v3...
- gravação atômica (arquivo temporário + criação exclusiva)
- temporários são sobrescritos com zeros antes de apagar
"""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .competencia import Competencia


def sha256(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(65536), b""):
            h.update(bloco)
    return h.hexdigest()


def pasta_competencia(base: Path | str, cnpj: str, comp: Competencia) -> Path:
    if not re.fullmatch(r"\d{14}", cnpj):
        raise ValueError("CNPJ deve ter 14 dígitos")
    return Path(base) / cnpj / str(comp.ano) / comp.pasta_mes


def nome_guia(cnpj: str, comp: Competencia, vencimento: str | None, numero_documento: str) -> str:
    venc = re.sub(r"[^0-9-]", "", vencimento or "") or "sem-venc"
    doc = re.sub(r"[^0-9A-Za-z]", "", numero_documento or "") or "sem-numero"
    return f"DAS-MEI_{cnpj}_{comp.iso}_venc-{venc}_{doc}.pdf"


def apagar_seguro(caminho: Path):
    try:
        p = Path(caminho)
        if p.exists():
            n = p.stat().st_size
            with open(p, "r+b") as f:
                f.write(b"\0" * n)
                f.flush()
                os.fsync(f.fileno())
            p.unlink()
    except OSError:
        pass


def gravar_sem_sobrescrever(pasta: Path, nome: str, dados: bytes) -> tuple[Path, bool]:
    """Retorna (caminho_final, novo). novo=False quando o mesmo conteúdo já existia."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    h = sha256(dados)
    raiz, ext = os.path.splitext(nome)
    for n in range(1, 1000):
        alvo = pasta / (nome if n == 1 else f"{raiz}_v{n}{ext}")
        if alvo.exists():
            if sha256_arquivo(alvo) == h:
                return alvo, False
            continue
        tmp = pasta / f".{alvo.name}.{os.getpid()}.tmp"
        try:
            with open(tmp, "wb") as f:
                f.write(dados)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.link(tmp, alvo)          # falha se o alvo surgiu nesse meio-tempo
            except FileExistsError:
                continue
            except OSError:
                # sistemas sem hardlink: criação exclusiva
                try:
                    fd = os.open(alvo, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0))
                except FileExistsError:
                    continue
                with os.fdopen(fd, "wb") as f:
                    f.write(dados)
            return alvo, True
        finally:
            if tmp.exists():
                tmp.unlink()
    raise RuntimeError("muitas versões do mesmo arquivo")
