import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dasmei.banco import Banco  # noqa: E402
from dasmei.config import Config, Rotina  # noqa: E402
from dasmei.gestor import GestorMemoria  # noqa: E402
from dasmei.serpro import IntegraContador  # noqa: E402
from tests.apoio import CNPJ_A, CNPJ_B, SerproFalsa  # noqa: E402

HOJE = dt.date(2026, 11, 19)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("DASMEI_HOME", str(tmp_path / "app"))
    c = Config(contratante_cnpj="11222333000181", pasta_documentos=str(tmp_path / "CENTRAL_DAS_MEI"),
               pausa_entre_clientes=(0, 0), max_tentativas=3, limite_falhas_seguidas=3)
    c.rotina = Rotina(meses_retroativos=3)
    return c


@pytest.fixture
def banco(tmp_path):
    b = Banco(tmp_path / "t.db")
    yield b
    b.fechar()


@pytest.fixture
def serpro_falsa():
    return SerproFalsa()


@pytest.fixture
def fabrica(serpro_falsa):
    def criar():
        return IntegraContador(ambiente="producao", contratante="11222333000181", consumer_key="k",
                               consumer_secret="s", transport=serpro_falsa.transporte(), intervalo_min=0,
                               dormir=lambda s: None)
    return criar


@pytest.fixture
def gestor():
    return GestorMemoria({"empresas": {
        "e1": {"regime": "MEI", "cnpj": CNPJ_A, "fantasia": "Alfa Doces"},
        "e2": {"regime": "MEI", "cnpj": CNPJ_B, "razao": "Beta Serviços"},
        "e3": {"regime": "Simples Nacional", "cnpj": "11222333000181", "fantasia": "Não é MEI"},
        "e4": {"regime": "MEI", "cnpj": "123", "fantasia": "Cadastro Ruim"},
        "e5": {"regime": "MEI", "cnpj": CNPJ_A, "fantasia": "Inativa", "inativa": True},
        "e6": {"regime": "MEI", "cnpj": CNPJ_B, "fantasia": "Sem guia", "guiaMensal": False},
    }})
