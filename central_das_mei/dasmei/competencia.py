"""Competências (períodos de apuração) e vencimento do DAS-MEI.

Regra: o DAS-MEI vence no dia 20 do mês seguinte ao da competência; se não for
dia útil, passa para o próximo dia útil. O vencimento devolvido pela Receita na
guia emitida sempre prevalece sobre este cálculo, que serve apenas para saber se
uma competência ainda não emitida já está vencida.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

MESES = ["JANEIRO", "FEVEREIRO", "MARCO", "ABRIL", "MAIO", "JUNHO", "JULHO",
         "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO"]
MESES_TXT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
             "agosto", "setembro", "outubro", "novembro", "dezembro"]


@dataclass(frozen=True, order=True)
class Competencia:
    ano: int
    mes: int

    def __post_init__(self):
        if not (1 <= self.mes <= 12) or not (2000 <= self.ano <= 2100):
            raise ValueError(f"competência inválida: {self.ano}-{self.mes}")

    @classmethod
    def de_texto(cls, txt: str) -> "Competencia":
        """Aceita AAAAMM, AAAA-MM, MM/AAAA e datas ISO (usa ano e mês)."""
        s = str(txt).strip()
        if "/" in s:
            m, a = s.split("/")[:2]
            return cls(int(a), int(m))
        dig = "".join(ch for ch in s if ch.isdigit())
        if len(dig) < 6:
            raise ValueError(f"competência inválida: {txt!r}")
        return cls(int(dig[:4]), int(dig[4:6]))

    @classmethod
    def de_data(cls, d: dt.date) -> "Competencia":
        return cls(d.year, d.month)

    def mais(self, n: int) -> "Competencia":
        t = self.ano * 12 + (self.mes - 1) + n
        return Competencia(t // 12, t % 12 + 1)

    @property
    def pa(self) -> str:          # formato da API: AAAAMM
        return f"{self.ano}{self.mes:02d}"

    @property
    def iso(self) -> str:         # formato do gestor: AAAA-MM
        return f"{self.ano}-{self.mes:02d}"

    @property
    def pasta_mes(self) -> str:
        return MESES[self.mes - 1]

    @property
    def texto(self) -> str:
        return f"{MESES_TXT[self.mes - 1]}/{self.ano}"

    def primeiro_dia(self) -> dt.date:
        return dt.date(self.ano, self.mes, 1)

    def __str__(self):
        return self.iso


def _pascoa(ano: int) -> dt.date:
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return dt.date(ano, mes, dia)


def feriados_nacionais(ano: int) -> set[dt.date]:
    fixos = [(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (11, 20), (12, 25)]
    s = {dt.date(ano, m, d) for m, d in fixos}
    s.add(_pascoa(ano) - dt.timedelta(days=2))  # Sexta-feira Santa
    return s


def dia_util(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in feriados_nacionais(d.year)


def vencimento(c: Competencia) -> dt.date:
    prox = c.mais(1)
    d = dt.date(prox.ano, prox.mes, 20)
    while not dia_util(d):
        d += dt.timedelta(days=1)
    return d


def janela(hoje: dt.date, meses_retroativos: int, incluir_mes_atual: bool = False) -> list[Competencia]:
    """Competências a acompanhar: da mais antiga da janela até o mês anterior
    (ou o mês atual, se configurado), em ordem cronológica."""
    fim = Competencia.de_data(hoje) if incluir_mes_atual else Competencia.de_data(hoje).mais(-1)
    n = max(1, int(meses_retroativos))
    return [fim.mais(-i) for i in range(n - 1, -1, -1)]
