import logging

import pytest

from dasmei import config as cfgmod
from dasmei import log as logmod
from dasmei.segredos import MemoriaSegredos


def test_config_ida_e_volta(tmp_path):
    c = cfgmod.Config(email_robo="robo@escritorio", contratante_cnpj="11222333000181",
                      certificado_pfx=r"C:\certs\escritorio.pfx", pasta_documentos=r"D:\CENTRAL_DAS_MEI")
    p = cfgmod.salvar(c, tmp_path / "config.toml")
    texto = p.read_text(encoding="utf-8")
    assert "senha" not in texto.lower().replace("senhas e chaves", "")   # nenhum segredo no arquivo
    lido = cfgmod.carregar(p)
    assert lido.certificado_pfx == r"C:\certs\escritorio.pfx" and lido.pasta_documentos == r"D:\CENTRAL_DAS_MEI"
    assert lido.autor_cnpj == "11222333000181" and lido.rotina.horario == "07:00"


def test_config_ambiente_invalido(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[serpro]\nambiente = "teste"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        cfgmod.carregar(p)


def test_config_ausente(tmp_path):
    with pytest.raises(FileNotFoundError):
        cfgmod.carregar(tmp_path / "nao.toml")


def test_log_mascara_tokens(tmp_path):
    lg = logmod.configurar(tmp_path)
    lg.info("Authorization: Bearer abc.def.ghi jwt_token=XYZ123 password=segredo")
    for h in lg.handlers:
        h.flush()
    txt = (tmp_path / "logs" / "dasmei.log").read_text(encoding="utf-8")
    assert "abc.def" not in txt and "XYZ123" not in txt and "segredo" not in txt and "***" in txt
    for h in list(lg.handlers):
        lg.removeHandler(h)
        h.close()


def test_segredos_memoria():
    s = MemoriaSegredos()
    s.gravar("gestor_senha", "x")
    assert s.exigir("gestor_senha") == "x"
    s.apagar("gestor_senha")
    with pytest.raises(RuntimeError):
        s.exigir("gestor_senha")
