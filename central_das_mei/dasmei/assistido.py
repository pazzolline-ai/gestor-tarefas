"""Sessão assistida no PGMEI (sem contrato SERPRO).

O robô abre o PGMEI oficial no Edge/Chrome do PC, cliente por cliente, já com o
CNPJ preenchido e uma barra de instruções na parte de baixo da página. A pessoa
resolve o captcha ("não sou um robô") e gera o DAS. O robô NÃO toca no captcha.
Assim que o PDF aparece (download ou visualização), o robô:
  - valida o arquivo e confere se o CNPJ do PDF é o do cliente;
  - lê período, vencimento, valor e número do documento;
  - salva em CENTRAL_DAS_MEI\\CNPJ\\ANO\\MÊS sem sobrescrever nada;
  - registra no banco local, atualiza o gestor e passa ao próximo cliente.
Pagamento NÃO é confirmado aqui: só com a consulta oficial (SERPRO) ou quando
alguém informa na tela que conferiu o comprovante.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import time
from pathlib import Path

from . import arquivos, pdf as pdfmod
from .banco import Banco, agora
from .cnpj import formatar
from .competencia import Competencia, janela, vencimento
from .gestor import COL_EXEC
from .motor import Motor
from .relatorio import Relatorio
from .status import Status, avancar_guia, resumo_cliente

log = logging.getLogger("dasmei")
PGMEI_URL = "https://www8.receita.fazenda.gov.br/SimplesNacional/Aplicacoes/ATSPO/pgmei.app/Identificacao"
SELETORES_CNPJ = ['input[name*="cnpj" i]', 'input[id*="cnpj" i]', 'input[placeholder*="cnpj" i]',
                  'input[aria-label*="cnpj" i]']

BARRA_JS = r"""
(() => {
  if (window.top !== window) return;
  const css = `#dasmei-barra{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;background:#0e1014;color:#fff;
   font:14px 'Segoe UI',system-ui,sans-serif;padding:10px 14px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;
   box-shadow:0 -4px 18px rgba(0,0,0,.35);line-height:1.4}
   #dasmei-barra .t{flex:1;min-width:260px}#dasmei-barra b{color:#ffd166}#dasmei-barra small{color:#b8c0cc;display:block}
   #dasmei-barra button{font:inherit;border:0;border-radius:8px;padding:7px 12px;cursor:pointer;background:#2b2f36;color:#fff}
   #dasmei-barra button.p{background:#2ecc71;color:#06210f;font-weight:600}
   #dasmei-barra .ok{color:#7ee2a8}#dasmei-barra .er{color:#ff8a80}`;
  const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  async function desenhar() {
    let e; try { e = JSON.parse(await window.dasmeiEstado()); } catch (x) { return; }
    if (!document.body) return;
    let el = document.getElementById('dasmei-barra');
    if (!el) {
      const st = document.createElement('style'); st.textContent = css; (document.head || document.body).appendChild(st);
      el = document.createElement('div'); el.id = 'dasmei-barra'; document.body.appendChild(el);
      document.body.style.paddingBottom = '90px';
      el.addEventListener('click', ev => { const b = ev.target.closest('button[data-a]'); if (b) window.dasmeiAcao(b.dataset.a); });
    }
    const bt = (a, t, p) => (e.botoes || []).includes(a) ? `<button data-a="${a}" class="${p ? 'p' : ''}">${t}</button>` : '';
    el.innerHTML = `<div class="t">🤖 <b>Central de DAS MEI</b> · ${esc(e.titulo)} · <b>${esc(e.nome)}</b> · CNPJ ${esc(e.cnpj)}
      <small>${esc(e.instrucao)}</small>${e.msg ? `<small class="${esc(e.msgTipo)}">${esc(e.msg)}</small>` : ''}</div>
      ${bt('proximo', 'Próximo cliente ▶', true)}${bt('ficar', 'Emitir outro mês deste cliente')}${bt('pular', 'Pular cliente')}${bt('parar', 'Encerrar sessão')}`;
  }
  window.__dasmeiAtualiza = desenhar;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', desenhar); else desenhar();
})();
"""


def abrir_navegador(pw):
    """Usa o Edge (já vem no Windows); se não houver, o Chrome; por último o Chromium do Playwright."""
    for canal in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(channel=canal, headless=False)
        except Exception:  # noqa: BLE001
            continue
    return pw.chromium.launch(headless=False)


class SessaoAssistida:
    def __init__(self, cfg, banco: Banco, gestor, *, url=PGMEI_URL, abrir=abrir_navegador, preparar_contexto=None,
                 hoje=None, timeout_cliente=900.0, espera_proximo=6.0, intervalo=0.4):
        self.cfg, self.banco, self.gestor = cfg, banco, gestor
        self.url, self._abrir, self._preparar = url, abrir, preparar_contexto
        self._hoje = hoje or dt.date.today
        self.timeout_cliente, self.espera_proximo, self.intervalo = timeout_cliente, espera_proximo, intervalo
        self._ui = {}
        self._acao = None
        self._capturas: list[bytes] = []
        self._vistos: set[str] = set()

    # ------------------------------------------------------------ fila
    def montar_fila(self, somente=None, todos=False):
        hoje = self._hoje()
        rotina = self.cfg.rotina.mesclar(self.gestor.config_remota())
        try:
            manuais = self.gestor.pagamentos_manuais()
        except Exception:  # noqa: BLE001
            manuais = {}
        aptos, probl = self.gestor.clientes_mei(rotina.excluidos, somente or rotina.somente)
        atual = janela(hoje, 1)[0]
        fila = []
        for it in aptos:
            alvo = []
            reg = self.banco.competencia(it["cnpj"], atual.pa)
            pago = f"{it['empresa_id']}_{atual.iso}" in manuais or (reg and reg["status"] == Status.PAGO_CONFIRMADO.value)
            ativa = next((g for g in reversed(self.banco.guias(it["cnpj"], atual.pa)) if not g["substituida"]), None)
            if rotina.emitir_competencia_atual and not pago and not (ativa and self._guia_valida(ativa, hoje)):
                alvo.append(atual)
            if alvo or somente or todos:
                fila.append({**it, "alvo": alvo})
        return fila, probl, rotina

    @staticmethod
    def _guia_valida(g, hoje):
        limite = g.get("data_limite") or g.get("vencimento")
        arq = g.get("arquivo")
        return bool(limite and limite >= hoje.isoformat() and arq and Path(arq).exists()
                    and arquivos.sha256_arquivo(Path(arq)) == g.get("sha256"))

    # ------------------------------------------------------------ registro de um PDF
    def registrar_pdf(self, item, dados: bytes) -> tuple[bool, str]:
        c = item["cnpj"]
        try:
            lido = pdfmod.ler(dados)
        except pdfmod.PdfInvalido as e:
            return False, f"O arquivo recebido não é um PDF válido ({e}). Nada foi salvo."
        if lido.cnpj and lido.cnpj != c:
            return False, f"Este PDF é do CNPJ {formatar(lido.cnpj)}, não deste cliente. Nada foi salvo."
        avisos = list(lido.avisos)
        if lido.periodos:
            comps = sorted({Competencia.de_texto(p) for p in lido.periodos})
        elif item.get("alvo"):
            comps = [item["alvo"][-1]]
            avisos.append(f"período não lido no PDF; registrado como {comps[0].texto}")
        else:
            return False, "Não consegui ler o período de apuração no PDF. Salve-o manualmente na pasta do cliente."
        if lido.texto_legivel and not lido.cnpj:
            avisos.append("CNPJ não encontrado no texto do PDF")
        h = arquivos.sha256(dados)
        numero = lido.numero_documento or f"SN{h[:15]}"
        existente = self.banco.guia_por_documento(numero)
        if existente and existente["sha256"] == h and existente["arquivo"] and Path(existente["arquivo"]).exists():
            return True, f"Esta guia ({comps[-1].texto}) já estava salva."
        comp = comps[-1]
        pasta = arquivos.pasta_competencia(self.cfg.pasta_documentos, c, comp)
        caminho, novo = arquivos.gravar_sem_sobrescrever(pasta, arquivos.nome_guia(c, comp, lido.vencimento, numero), dados)
        st = Status.DAS_EMITIDO
        for prox in (Status.DAS_DISPONIVEL, Status.GUIA_BAIXADA):
            st = avancar_guia(st, prox)
        extr = json.dumps(lido.dict(), ensure_ascii=False)
        if existente:
            gid = existente["id"]
            self.banco.atualizar_guia(gid, status=st.value, arquivo=str(caminho), sha256=h, tamanho=len(dados), extracao=extr)
        else:
            gid = self.banco.inserir_guia(cnpj=c, pa=comp.pa, numero_documento=numero, status=st.value,
                                          vencimento=lido.vencimento, data_limite=lido.vencimento, total=lido.valor_total,
                                          arquivo=str(caminho), sha256=h, tamanho=len(dados), extracao=extr,
                                          emitida_em=agora(), operacao_id=self.eid)
            self.rel.guias_emitidas += 1
        self.banco.substituir_guias(c, comp.pa, gid)
        if novo:
            self.rel.pdfs_baixados += 1
        hoje = self._hoje()
        conj = f" — guia conjunta de {len(comps)} meses" if len(comps) > 1 else ""
        for k in comps:
            reg = self.banco.competencia(c, k.pa)
            if reg and reg["status"] == Status.PAGO_CONFIRMADO.value:
                continue
            stc = Status.VENCIDO if hoje > vencimento(k) else Status.PENDENTE
            self.banco.salvar_competencia(c, k.pa, stc, vencimento(k).isoformat(),
                                          "Guia baixada na sessão assistida; pagamento não verificado" + conj)
            try:
                self.gestor.marcar_das_painel(item["empresa_id"], k.iso, {
                    "documento": numero, "vencimento": lido.vencimento, "total": lido.valor_total,
                    "arquivo": str(caminho), "em": agora(), "origem": "sessão assistida"})
            except Exception as e:  # noqa: BLE001
                log.warning("Painel DAS do Início não atualizado: %s", e)
        self.banco.auditar("guia_arquivada_assistida", c, {"pas": [k.pa for k in comps], "arquivo": str(caminho),
                                                            "sha256": h, "novo": novo}, self.eid)
        if avisos:
            self.rel.revisao(item, comp, "Conferir guia: " + "; ".join(avisos))
        self._publicar(item)
        txt = f"✔ Guia de {', '.join(k.texto for k in comps)} salva ({caminho.name})"
        return True, txt + (f". Conferir: {'; '.join(avisos)}" if avisos else "")

    def _publicar(self, item):
        hoje = self._hoje()
        comps = janela(hoje, self._rotina.meses_retroativos)
        sts = [x["status"] for x in self.banco.competencias(item["cnpj"]) if x["pa"] in {k.pa for k in comps}]
        conhecidos = [s for s in sts if s != Status.NAO_CONSULTADO.value] or sts
        sit = resumo_cliente(conhecidos)
        self.banco.salvar_cliente(item["empresa_id"], item["cnpj"], item.get("nome"), sit.value, None, consultado=True)
        m = Motor(self.cfg, self.banco, self.gestor, lambda: None, hoje=self._hoje)
        m.rel, m.eid, m._rotina = self.rel, self.eid, self._rotina
        m._publicar_cliente(item, sit, None, comps)

    # ------------------------------------------------------------ navegador
    def _estado(self, *_):
        return json.dumps(self._ui, ensure_ascii=False)

    def _set_acao(self, _src, acao):
        self._acao = acao

    def _ao_responder(self, resp):
        try:
            h = resp.headers
            if "attachment" in (h.get("content-disposition") or "").lower():
                return  # é download: chega pelo evento de download
            if "application/pdf" in (h.get("content-type") or "").lower():
                self._guardar(resp.body())
        except Exception:  # noqa: BLE001 - downloads não têm corpo aqui; vêm pelo evento de download
            pass

    def _ao_baixar(self, dl):
        try:
            p = dl.path()
            if p:
                self._guardar(Path(p).read_bytes())
        except Exception as e:  # noqa: BLE001
            log.warning("Download não capturado: %s", e)

    def _guardar(self, dados):
        if not dados:
            return
        h = arquivos.sha256(dados)
        if h not in self._vistos:
            self._vistos.add(h)
            self._capturas.append(dados)

    def _ui_atualizar(self, page, **kw):
        self._ui.update(kw)
        try:
            page.evaluate("window.__dasmeiAtualiza && window.__dasmeiAtualiza()")
        except Exception:  # noqa: BLE001
            pass

    def _preencher_cnpj(self, page, c) -> bool:
        for sel in SELETORES_CNPJ:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.fill(c)
                    if "".join(ch for ch in loc.input_value() if ch.isdigit()) != c:
                        loc.fill("")
                        loc.press_sequentially(c, delay=30)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    # ------------------------------------------------------------ sessão
    def executar(self, somente=None, todos=False) -> dict:
        from playwright.sync_api import sync_playwright
        fila, probl, self._rotina = self.montar_fila(somente, todos)
        self.banco.fechar_assistidas_abertas()
        self.eid = self.banco.nova_execucao("assistida", fila)
        self.rel = Relatorio(self.eid, "assistida", len(fila))
        for p in probl:
            self.rel.intervencao(p, None, p["problema"])
        estado = "concluida"
        if not fila:
            log.info("Nenhum cliente precisa de guia agora.")
        else:
            with sync_playwright() as pw:
                nav = self._abrir(pw)
                ctx = nav.new_context(accept_downloads=True, no_viewport=not self._preparar)
                if self._preparar:
                    self._preparar(ctx)
                ctx.expose_binding("dasmeiEstado", self._estado)
                ctx.expose_binding("dasmeiAcao", self._set_acao)
                ctx.add_init_script(BARRA_JS)
                ctx.on("response", self._ao_responder)
                ctx.on("page", lambda pg: pg.on("download", self._ao_baixar))
                page = ctx.new_page()
                try:
                    estado = self._percorrer(page, fila)
                finally:
                    try:
                        ctx.close()
                        nav.close()
                    except Exception:  # noqa: BLE001
                        pass
        resumo = self.rel.resumo(self.banco.fila_total(self.eid), estado)
        self.banco.finalizar_execucao(self.eid, estado, resumo)
        try:
            self.gestor.gravar(COL_EXEC, self.eid, resumo)
        except Exception as e:  # noqa: BLE001
            log.error("Relatório da sessão não enviado ao gestor: %s", e)
        try:
            self.rel.salvar_arquivos(self.cfg.pasta_relatorios, resumo)
        except OSError as e:
            log.error("Relatório não salvo em arquivo: %s", e)
        return resumo

    def _percorrer(self, page, fila) -> str:
        total = len(fila)
        falhas_abrir = 0
        for i, item in enumerate(fila):
            if page.is_closed():
                return "interrompida"
            self._acao, self._capturas = None, []
            alvo = ", ".join(k.texto for k in item["alvo"]) or "o mês que precisar"
            self._ui = {"titulo": f"cliente {i + 1} de {total}", "nome": item.get("nome"), "cnpj": formatar(item["cnpj"]),
                        "instrucao": f"1) Resolva o “não sou um robô” e clique em Continuar. 2) Emitir Guia de Pagamento (DAS) "
                                     f"→ ano → marque {alvo} → Apurar/Gerar DAS → Imprimir/Visualizar PDF. "
                                     "O robô salva o PDF sozinho.",
                        "msg": "", "msgTipo": "", "botoes": ["pular", "parar"]}
            try:
                page.goto(self.url, wait_until="domcontentloaded", timeout=60_000)
                falhas_abrir = 0
            except Exception as e:  # noqa: BLE001
                falhas_abrir += 1
                self.rel.erro(item, f"PGMEI não abriu: {e.__class__.__name__}")
                self.banco.fila_marcar(self.eid, item["empresa_id"], "erro", "PGMEI não abriu")
                if falhas_abrir >= 3:
                    self.rel.alerta("geral", None, "O PGMEI não abriu 3 vezes seguidas: portal fora do ar ou sem internet.")
                    return "interrompida"
                continue
            if not self._preencher_cnpj(page, item["cnpj"]):
                self._ui_atualizar(page, msg=f"Digite o CNPJ {item['cnpj']} no campo do PGMEI.", msgTipo="er")
            else:
                self._ui_atualizar(page)
            resultado = self._esperar_cliente(page, item)
            if resultado == "parar":
                self.banco.fila_marcar(self.eid, item["empresa_id"], "pendente")
                return "interrompida"
        return "concluida"

    def _esperar_cliente(self, page, item) -> str:
        inicio = time.monotonic()
        salvos, ultimo, ficar = 0, None, False
        while True:
            try:
                page.wait_for_timeout(self.intervalo * 1000)
            except Exception:  # noqa: BLE001 - janela fechada pela pessoa
                self.banco.fila_marcar(self.eid, item["empresa_id"], "processado" if salvos else "pendente")
                return "parar"
            while self._capturas:
                ok, msg = self.registrar_pdf(item, self._capturas.pop(0))
                if ok:
                    salvos += 1
                    ultimo = time.monotonic()
                    self._ui_atualizar(page, msg=msg + ("" if ficar else f" Indo para o próximo em {self.espera_proximo:.0f}s…"),
                                       msgTipo="ok", botoes=["proximo", "ficar", "parar"])
                else:
                    self._ui_atualizar(page, msg=msg, msgTipo="er")
            a, self._acao = self._acao, None
            if a == "parar":
                self.banco.fila_marcar(self.eid, item["empresa_id"], "processado" if salvos else "pendente")
                return "parar"
            if a == "ficar":
                ficar = True
                self._ui_atualizar(page, msg="Pode gerar outro mês. Quando terminar, clique em Próximo cliente.", msgTipo="ok",
                                   botoes=["proximo", "parar"])
            if a in ("pular", "proximo") or (ultimo and not ficar and time.monotonic() - ultimo > self.espera_proximo):
                break
            if time.monotonic() - inicio > self.timeout_cliente:
                self.rel.revisao(item, None, "Tempo esgotado na sessão assistida; cliente ficou sem guia")
                break
        if salvos:
            self.rel.processados += 1
            self.banco.fila_marcar(self.eid, item["empresa_id"], "processado")
        else:
            self.banco.fila_marcar(self.eid, item["empresa_id"], "pulado")
            if a == "pular":
                self.rel.revisao(item, None, "Pulado na sessão assistida")
        return "ok"
