"""Validação e leitura do PDF do DAS-MEI.

O PDF só é aceito se: começa com %PDF, termina com %%EOF, abre no leitor e tem
ao menos uma página. Os dados (CNPJ, período, vencimento, valor, número do
documento) são extraídos do texto quando o layout permite e conferidos com os
dados devolvidos pela API. Divergência = guia vai para revisão humana.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from . import cnpj as cnpjmod
from .competencia import MESES_TXT


class PdfInvalido(ValueError):
    pass


@dataclass
class DadosPdf:
    paginas: int = 0
    texto_legivel: bool = False
    cnpj: str | None = None
    periodo: str | None = None          # AAAA-MM (primeiro encontrado)
    periodos: list = field(default_factory=list)   # todos os períodos citados no PDF
    vencimento: str | None = None       # AAAA-MM-DD
    valor_total: float | None = None
    numero_documento: str | None = None
    avisos: list = field(default_factory=list)

    def dict(self):
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _data(s):
    d, m, a = s.split("/")
    return f"{a}-{m}-{d}"


def _valor(s):
    return float(s.replace(".", "").replace(",", "."))


def ler(dados: bytes) -> DadosPdf:
    if not dados or not dados.lstrip()[:5].startswith(b"%PDF-"):
        raise PdfInvalido("arquivo não começa com %PDF-")
    if b"%%EOF" not in dados[-2048:]:
        raise PdfInvalido("PDF incompleto (sem %%EOF no final)")
    try:
        from pypdf import PdfReader
        leitor = PdfReader(io.BytesIO(dados))
        n = len(leitor.pages)
        texto = "\n".join((p.extract_text() or "") for p in leitor.pages)
    except Exception as e:  # noqa: BLE001 - qualquer falha do leitor = PDF inválido
        raise PdfInvalido(f"PDF não abre: {e}") from e
    if n < 1:
        raise PdfInvalido("PDF sem páginas")
    r = DadosPdf(paginas=n, texto_legivel=len(texto.strip()) > 20)
    if not r.texto_legivel:
        r.avisos.append("PDF sem texto legível; dados conferidos só pela API")
        return r
    t = re.sub(r"[ \t]+", " ", texto)
    m = re.search(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", t)
    if m:
        r.cnpj = cnpjmod.limpar(m.group())
    for m in re.finditer(r"(?i)(" + "|".join(MESES_TXT + ["marco"]) + r")\s*/\s*(\d{4})", t):
        nome = m.group(1).lower().replace("marco", "março")
        p = f"{m.group(2)}-{MESES_TXT.index(nome) + 1:02d}"
        if p not in r.periodos:
            r.periodos.append(p)
    r.periodo = r.periodos[0] if r.periodos else None
    m = re.search(r"(?i)(?:pagar este documento at[ée]|data de vencimento|vencimento)\D{0,40}?(\d{2}/\d{2}/\d{4})", t)
    if m:
        r.vencimento = _data(m.group(1))
    m = re.search(r"(?i)valor total do documento\D{0,40}?(\d{1,3}(?:\.\d{3})*,\d{2})", t)
    if m:
        r.valor_total = _valor(m.group(1))
    m = re.search(r"(?i)n[úu]mero do documento\D{0,40}?([\d.\-]{10,})", t)
    if m:
        r.numero_documento = re.sub(r"\D", "", m.group(1))
    return r


def conferir(pdf: DadosPdf, cnpj: str, periodo_iso: str, vencimento_iso: str | None,
             total: float | None, numero_documento: str | None) -> list[str]:
    """Compara o que foi lido no PDF com os dados da API. Retorna divergências."""
    div = []
    if pdf.cnpj and pdf.cnpj != cnpj:
        div.append(f"CNPJ no PDF ({pdf.cnpj}) diferente do cliente ({cnpj})")
    if pdf.periodo and pdf.periodo != periodo_iso:
        div.append(f"período no PDF ({pdf.periodo}) diferente do pedido ({periodo_iso})")
    if pdf.vencimento and vencimento_iso and pdf.vencimento != vencimento_iso:
        div.append(f"vencimento no PDF ({pdf.vencimento}) diferente da API ({vencimento_iso})")
    if pdf.valor_total is not None and total is not None and abs(pdf.valor_total - total) > 0.009:
        div.append(f"valor no PDF ({pdf.valor_total:.2f}) diferente da API ({total:.2f})")
    if pdf.numero_documento and numero_documento and re.sub(r"\D", "", numero_documento) != pdf.numero_documento:
        div.append("número do documento no PDF diferente da API")
    if pdf.texto_legivel and not pdf.cnpj:
        div.append("CNPJ não encontrado no texto do PDF")
    return div
