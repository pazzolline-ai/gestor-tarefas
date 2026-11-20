"""Envio do relatório por e-mail/WhatsApp — PREPARADO, mas desligado.

Nenhuma mensagem é enviada hoje. Para ligar, implemente um canal autorizado
(ex.: SMTP do escritório, API oficial do WhatsApp Business) como subclasse de
Canal e registre em CANAIS. O texto já está pronto em relatorio.texto_curto().
"""
from __future__ import annotations

from .relatorio import texto_curto


class Canal:
    nome = "base"

    def enviar(self, texto: str, resumo: dict) -> bool:
        raise NotImplementedError


CANAIS: list[Canal] = []   # vazio = nenhum envio


def notificar(resumo: dict) -> list[str]:
    enviados = []
    for c in CANAIS:
        if c.enviar(texto_curto(resumo), resumo):
            enviados.append(c.nome)
    return enviados
