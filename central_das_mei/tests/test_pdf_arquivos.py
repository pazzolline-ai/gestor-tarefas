import pytest

from dasmei import arquivos, pdf
from dasmei.competencia import Competencia
from tests.apoio import CNPJ_A, pdf_das, pdf_texto


def test_pdf_valido_extrai_dados():
    b = pdf_das(CNPJ_A, 2026, 3, "2026-04-20", 81.05, "07202000000001234")
    d = pdf.ler(b)
    assert d.paginas == 1 and d.texto_legivel
    assert d.cnpj == CNPJ_A and d.periodo == "2026-03" and d.vencimento == "2026-04-20"
    assert d.valor_total == 81.05 and d.numero_documento == "07202000000001234"
    assert pdf.conferir(d, CNPJ_A, "2026-03", "2026-04-20", 81.05, "07202000000001234") == []


def test_pdf_divergente():
    d = pdf.ler(pdf_das(CNPJ_A, 2026, 3, "2026-04-20", 81.05, "07202000000001234"))
    div = pdf.conferir(d, CNPJ_A, "2026-04", "2026-05-20", 90.0, "07202000000009999")
    assert len(div) == 4


@pytest.mark.parametrize("ruim", [b"", b"nao e pdf", b"%PDF-1.4 truncado", pdf_texto(["x"])[:-30]])
def test_pdf_invalido(ruim):
    with pytest.raises(pdf.PdfInvalido):
        pdf.ler(ruim)


def test_pdf_sem_texto_vira_aviso():
    d = pdf.ler(pdf_texto([]))
    assert not d.texto_legivel and d.avisos


def test_pastas_e_nome(tmp_path):
    c = Competencia(2026, 3)
    p = arquivos.pasta_competencia(tmp_path / "CENTRAL_DAS_MEI", CNPJ_A, c)
    assert p.parts[-3:] == (CNPJ_A, "2026", "MARCO")
    assert arquivos.nome_guia(CNPJ_A, c, "2026-04-20", "07.20.123") == f"DAS-MEI_{CNPJ_A}_2026-03_venc-2026-04-20_0720123.pdf"
    with pytest.raises(ValueError):
        arquivos.pasta_competencia(tmp_path, "../x", c)


def test_nunca_sobrescreve(tmp_path):
    p1, novo1 = arquivos.gravar_sem_sobrescrever(tmp_path, "a.pdf", b"conteudo 1")
    p2, novo2 = arquivos.gravar_sem_sobrescrever(tmp_path, "a.pdf", b"conteudo 1")   # duplicado
    p3, novo3 = arquivos.gravar_sem_sobrescrever(tmp_path, "a.pdf", b"conteudo 2")   # diferente
    assert novo1 and not novo2 and novo3
    assert p1 == p2 and p3.name == "a_v2.pdf"
    assert p1.read_bytes() == b"conteudo 1" and p3.read_bytes() == b"conteudo 2"
    assert not list(tmp_path.glob(".*.tmp"))


def test_apagar_seguro(tmp_path):
    f = tmp_path / "segredo.tmp"
    f.write_bytes(b"chave privada")
    arquivos.apagar_seguro(f)
    assert not f.exists()
