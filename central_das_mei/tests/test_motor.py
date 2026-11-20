import datetime as dt
from pathlib import Path

import pytest

from dasmei.motor import Motor
from dasmei.status import Status
from tests.apoio import CNPJ_A, CNPJ_B
from tests.conftest import HOJE


def motor(cfg, banco, gestor, fabrica, hoje=HOJE):
    return Motor(cfg, banco, gestor, fabrica, hoje=lambda: hoje, dormir=lambda s: None, aleatorio=lambda a, b: a)


def comps(banco, c):
    return {r["pa"]: r for r in banco.competencias(c)}


def test_lote_completo(cfg, banco, gestor, fabrica, serpro_falsa):
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    # fila: e1, e2 aptos + e4 (CNPJ inválido)
    assert r["estado"] == "concluida" and r["total_clientes"] == 3 and r["processados"] == 3
    # janela 2026-08..2026-10: 08 e 09 vencidos (emitidos), 10 pendente (emitido) → 3 guias por cliente
    assert r["guias_emitidas"] == 6 and r["pdfs_baixados"] == 6
    assert r["das_vencidos"] == 4 and r["competencias_pendentes"] == 2
    assert r["consultas_ok"] == 2 and r["revisao_n"] == 1   # cadastro com CNPJ ruim
    cs = comps(banco, CNPJ_A)
    assert cs["202610"]["status"] == "pendente" and cs["202608"]["status"] == "vencido"
    # nada vira "pago" por ter sido emitido/baixado
    assert all(x["status"] != Status.PAGO_CONFIRMADO.value for x in cs.values())
    # arquivos organizados por CNPJ/ano/mês, com hash registrado
    guias = banco.guias(CNPJ_A)
    assert len(guias) == 3 and all(g["status"] == "guia_baixada" for g in guias)
    p = Path(guias[-1]["arquivo"])
    assert p.exists() and p.parts[-4:-1] == (CNPJ_A, "2026", "OUTUBRO")
    # gestor atualizado
    d = gestor.ler_doc("dasmei_clientes", "e1")
    assert d["situacao"] == "vencido" and d["guiasBaixadas"] == 3 and d["vencidos"] == ["2026-08", "2026-09"]
    assert d["pendentes"] == ["2026-10"] and d["ultimaConsulta"]
    assert gestor.ler_doc("dasmei_clientes", "e4")["situacao"] == "exige_intervencao"
    assert gestor.ler_doc("das", "e1_2026-10")["emitida"]                 # painel antigo do Início
    assert gestor.ler_doc("dasmei_execucoes", r["id"])["guias_emitidas"] == 6
    assert gestor.ler_doc("dasmei_robo", "status")["executando"] is False
    # relatório em arquivo
    assert list(Path(cfg.pasta_relatorios).glob("relatorio_*.html"))
    # operações com identificador único e auditoria
    ops = banco.operacoes_execucao(r["id"])
    assert len({o["id"] for o in ops}) == len(ops) and all(o["estado"] == "concluida" for o in ops)
    assert banco.um("SELECT COUNT(*) n FROM auditoria WHERE acao='das_emitido'")["n"] == 6


def test_segunda_execucao_nao_duplica(cfg, banco, gestor, fabrica, serpro_falsa):
    motor(cfg, banco, gestor, fabrica).executar("manual")
    emissoes = sum(1 for ch in serpro_falsa.chamadas if ch[1] == "GERARDASPDF21")
    r2 = motor(cfg, banco, gestor, fabrica).executar("manual")
    assert sum(1 for ch in serpro_falsa.chamadas if ch[1] == "GERARDASPDF21") == emissoes
    assert r2["guias_emitidas"] == 0 and len(banco.guias(CNPJ_A)) == 3


def test_guia_vencida_e_reemitida_e_antiga_substituida(cfg, banco, gestor, fabrica, serpro_falsa):
    motor(cfg, banco, gestor, fabrica).executar("manual")
    banco._x("UPDATE guias SET data_limite='2026-11-01' WHERE cnpj=? AND pa='202608'", (CNPJ_A,))
    r = motor(cfg, banco, gestor, fabrica, hoje=dt.date(2026, 11, 20)).executar("manual")
    g = banco.guias(CNPJ_A, "202608")
    assert len(g) == 2 and g[0]["substituida"] == 1 and g[1]["substituida"] == 0
    assert r["guias_emitidas"] == 1


def test_arquivo_apagado_gera_nova_guia(cfg, banco, gestor, fabrica):
    motor(cfg, banco, gestor, fabrica).executar("manual")
    Path(banco.guias(CNPJ_A, "202610")[0]["arquivo"]).unlink()
    motor(cfg, banco, gestor, fabrica, hoje=dt.date(2026, 11, 20)).executar("manual")
    ativa = [g for g in banco.guias(CNPJ_A, "202610") if not g["substituida"]][0]
    assert Path(ativa["arquivo"]).exists()


def test_pagamento_confirmado_por_evidencia_oficial(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.pagamentos[CNPJ_A] = [{
        "numeroDocumento": "07201111111111111", "tipo": {"codigo": "DAS", "descricao": "Documento de Arrecadação do Simples Nacional"},
        "periodoApuracao": "2026-09-01", "dataArrecadacao": "2026-10-18", "dataVencimento": "2026-10-20",
        "receitaPrincipal": {"codigo": "1001", "descricao": "SIMEI"}, "valorTotal": 81.05, "valorPrincipal": 81.05,
        "desmembramentos": []}]
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    c = comps(banco, CNPJ_A)["202609"]
    assert c["status"] == "pago_confirmado" and c["pago_em"] == "2026-10-18" and "PAGTOWEB" in c["pago_evidencia"]
    assert not banco.guias(CNPJ_A, "202609")          # pago: não emite guia
    assert r["pagamentos_confirmados"] == 1


def test_pagamento_sem_identificacao_vai_para_revisao(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.pagamentos[CNPJ_A] = [{
        "numeroDocumento": "999", "tipo": {"codigo": "DARF", "descricao": "DARF"}, "periodoApuracao": "2026-09-01",
        "dataArrecadacao": "2026-10-18", "receitaPrincipal": {"codigo": "0211", "descricao": "IRPF"},
        "valorTotal": 10, "valorPrincipal": 10, "desmembramentos": []}]
    motor(cfg, banco, gestor, fabrica).executar("manual")
    c = comps(banco, CNPJ_A)["202609"]
    assert c["status"] == "exige_intervencao" and not c["pago_em"]


def test_sem_procuracao_aguarda_e_continua(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.comportamento[CNPJ_A] = "sem_procuracao"
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    assert gestor.ler_doc("dasmei_clientes", "e1")["situacao"] == "aguardando_autenticacao"
    assert r["aguardando_autenticacao_n"] == 1 and len(banco.guias(CNPJ_B)) == 3   # o outro seguiu


def test_erro_temporario_reprocessa(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.comportamento[CNPJ_A] = 2           # duas falhas 500 e depois funciona
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    assert r["novas_tentativas"] == 2 and r["erros_n"] == 0 and len(banco.guias(CNPJ_A)) == 3


def test_erro_persistente_marca_cliente_e_segue(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.comportamento[CNPJ_A] = "fora"
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    assert gestor.ler_doc("dasmei_clientes", "e1")["situacao"] == "erro_consulta"
    assert r["erros_n"] == 1 and len(banco.guias(CNPJ_B)) == 3 and r["estado"] == "concluida"


def test_portal_fora_do_ar_interrompe_e_retoma(cfg, banco, gestor, fabrica, serpro_falsa):
    cfg.limite_falhas_seguidas = 2
    serpro_falsa.comportamento[CNPJ_A] = "fora"
    serpro_falsa.comportamento[CNPJ_B] = "fora"
    r = motor(cfg, banco, gestor, fabrica).executar("agendada")
    assert r["estado"] == "interrompida" and r["alertas"]
    assert banco.execucao_aberta()["id"] == r["id"]
    # portal volta: a próxima chamada retoma a MESMA execução e processa o que faltou
    serpro_falsa.comportamento.clear()
    r2 = motor(cfg, banco, gestor, fabrica).executar("retomada")
    assert r2["id"] == r["id"] and r2["estado"] == "concluida" and r2["retomada"]
    assert banco.execucao_aberta() is None
    estados = {f["empresa_id"]: f["estado"] for f in banco.fila_total(r["id"])}
    assert estados["e4"] == "processado"


def test_credencial_do_escritorio_aborta(cfg, banco, gestor):
    from dasmei.serpro import ErroCredencial

    def fab():
        raise ErroCredencial("Certificado digital do escritório vencido")
    r = motor(cfg, banco, gestor, fab).executar("agendada")
    assert r["estado"] == "abortada" and "vencido" in r["alertas"][0]["mensagem"]


def test_pdf_invalido_vai_para_revisao(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.comportamento[CNPJ_A] = "pdf_ruim"
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    assert all(g["status"] == "das_emitido" and not g["arquivo"] for g in banco.guias(CNPJ_A))
    assert comps(banco, CNPJ_A)["202610"]["status"] == "exige_intervencao"
    assert r["pdfs_baixados"] == 3   # só os do outro cliente
    assert not list(Path(cfg.pasta_documentos).glob(f"{CNPJ_A}/**/*.pdf"))


def test_recusa_da_receita_exige_intervencao(cfg, banco, gestor, fabrica, serpro_falsa):
    serpro_falsa.comportamento[CNPJ_A] = "negocio"
    motor(cfg, banco, gestor, fabrica).executar("manual")
    c = comps(banco, CNPJ_A)["202610"]
    assert c["status"] == "exige_intervencao" and "não permitido" in c["mensagem"]


def test_config_da_tela_desliga_vencidos_e_pausa(cfg, banco, gestor, fabrica, serpro_falsa):
    gestor.gravar("dasmei_robo", "config", {"emitir_vencidos": False, "excluidos": ["e2"]})
    r = motor(cfg, banco, gestor, fabrica).executar("manual")
    assert r["guias_emitidas"] == 1 and not banco.guias(CNPJ_B)
    gestor.gravar("dasmei_robo", "config", {"pausado": True})
    assert motor(cfg, banco, gestor, fabrica).executar("agendada") == {"estado": "pausado"}


def test_somente_um_cliente(cfg, banco, gestor, fabrica):
    r = motor(cfg, banco, gestor, fabrica).executar("manual", somente=["e2"])
    assert r["total_clientes"] == 1 and not banco.guias(CNPJ_A)


def test_nao_sobrescreve_arquivo_existente_diferente(cfg, banco, gestor, fabrica, serpro_falsa):
    from dasmei import arquivos
    from dasmei.competencia import Competencia
    r = motor(cfg, banco, gestor, fabrica).executar("manual", somente=["e1"])
    g = banco.guias(CNPJ_A, "202610")[0]
    original = Path(g["arquivo"]).read_bytes()
    p, novo = arquivos.gravar_sem_sobrescrever(Path(g["arquivo"]).parent, Path(g["arquivo"]).name, b"%PDF outro")
    assert novo and p.name.endswith("_v2.pdf") and Path(g["arquivo"]).read_bytes() == original
