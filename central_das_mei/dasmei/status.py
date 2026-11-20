"""Status oficiais da Central de DAS MEI.

Regra de ouro: emitir ou baixar uma guia NUNCA a torna paga. "Pago confirmado"
só é registrado com evidência do serviço oficial de pagamentos (PAGTOWEB).
"""
from enum import Enum


class Status(str, Enum):
    NAO_CONSULTADO = "nao_consultado"
    CONSULTADO = "consultado"
    DAS_EMITIDO = "das_emitido"
    DAS_DISPONIVEL = "das_disponivel"
    GUIA_BAIXADA = "guia_baixada"
    PENDENTE = "pendente"
    VENCIDO = "vencido"
    PAGO_CONFIRMADO = "pago_confirmado"
    AGUARDANDO_AUTENTICACAO = "aguardando_autenticacao"
    ERRO_CONSULTA = "erro_consulta"
    EXIGE_INTERVENCAO = "exige_intervencao"


ROTULO = {
    Status.NAO_CONSULTADO: "Não consultado",
    Status.CONSULTADO: "Consultado",
    Status.DAS_EMITIDO: "DAS emitido",
    Status.DAS_DISPONIVEL: "DAS disponível para download",
    Status.GUIA_BAIXADA: "Guia baixada",
    Status.PENDENTE: "Pendente",
    Status.VENCIDO: "Vencido",
    Status.PAGO_CONFIRMADO: "Pago confirmado",
    Status.AGUARDANDO_AUTENTICACAO: "Aguardando autenticação",
    Status.ERRO_CONSULTA: "Erro de consulta",
    Status.EXIGE_INTERVENCAO: "Exige intervenção humana",
}

# Situação da GUIA (documento) — ciclo de vida do arquivo
GUIA = (Status.DAS_EMITIDO, Status.DAS_DISPONIVEL, Status.GUIA_BAIXADA)
_ORDEM_GUIA = {s: i for i, s in enumerate(GUIA)}

# Situação da COMPETÊNCIA (obrigação de pagar)
COMPETENCIA = (Status.NAO_CONSULTADO, Status.PENDENTE, Status.VENCIDO, Status.PAGO_CONFIRMADO,
               Status.AGUARDANDO_AUTENTICACAO, Status.ERRO_CONSULTA, Status.EXIGE_INTERVENCAO)


class TransicaoInvalida(ValueError):
    pass


def avancar_guia(atual, novo: Status) -> Status:
    """A guia só anda para frente (emitida → disponível → baixada)."""
    if novo not in _ORDEM_GUIA:
        raise TransicaoInvalida(f"{novo} não é status de guia")
    if atual is None:
        if novo != Status.DAS_EMITIDO:
            raise TransicaoInvalida("uma guia nova começa como 'DAS emitido'")
        return novo
    atual = Status(atual)
    if _ORDEM_GUIA[novo] < _ORDEM_GUIA[atual]:
        raise TransicaoInvalida(f"{ROTULO[atual]} → {ROTULO[novo]} não é permitido")
    return novo


def competencia_pode_ir(atual, novo: Status, evidencia_pagamento: bool = False) -> Status:
    novo = Status(novo)
    if novo not in COMPETENCIA:
        raise TransicaoInvalida(f"{novo} não é status de competência")
    if novo == Status.PAGO_CONFIRMADO and not evidencia_pagamento:
        raise TransicaoInvalida("pagamento só pode ser confirmado com evidência oficial")
    if atual is not None and Status(atual) == Status.PAGO_CONFIRMADO and novo != Status.PAGO_CONFIRMADO:
        # um pagamento confirmado não é desfeito automaticamente
        raise TransicaoInvalida("competência paga não volta a ficar em aberto automaticamente")
    return novo


# Prioridade para resumir a situação de um cliente (maior = mais urgente)
_PRIORIDADE = {
    Status.EXIGE_INTERVENCAO: 90, Status.AGUARDANDO_AUTENTICACAO: 80, Status.ERRO_CONSULTA: 70,
    Status.VENCIDO: 60, Status.PENDENTE: 50, Status.NAO_CONSULTADO: 40,
    Status.PAGO_CONFIRMADO: 10, Status.CONSULTADO: 5,
}


def resumo_cliente(status_competencias) -> Status:
    lst = [Status(s) for s in status_competencias if s]
    if not lst:
        return Status.NAO_CONSULTADO
    pior = max(lst, key=lambda s: _PRIORIDADE.get(s, 0))
    return Status.CONSULTADO if pior == Status.PAGO_CONFIRMADO else pior
