"""Relatório de cada rotina (salvo no banco local, no gestor e em arquivo)."""
from __future__ import annotations

import html
import json
from pathlib import Path

from .banco import agora
from .cnpj import formatar


class Relatorio:
    def __init__(self, eid, origem, total, retomada=False):
        self.eid, self.origem, self.total, self.retomada = eid, origem, total, retomada
        self.inicio = agora()
        self.processados = self.consultas_ok = self.guias_emitidas = self.pdfs_baixados = 0
        self.pendentes = self.vencidos = self.pagos = self.tentativas_extras = self.avisos_gestor = 0
        self.aguardando_sessao = 0
        self.erros, self.aguardando_l, self.revisao_l, self.intervencao_l, self.alertas = [], [], [], [], []

    @staticmethod
    def _it(item, comp, msg):
        return {"empresaId": item.get("empresa_id") if item else None, "nome": item.get("nome") if item else None,
                "cnpj": item.get("cnpj") if item else None, "comp": comp.iso if comp else None, "mensagem": msg}

    def erro(self, item, msg):
        self.erros.append(self._it(item, None, msg))

    def aguardando(self, item, msg):
        self.aguardando_l.append(self._it(item, None, msg))

    def revisao(self, item, comp, msg):
        self.revisao_l.append(self._it(item, comp, msg))

    def intervencao(self, item, comp, msg):
        self.intervencao_l.append(self._it(item, comp, msg))

    def alerta(self, tipo, item, msg):
        self.alertas.append({"tipo": tipo, **self._it(item, None, msg)})

    def resumo(self, fila, estado) -> dict:
        return {
            "id": self.eid, "origem": self.origem, "estado": estado, "retomada": self.retomada,
            "inicio": self.inicio, "fim": agora(),
            "total_clientes": self.total,
            "processados": sum(1 for f in fila if f["estado"] == "processado"),
            "nao_processados": sum(1 for f in fila if f["estado"] in ("pendente", "nao_processado")),
            "consultas_ok": self.consultas_ok,
            "guias_emitidas": self.guias_emitidas, "pdfs_baixados": self.pdfs_baixados,
            "competencias_pendentes": self.pendentes, "das_vencidos": self.vencidos,
            "pagamentos_confirmados": self.pagos, "guias_para_sessao_assistida": self.aguardando_sessao,
            "aguardando_autenticacao_n": len(self.aguardando_l), "aguardando_autenticacao": self.aguardando_l,
            "erros_n": len(self.erros), "erros": self.erros,
            "revisao_n": len(self.revisao_l) + len(self.intervencao_l),
            "revisao": self.revisao_l + self.intervencao_l,
            "alertas": self.alertas, "novas_tentativas": self.tentativas_extras,
            "falhas_ao_atualizar_gestor": self.avisos_gestor,
        }

    def salvar_arquivos(self, pasta: Path, r: dict) -> Path:
        pasta = Path(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        base = pasta / f"relatorio_{r['inicio'][:10]}_{r['id'][:8]}"
        base.with_suffix(".json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        base.with_suffix(".html").write_text(html_relatorio(r), encoding="utf-8")
        return base.with_suffix(".html")


def texto_curto(r: dict) -> str:
    """Resumo em texto simples (base para envio futuro por e-mail/WhatsApp)."""
    return (f"Central de DAS MEI — rotina de {r['inicio'][:16].replace('T', ' ')} ({r['estado']})\n"
            f"Clientes: {r['processados']}/{r['total_clientes']} processados\n"
            f"Guias emitidas: {r['guias_emitidas']} · PDFs baixados: {r['pdfs_baixados']}\n"
            f"Pendentes: {r['competencias_pendentes']} · Vencidos: {r['das_vencidos']}\n"
            f"Aguardando autenticação: {r['aguardando_autenticacao_n']} · Erros: {r['erros_n']} · "
            f"Para revisar: {r['revisao_n']}")


def html_relatorio(r: dict) -> str:
    e = html.escape

    def tabela(titulo, itens):
        if not itens:
            return ""
        linhas = "".join(f"<tr><td>{e(i.get('nome') or '—')}</td><td>{e(formatar(i.get('cnpj') or ''))}</td>"
                         f"<td>{e(i.get('comp') or '')}</td><td>{e(i.get('mensagem') or '')}</td></tr>" for i in itens)
        return (f"<h2>{e(titulo)} ({len(itens)})</h2><table><tr><th>Cliente</th><th>CNPJ</th>"
                f"<th>Competência</th><th>Detalhe</th></tr>{linhas}</table>")

    cards = [("Clientes na fila", r["total_clientes"]), ("Processados", r["processados"]),
             ("Consultas com sucesso", r["consultas_ok"]), ("Guias emitidas", r["guias_emitidas"]),
             ("PDFs baixados", r["pdfs_baixados"]), ("Competências pendentes", r["competencias_pendentes"]),
             ("DAS vencidos", r["das_vencidos"]), ("Pagamentos confirmados", r["pagamentos_confirmados"]),
             ("Aguardando autenticação", r["aguardando_autenticacao_n"]), ("Erros", r["erros_n"]),
             ("Para revisar", r["revisao_n"])]
    return f"""<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Relatório DAS MEI</title>
<style>body{{font:14px system-ui,sans-serif;margin:24px;color:#1b1f24}}h1{{font-size:20px}}h2{{font-size:15px;margin-top:24px}}
.c{{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}}.c div{{border:1px solid #ddd;border-radius:8px;padding:10px}}
.c b{{display:block;font-size:22px}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #eee;padding:6px;text-align:left;vertical-align:top}}</style>
<h1>Central de DAS MEI — relatório da rotina</h1>
<p>Início {e(r['inicio'])} · fim {e(r['fim'])} · origem: {e(r['origem'])} · situação: <b>{e(r['estado'])}</b></p>
<div class="c">{''.join(f'<div><b>{v}</b>{e(k)}</div>' for k, v in cards)}</div>
{''.join(f'<p><b>Alerta:</b> {e(a["mensagem"])}</p>' for a in r['alertas'])}
{tabela('Aguardando autenticação', r['aguardando_autenticacao'])}{tabela('Erros', r['erros'])}{tabela('Operações para revisar', r['revisao'])}
<p style="color:#777">Guia emitida ou baixada não significa guia paga. Pagamento só é confirmado pela consulta oficial (PAGTOWEB).</p>
</html>"""
