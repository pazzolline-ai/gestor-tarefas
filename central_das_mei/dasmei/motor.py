"""Motor de automação: fila de clientes MEI, um por vez.

Para cada cliente:
 1. consulta pagamentos oficiais (PAGTOWEB) da janela de competências;
 2. classifica cada competência: pago confirmado / pendente / vencido;
 3. emite o DAS (PGMEI) quando autorizado e ainda não houver guia válida;
 4. valida e arquiva o PDF, registra tudo e atualiza o gestor;
 5. passa ao próximo — o erro de um cliente nunca para o lote.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import re
import socket
import time
from pathlib import Path

from . import __version__, arquivos, pdf as pdfmod
from . import cnpj as cnpjmod
from .banco import Banco, agora
from .competencia import Competencia, janela, vencimento
from .config import Config, Rotina
from .gestor import COL_CLIENTES, COL_EXEC, COL_ROBO, GestorBase
from .relatorio import Relatorio
from .serpro import ErroAutorizacao, ErroCredencial, ErroNegocio, ErroSerpro, ErroTemporario
from .status import ROTULO, Status, avancar_guia, resumo_cliente

log = logging.getLogger("dasmei")
_DAS = re.compile(r"(?i)\bDAS\b|SIMPLES|SIMEI|\bMEI\b")


class PortalIndisponivel(Exception):
    pass


class LoteAbortado(Exception):
    pass


def achar_pagamento(pagamentos, comp: Competencia, numeros_guias: set[str]):
    """Devolve (evidencia|None, suspeita|None). Só 'evidencia' confirma pagamento."""
    suspeita = None
    for p in pagamentos or []:
        if p.numero_documento and p.numero_documento in numeros_guias:
            return ({"data": p.data_arrecadacao, "valor": p.valor_total, "documento": p.numero_documento,
                     "evidencia": "PAGTOWEB: pagamento do documento emitido pelo robô"}, None)
    for p in pagamentos or []:
        if comp.pa == p.pa or comp.pa in (p.pas_desmembrados or []):
            if _DAS.search(f"{p.tipo} {p.receita}") and p.data_arrecadacao:
                return ({"data": p.data_arrecadacao, "valor": p.valor_total, "documento": p.numero_documento,
                         "evidencia": f"PAGTOWEB: documento de arrecadação ({p.tipo or 'DAS'}) pago para o período"}, None)
            suspeita = p
    return None, suspeita


class Motor:
    def __init__(self, cfg: Config, banco: Banco, gestor: GestorBase, serpro_fabrica, *,
                 hoje=None, dormir=time.sleep, aleatorio=random.uniform):
        self.cfg, self.banco, self.gestor = cfg, banco, gestor
        self._fabrica = serpro_fabrica
        self._hoje = hoje or dt.date.today
        self._dormir = dormir
        self._aleat = aleatorio
        self.serpro = None
        self.rel: Relatorio | None = None
        self.eid = None

    # ------------------------------------------------------------ utilidades
    def _retry(self, fn, descricao):
        n = max(1, self.cfg.max_tentativas)
        for t in range(1, n + 1):
            try:
                return fn()
            except ErroTemporario as e:
                if t == n:
                    raise
                espera = min(60, 2 ** t) * self._aleat(0.8, 1.2)
                log.warning("%s: falha temporária (%s). Nova tentativa em %.0fs", descricao, e, espera)
                self.rel.tentativas_extras += 1
                self._dormir(espera)

    def _publicar(self, col, did, data):
        try:
            self.gestor.gravar(col, did, data)
        except Exception as e:  # noqa: BLE001 - o lote continua mesmo sem o gestor
            log.error("Não consegui atualizar o gestor (%s/%s): %s", col, did, e)
            self.rel.avisos_gestor += 1

    def status_robo(self, **extra):
        d = {"online": agora(), "versao": __version__, "maquina": socket.gethostname(),
             "ambiente": self.cfg.serpro_ambiente}
        d.update(extra)
        try:
            self.gestor.mesclar(COL_ROBO, "status", d)
        except Exception as e:  # noqa: BLE001
            log.warning("Heartbeat não enviado: %s", e)

    def rotina(self) -> Rotina:
        try:
            return self.cfg.rotina.mesclar(self.gestor.config_remota())
        except Exception as e:  # noqa: BLE001
            log.warning("Configuração da tela indisponível, usando a local: %s", e)
            return self.cfg.rotina

    # ------------------------------------------------------------ lote
    def executar(self, origem="agendada", somente=None) -> dict:
        hoje = self._hoje()
        rotina = self.rotina()
        if rotina.pausado and origem == "agendada":
            log.info("Robô pausado pela tela do gestor; rotina agendada não executada.")
            return {"estado": "pausado"}
        aberta = self.banco.execucao_aberta()
        if aberta:
            self.eid = aberta["id"]
            log.info("Retomando execução interrompida %s", self.eid)
            self.banco.auditar("execucao_retomada", execucao_id=self.eid)
        else:
            aptos, probl = self.gestor.clientes_mei(rotina.excluidos, somente or rotina.somente)
            self.eid = self.banco.nova_execucao(origem, aptos + probl)
        fila = self.banco.fila_total(self.eid)
        self.rel = Relatorio(self.eid, origem, len(fila), retomada=bool(aberta))
        self.status_robo(executando=True, execucaoId=self.eid, progresso={"feitos": 0, "total": len(fila)})
        estado = "concluida"
        try:
            self.serpro = self._fabrica()
            falhas_seguidas = 0
            pend = self.banco.fila_pendente(self.eid)
            for i, item in enumerate(pend):
                try:
                    self.processar_cliente(item, rotina, hoje)
                    self.banco.fila_marcar(self.eid, item["empresa_id"], "processado")
                    falhas_seguidas = 0
                except ErroTemporario as e:
                    falhas_seguidas += 1
                    self._erro_cliente(item, Status.ERRO_CONSULTA, str(e))
                    self.banco.fila_marcar(self.eid, item["empresa_id"], "erro", str(e))
                    if falhas_seguidas >= self.cfg.limite_falhas_seguidas:
                        raise PortalIndisponivel(
                            f"{falhas_seguidas} clientes seguidos com falha temporária: portal/serviço indisponível")
                except ErroCredencial:
                    raise
                except Exception as e:  # noqa: BLE001 - erro inesperado de um cliente não para o lote
                    log.exception("Erro inesperado no cliente %s", item["cnpj"])
                    self._erro_cliente(item, Status.EXIGE_INTERVENCAO, f"Erro inesperado: {e}")
                    self.banco.fila_marcar(self.eid, item["empresa_id"], "erro", str(e))
                self.status_robo(executando=True, execucaoId=self.eid,
                                 progresso={"feitos": i + 1 + (len(fila) - len(pend)), "total": len(fila)})
                if i < len(pend) - 1:
                    self._dormir(self._aleat(*self.cfg.pausa_entre_clientes))
        except ErroCredencial as e:
            estado = "abortada"
            self.rel.alerta("geral", None, f"Lote parado: {e}. Confira chaves SERPRO, certificado e contrato.")
            for it in self.banco.fila_pendente(self.eid):
                self.banco.fila_marcar(self.eid, it["empresa_id"], "nao_processado", str(e))
        except PortalIndisponivel as e:
            estado = "interrompida"
            self.rel.alerta("geral", None, f"{e}. Os clientes restantes serão retomados na próxima tentativa.")
        finally:
            if self.serpro is not None and hasattr(self.serpro, "fechar"):
                self.serpro.fechar()
        if estado == "interrompida":
            # deixa a execução aberta para ser retomada
            resumo = self.rel.resumo(self.banco.fila_total(self.eid), estado)
            self.banco._x("UPDATE execucoes SET resumo=? WHERE id=?", (__import__("json").dumps(resumo, ensure_ascii=False), self.eid))
        else:
            resumo = self.rel.resumo(self.banco.fila_total(self.eid), estado)
            self.banco.finalizar_execucao(self.eid, estado, resumo)
        self._publicar(COL_EXEC, self.eid, resumo)
        try:
            self.rel.salvar_arquivos(self.cfg.pasta_relatorios, resumo)
        except OSError as e:
            log.error("Relatório não salvo em arquivo: %s", e)
        self.status_robo(executando=False, execucaoId=None, progresso=None,
                         ultimaExecucao={"id": self.eid, "fim": agora(), "estado": estado,
                                         "resumo": {k: resumo[k] for k in ("total_clientes", "processados", "guias_emitidas", "pdfs_baixados", "erros_n", "aguardando_autenticacao_n")}})
        log.info("Execução %s %s: %s", self.eid, estado, {k: resumo[k] for k in ("processados", "guias_emitidas", "pdfs_baixados", "erros_n")})
        return resumo

    def _erro_cliente(self, item, status: Status, msg: str):
        self.rel.erro(item, msg)
        self.banco.salvar_cliente(item["empresa_id"], item["cnpj"], item.get("nome"), status.value, msg)
        self._publicar_cliente(item, status, msg)

    # ------------------------------------------------------------ cliente
    def processar_cliente(self, item: dict, rotina: Rotina, hoje: dt.date):
        eid, c, nome = item["empresa_id"], item["cnpj"], item.get("nome")
        log.info("Processando %s (%s)", nome, cnpjmod.formatar(c))
        if not cnpjmod.valido(c) and self.cfg.serpro_ambiente == "producao":
            msg = "CNPJ ausente ou inválido no cadastro da empresa"
            self.rel.intervencao(item, None, msg)
            self.banco.salvar_cliente(eid, c, nome, Status.EXIGE_INTERVENCAO.value, msg)
            self._publicar_cliente(item, Status.EXIGE_INTERVENCAO, msg)
            return
        comps = janela(hoje, rotina.meses_retroativos)
        atual = comps[-1]
        pagamentos, msg_pag = None, None
        if rotina.consultar_pagamentos:
            oid = self.banco.iniciar_operacao(self.eid, f"pag:{c}:{hoje}", "consultar_pagamentos", c)
            try:
                pagamentos = self._retry(lambda: self.serpro.consultar_pagamentos(c, comps[0].primeiro_dia(), hoje),
                                         f"pagamentos {c}")
                self.banco.concluir_operacao(oid)
                self.rel.consultas_ok += 1
            except ErroAutorizacao as e:
                self.banco.concluir_operacao(oid, "falhou", str(e))
                self._aguardando(item, str(e))
                return
            except ErroNegocio as e:
                self.banco.concluir_operacao(oid, "falhou", str(e))
                msg_pag = f"Pagamentos não verificados: {e}"
                self.rel.revisao(item, None, msg_pag)
            except ErroTemporario as e:
                self.banco.concluir_operacao(oid, "falhou", str(e))
                raise
        else:
            msg_pag = "Consulta de pagamentos desligada: pagamento não verificado"

        for comp in comps:
            try:
                self._processar_competencia(item, comp, comp == atual, rotina, hoje, pagamentos, msg_pag)
            except ErroAutorizacao as e:
                self._aguardando(item, str(e))
                return
        self.rel.processados += 1
        sts = [x["status"] for x in self.banco.competencias(c) if x["pa"] in {k.pa for k in comps}]
        situacao = resumo_cliente(sts)
        msgs = [x["mensagem"] for x in self.banco.competencias(c) if x["status"] == Status.EXIGE_INTERVENCAO.value and x["mensagem"]]
        self.banco.salvar_cliente(eid, c, nome, situacao.value, "; ".join(msgs)[:500] or None, consultado=True)
        self._publicar_cliente(item, situacao, None, comps)

    def _aguardando(self, item, msg):
        msg = ("Sem procuração eletrônica (e-CAC) do cliente para o escritório, ou procuração sem os serviços "
               f"PGMEI/Pagamentos. Detalhe: {msg}")
        self.rel.aguardando(item, msg)
        self.banco.salvar_cliente(item["empresa_id"], item["cnpj"], item.get("nome"),
                                  Status.AGUARDANDO_AUTENTICACAO.value, msg, consultado=True)
        self._publicar_cliente(item, Status.AGUARDANDO_AUTENTICACAO, msg)

    def _guia_valida(self, g, hoje) -> bool:
        limite = g.get("data_limite") or g.get("vencimento")
        if not limite or limite < hoje.isoformat():
            return False
        arq = g.get("arquivo")
        return bool(arq and Path(arq).exists() and arquivos.sha256_arquivo(Path(arq)) == g.get("sha256"))

    def _processar_competencia(self, item, comp: Competencia, eh_atual, rotina: Rotina, hoje, pagamentos, msg_pag):
        c = item["cnpj"]
        reg = self.banco.competencia(c, comp.pa)
        if reg and reg["status"] == Status.PAGO_CONFIRMADO.value:
            return
        guias = self.banco.guias(c, comp.pa)
        numeros = {g["numero_documento"] for g in guias}
        venc_legal = vencimento(comp)
        if pagamentos is not None:
            evid, suspeita = achar_pagamento(pagamentos, comp, numeros)
            if evid:
                self.banco.salvar_competencia(c, comp.pa, Status.PAGO_CONFIRMADO, venc_legal.isoformat(), None, evid)
                self.banco.auditar("pagamento_confirmado", c, {"pa": comp.pa, **evid}, self.eid)
                self.rel.pagos += 1
                return
            if suspeita:
                m = (f"Há pagamento no período {comp.texto} sem identificação clara de DAS "
                     f"(doc. {suspeita.numero_documento}). Conferir antes de emitir.")
                self.banco.salvar_competencia(c, comp.pa, Status.EXIGE_INTERVENCAO, venc_legal.isoformat(), m)
                self.rel.revisao(item, comp, m)
                return
        st = Status.VENCIDO if hoje > venc_legal else Status.PENDENTE
        mensagem = msg_pag
        quer_emitir = (eh_atual and rotina.emitir_competencia_atual) or (st == Status.VENCIDO and rotina.emitir_vencidos)
        ativa = next((g for g in reversed(guias) if not g["substituida"]), None)
        if quer_emitir and not (ativa and self._guia_valida(ativa, hoje)):
            chave = f"emitir:{c}:{comp.pa}:{hoje}"
            if self.banco.operacao_concluida(chave):
                # já emitida hoje e o arquivo sumiu/mudou: não emite de novo, pede revisão
                mensagem = "Guia já emitida hoje, mas o arquivo não confere — revisar a pasta do cliente"
                self.banco.salvar_competencia(c, comp.pa, Status.EXIGE_INTERVENCAO, venc_legal.isoformat(), mensagem)
                self.rel.revisao(item, comp, mensagem)
                return
            else:
                try:
                    problema = self._emitir(item, comp, chave)
                except ErroNegocio as e:
                    self.banco.salvar_competencia(c, comp.pa, Status.EXIGE_INTERVENCAO, venc_legal.isoformat(), str(e))
                    self.rel.intervencao(item, comp, str(e))
                    return
                if problema:
                    self.banco.salvar_competencia(c, comp.pa, Status.EXIGE_INTERVENCAO, venc_legal.isoformat(), problema)
                    return
        self.banco.salvar_competencia(c, comp.pa, st, venc_legal.isoformat(), mensagem)
        if st == Status.VENCIDO:
            self.rel.vencidos += 1
        else:
            self.rel.pendentes += 1

    def _emitir(self, item, comp: Competencia, chave) -> str | None:
        """Emite, valida e arquiva. Devolve texto do problema (revisão) ou None."""
        c = item["cnpj"]
        oid = self.banco.iniciar_operacao(self.eid, chave, "emitir_das", c, comp.pa)
        try:
            gerados = self._retry(lambda: self.serpro.gerar_das_pdf(c, comp.pa), f"emitir {c} {comp.pa}")
        except ErroSerpro as e:
            self.banco.concluir_operacao(oid, "falhou", str(e))
            raise
        if not gerados:
            self.banco.concluir_operacao(oid, "falhou", "sem guia na resposta")
            raise ErroNegocio("A Receita não devolveu guia para este período")
        das = gerados[0]
        det = next((d for d in das.detalhes if d.periodo_apuracao == comp.pa), das.detalhes[0] if das.detalhes else None)
        if det is None or not det.numero_documento:
            self.banco.concluir_operacao(oid, "falhou", "resposta sem detalhamento")
            raise ErroNegocio("Resposta da Receita sem número do documento/vencimento")
        existente = self.banco.guia_por_documento(det.numero_documento)
        if existente:
            gid = existente["id"]
            st_guia = existente["status"]
        else:
            st_guia = avancar_guia(None, Status.DAS_EMITIDO).value
            gid = self.banco.inserir_guia(cnpj=c, pa=comp.pa, numero_documento=det.numero_documento, status=st_guia,
                                          vencimento=det.data_vencimento, data_limite=det.data_limite,
                                          principal=det.principal, multa=det.multa, juros=det.juros, total=det.total,
                                          emitida_em=agora(), operacao_id=oid)
            self.rel.guias_emitidas += 1
            self.banco.auditar("das_emitido", c, {"pa": comp.pa, "documento": det.numero_documento, "total": det.total},
                               self.eid, oid)
        # validação do PDF
        try:
            lido = pdfmod.ler(das.pdf)
        except pdfmod.PdfInvalido as e:
            m = f"PDF inválido recebido da Receita ({e}); guia não arquivada"
            self.banco.concluir_operacao(oid, "falhou", m)
            self.banco.auditar("pdf_invalido", c, {"pa": comp.pa, "erro": str(e)}, self.eid, oid)
            self.rel.revisao(item, comp, m)
            return m
        st_guia = avancar_guia(st_guia, Status.DAS_DISPONIVEL).value if st_guia != Status.GUIA_BAIXADA.value else st_guia
        divergencias = pdfmod.conferir(lido, c, comp.iso, det.data_vencimento, det.total, det.numero_documento)
        divergencias += lido.avisos
        if das.cnpj and das.cnpj != c:
            divergencias.append(f"API devolveu CNPJ {das.cnpj} diferente do pedido")
        # arquivo
        pasta = arquivos.pasta_competencia(self.cfg.pasta_documentos, c, comp)
        caminho, novo = arquivos.gravar_sem_sobrescrever(
            pasta, arquivos.nome_guia(c, comp, det.data_vencimento, det.numero_documento), das.pdf)
        h = arquivos.sha256(das.pdf)
        if arquivos.sha256_arquivo(caminho) != h:
            m = "Arquivo gravado não confere com o recebido (hash diferente)"
            self.banco.concluir_operacao(oid, "falhou", m)
            self.rel.revisao(item, comp, m)
            return m
        st_guia = avancar_guia(st_guia, Status.GUIA_BAIXADA).value
        self.banco.atualizar_guia(gid, status=st_guia, arquivo=str(caminho), sha256=h, tamanho=len(das.pdf),
                                  extracao=__import__("json").dumps(lido.dict(), ensure_ascii=False))
        self.banco.substituir_guias(c, comp.pa, gid)
        self.banco.concluir_operacao(oid)
        if novo:
            self.rel.pdfs_baixados += 1
        self.banco.auditar("guia_arquivada", c, {"pa": comp.pa, "arquivo": str(caminho), "sha256": h, "novo": novo},
                           self.eid, oid)
        try:
            self.gestor.marcar_das_painel(item["empresa_id"], comp.iso, {
                "documento": det.numero_documento, "vencimento": det.data_vencimento, "total": det.total,
                "arquivo": str(caminho), "em": agora()})
        except Exception as e:  # noqa: BLE001
            log.warning("Painel DAS do Início não atualizado: %s", e)
        if divergencias:
            m = "Conferir guia: " + "; ".join(divergencias)
            self.rel.revisao(item, comp, m)
            # aviso de PDF sem texto não bloqueia; divergência real sim
            if any(not d.startswith("PDF sem texto") for d in divergencias):
                return m
        return None

    # ------------------------------------------------------------ publicação
    def _publicar_cliente(self, item, situacao: Status, mensagem, comps=None):
        c = item["cnpj"]
        lst = []
        regs = {r["pa"]: r for r in self.banco.competencias(c)}
        pas = [k.pa for k in comps] if comps else sorted(regs)
        for pa in pas:
            r = regs.get(pa)
            if not r:
                continue
            comp = Competencia.de_texto(pa)
            g = next((x for x in reversed(self.banco.guias(c, pa)) if not x["substituida"]), None)
            lst.append({"comp": comp.iso, "status": r["status"], "statusTxt": ROTULO[Status(r["status"])],
                        "venc": r["vencimento"], "mensagem": r["mensagem"],
                        "pago": {"data": r["pago_em"], "valor": r["pago_valor"], "documento": r["pago_documento"],
                                 "evidencia": r["pago_evidencia"]} if r["pago_em"] else None,
                        "guia": {"documento": g["numero_documento"], "status": g["status"],
                                 "statusTxt": ROTULO[Status(g["status"])], "venc": g["vencimento"],
                                 "validade": g["data_limite"], "total": g["total"], "arquivo": g["arquivo"]} if g else None})
        todas = self.banco.guias(c)
        cli = self.banco.cliente(item["empresa_id"]) or {}
        doc = {"empresaId": item["empresa_id"], "cnpj": c, "nome": item.get("nome"),
               "situacao": situacao.value, "situacaoTxt": ROTULO[situacao], "mensagem": mensagem or cli.get("mensagem"),
               "ultimaConsulta": cli.get("ultima_consulta"), "atualizadoEm": agora(),
               "guiasEmitidas": len(todas), "guiasBaixadas": sum(1 for g in todas if g["status"] == Status.GUIA_BAIXADA.value),
               "pendentes": [x["comp"] for x in lst if x["status"] == Status.PENDENTE.value],
               "vencidos": [x["comp"] for x in lst if x["status"] == Status.VENCIDO.value],
               "competencias": lst, "execucaoId": self.eid}
        self._publicar(COL_CLIENTES, item["empresa_id"], doc)
