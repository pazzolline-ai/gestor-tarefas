"""Validação e formatação de CNPJ (dígitos verificadores oficiais)."""
import re

_PESOS1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
_PESOS2 = [6] + _PESOS1


def limpar(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _dv(numeros: str, pesos) -> str:
    soma = sum(int(n) * p for n, p in zip(numeros, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def valido(valor) -> bool:
    c = limpar(valor)
    if len(c) != 14 or c == c[0] * 14:
        return False
    return c[12] == _dv(c[:12], _PESOS1) and c[13] == _dv(c[:13], _PESOS2)


def formatar(valor) -> str:
    c = limpar(valor)
    if len(c) != 14:
        return str(valor or "")
    return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"


def gerar_com_dv(base12: str) -> str:
    """Completa os 2 dígitos verificadores (usado nos testes com dados fictícios)."""
    b = limpar(base12)[:12]
    d1 = _dv(b, _PESOS1)
    return b + d1 + _dv(b + d1, _PESOS2)
