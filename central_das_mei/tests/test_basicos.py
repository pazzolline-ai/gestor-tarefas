import datetime as dt

import pytest

from dasmei import cnpj
from dasmei.competencia import Competencia, feriados_nacionais, janela, vencimento
from dasmei.status import (Status, TransicaoInvalida, avancar_guia, competencia_pode_ir, resumo_cliente)


# ---------- CNPJ ----------
@pytest.mark.parametrize("v", ["11.222.333/0001-81", "11222333000181"])
def test_cnpj_valido(v):
    assert cnpj.valido(v)


@pytest.mark.parametrize("v", ["11.222.333/0001-82", "00000000000000", "123", "", None, "11111111111111"])
def test_cnpj_invalido(v):
    assert not cnpj.valido(v)


def test_cnpj_formatar_e_gerar():
    c = cnpj.gerar_com_dv("112223330001")
    assert c == "11222333000181" and cnpj.formatar(c) == "11.222.333/0001-81"


# ---------- competências ----------
def test_competencia_formatos():
    assert Competencia.de_texto("202603") == Competencia(2026, 3)
    assert Competencia.de_texto("2026-03") == Competencia(2026, 3)
    assert Competencia.de_texto("03/2026") == Competencia(2026, 3)
    assert Competencia(2026, 3).pasta_mes == "MARCO"
    assert Competencia(2026, 12).mais(1) == Competencia(2027, 1)
    with pytest.raises(ValueError):
        Competencia(2026, 13)


def test_vencimento_dia_20_e_dia_util():
    assert vencimento(Competencia(2026, 9)) == dt.date(2026, 10, 20)      # terça
    assert vencimento(Competencia(2026, 5)) == dt.date(2026, 6, 22)      # 20/06/2026 é sábado
    assert dt.date(2026, 4, 3) in feriados_nacionais(2026)               # Sexta-feira Santa


def test_janela():
    j = janela(dt.date(2026, 11, 19), 3)
    assert [c.iso for c in j] == ["2026-08", "2026-09", "2026-10"]
    assert janela(dt.date(2026, 1, 5), 2)[-1] == Competencia(2025, 12)


# ---------- status ----------
def test_guia_so_avanca():
    s = avancar_guia(None, Status.DAS_EMITIDO)
    s = avancar_guia(s, Status.DAS_DISPONIVEL)
    s = avancar_guia(s, Status.GUIA_BAIXADA)
    assert s == Status.GUIA_BAIXADA
    with pytest.raises(TransicaoInvalida):
        avancar_guia(Status.GUIA_BAIXADA, Status.DAS_EMITIDO)
    with pytest.raises(TransicaoInvalida):
        avancar_guia(None, Status.GUIA_BAIXADA)


def test_pago_exige_evidencia():
    with pytest.raises(TransicaoInvalida):
        competencia_pode_ir(Status.PENDENTE, Status.PAGO_CONFIRMADO)
    assert competencia_pode_ir(Status.PENDENTE, Status.PAGO_CONFIRMADO, evidencia_pagamento=True)
    with pytest.raises(TransicaoInvalida):
        competencia_pode_ir(Status.PAGO_CONFIRMADO, Status.PENDENTE)
    with pytest.raises(TransicaoInvalida):   # guia baixada não é status de pagamento
        competencia_pode_ir(Status.PENDENTE, Status.GUIA_BAIXADA)


def test_resumo_cliente():
    assert resumo_cliente([]) == Status.NAO_CONSULTADO
    assert resumo_cliente(["pago_confirmado", "pago_confirmado"]) == Status.CONSULTADO
    assert resumo_cliente(["pago_confirmado", "vencido", "pendente"]) == Status.VENCIDO
    assert resumo_cliente(["vencido", "exige_intervencao"]) == Status.EXIGE_INTERVENCAO
