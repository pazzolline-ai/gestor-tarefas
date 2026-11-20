"""Segredos no Cofre de Credenciais do Windows (via keyring/DPAPI).

Nada sensível é gravado em arquivo ou no banco. Em testes, use MemoriaSegredos.
"""
from __future__ import annotations

SERVICO = "CentralDasMei"
CHAVES = ("gestor_senha", "serpro_consumer_key", "serpro_consumer_secret", "certificado_senha")


class Segredos:
    def __init__(self, servico: str = SERVICO):
        import keyring  # import tardio: os testes não dependem do cofre do sistema
        self._kr = keyring
        self._servico = servico

    def ler(self, chave: str) -> str | None:
        return self._kr.get_password(self._servico, chave)

    def gravar(self, chave: str, valor: str) -> None:
        if chave not in CHAVES:
            raise KeyError(chave)
        self._kr.set_password(self._servico, chave, valor)

    def apagar(self, chave: str) -> None:
        try:
            self._kr.delete_password(self._servico, chave)
        except Exception:
            pass

    def exigir(self, chave: str) -> str:
        v = self.ler(chave)
        if v is None:
            raise RuntimeError(f"Segredo '{chave}' não configurado. Rode: python -m dasmei configurar")
        return v


class MemoriaSegredos(Segredos):
    def __init__(self, valores: dict | None = None):
        self._v = dict(valores or {})

    def ler(self, chave):
        return self._v.get(chave)

    def gravar(self, chave, valor):
        self._v[chave] = valor

    def apagar(self, chave):
        self._v.pop(chave, None)
