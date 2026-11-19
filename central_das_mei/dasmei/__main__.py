"""Linha de comando da Central de DAS MEI.

  python -m dasmei configurar      configura acesso ao gestor, SERPRO e pastas
  python -m dasmei testar          testa login no gestor, certificado e SERPRO
  python -m dasmei testar-trial    emite um DAS de demonstração no ambiente de teste da SERPRO
  python -m dasmei executar        roda a rotina agora (todos os clientes MEI)
  python -m dasmei executar --empresa ID [--empresa ID2]
  python -m dasmei assistido       abre o PGMEI cliente por cliente; você resolve o captcha, o robô faz o resto
  python -m dasmei servico         serviço em segundo plano (usado pelo Agendador do Windows)
  python -m dasmei status          últimas execuções
  python -m dasmei backup          backup imediato do banco local
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import logging
import sys
from pathlib import Path

from . import __version__, cnpj as cnpjmod, config as cfgmod, log as logmod
from .banco import Banco
from .segredos import Segredos


def fabrica_serpro(cfg, seg: Segredos):
    from .serpro import IntegraContador

    def criar():
        if cfg.modo_assistido:
            return None
        if cfg.serpro_ambiente == "trial":
            return IntegraContador(ambiente="trial", contratante=cfg.contratante_cnpj or "99999999999999",
                                   intervalo_min=cfg.intervalo_min_segundos, timeout=cfg.timeout_segundos)
        pfx = Path(cfg.certificado_pfx).read_bytes()
        return IntegraContador(ambiente="producao", contratante=cfg.contratante_cnpj, autor=cfg.autor_cnpj,
                               consumer_key=seg.exigir("serpro_consumer_key"),
                               consumer_secret=seg.exigir("serpro_consumer_secret"),
                               pfx=pfx, pfx_senha=seg.ler("certificado_senha") or "",
                               intervalo_min=cfg.intervalo_min_segundos, timeout=cfg.timeout_segundos)
    return criar


def montar(cfg, seg):
    from .gestor import GestorSupabase
    banco = Banco(cfg.banco)
    gestor = GestorSupabase(cfg.supabase_url, cfg.supabase_anon_key, cfg.email_robo, seg.exigir("gestor_senha"))
    return banco, gestor


def _perg(txt, atual="", obrigatorio=True, valida=None):
    while True:
        v = input(f"{txt}{f' [{atual}]' if atual else ''}: ").strip() or atual
        if not v and obrigatorio:
            print("  campo obrigatório")
            continue
        if valida and v and not valida(v):
            print("  valor inválido")
            continue
        return v


def configurar():
    seg = Segredos()
    try:
        cfg = cfgmod.carregar()
    except FileNotFoundError:
        cfg = cfgmod.Config()
    print("=== Central de DAS MEI — configuração ===\n")
    print("1) Gestor de Tarefas (usuário próprio do robô, criado em Equipe › Usuários)")
    cfg.supabase_url = _perg("URL do Supabase", cfg.supabase_url)
    cfg.supabase_anon_key = _perg("Chave pública (anon) do Supabase", cfg.supabase_anon_key)
    cfg.email_robo = _perg("E-mail do usuário Robô DAS", cfg.email_robo)
    s = getpass.getpass("Senha do usuário Robô DAS (Enter mantém a atual): ")
    if s:
        seg.gravar("gestor_senha", s)
    print("\n2) Receita Federal")
    print("   Sem contrato SERPRO Integra Contador o robô trabalha em MODO ASSISTIDO: abre o PGMEI de cada")
    print("   cliente, você resolve o captcha e gera o DAS, e o robô salva, organiza e atualiza o gestor.")
    tem = _perg("Tem contrato SERPRO Integra Contador? (s/n)", "s" if cfg.serpro_ambiente == "producao" else "n",
                valida=lambda v: v.lower() in ("s", "n"))
    cfg.serpro_ambiente = "producao" if tem.lower() == "s" else "nenhum"
    if cfg.serpro_ambiente == "producao":
        cfg.contratante_cnpj = cnpjmod.limpar(_perg("CNPJ do escritório (contratante)", cfg.contratante_cnpj, valida=cnpjmod.valido))
        cfg.autor_cnpj = cnpjmod.limpar(_perg("CNPJ do autor do pedido (Enter = escritório)", cfg.autor_cnpj or cfg.contratante_cnpj))
        cfg.certificado_pfx = _perg("Caminho do certificado e-CNPJ A1 (.pfx)", cfg.certificado_pfx, valida=lambda v: Path(v).is_file())
        for chave, rot in (("serpro_consumer_key", "Consumer Key"), ("serpro_consumer_secret", "Consumer Secret"),
                           ("certificado_senha", "Senha do certificado")):
            v = getpass.getpass(f"{rot} (Enter mantém o atual): ")
            if v:
                seg.gravar(chave, v)
    print("\n3) Pasta dos documentos")
    cfg.pasta_documentos = _perg("Pasta CENTRAL_DAS_MEI", cfg.pasta_documentos)
    Path(cfg.pasta_documentos).mkdir(parents=True, exist_ok=True)
    p = cfgmod.salvar(cfg)
    print(f"\nConfiguração salva em {p}. Senhas e chaves foram para o Cofre de Credenciais do Windows.")
    print("Agora rode: python -m dasmei testar")


def testar(cfg, seg):
    ok = True
    print("Gestor…", end=" ", flush=True)
    try:
        banco, gestor = montar(cfg, seg)
        aptos, probl = gestor.clientes_mei()
        print(f"OK — {len(aptos)} clientes MEI aptos, {len(probl)} com problema no cadastro")
        for p in probl:
            print(f"   ! {p['nome']}: {p['problema']}")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"FALHOU: {e}")
    try:
        from playwright.sync_api import sync_playwright
        from .assistido import abrir_navegador
        print("Navegador (Edge/Chrome)…", end=" ", flush=True)
        with sync_playwright() as pw:
            abrir_navegador(pw).close()
        print("OK")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"FALHOU: {e}")
    if cfg.modo_assistido:
        print("SERPRO… não contratado: modo assistido (sessão no PGMEI).")
        return ok
    if cfg.serpro_ambiente == "producao":
        from .serpro import info_certificado
        print("Certificado…", end=" ", flush=True)
        try:
            i = info_certificado(Path(cfg.certificado_pfx).read_bytes(), seg.ler("certificado_senha") or "")
            print(f"OK — {i['titular']} · válido até {i['valido_ate']} ({i['dias_restantes']} dias)")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"FALHOU: {e}")
    print("SERPRO (autenticação)…", end=" ", flush=True)
    try:
        cli = fabrica_serpro(cfg, seg)()
        cli.autenticar()
        cli.fechar()
        print("OK")
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"FALHOU: {e}")
    return ok


def testar_trial(cfg):
    """Chamada REAL ao ambiente de demonstração da SERPRO (dados fictícios dela)."""
    from . import pdf as pdfmod
    from .serpro import IntegraContador
    cli = IntegraContador(ambiente="trial", contratante="99999999999999", intervalo_min=0)
    try:
        g = cli.gerar_das_pdf("00000000000100", "201901")
    finally:
        cli.fechar()
    if not g:
        print("A SERPRO não devolveu guia no ambiente de teste.")
        return False
    d = g[0]
    lido = pdfmod.ler(d.pdf)
    destino = Path(cfg.pasta_documentos) / "_SISTEMA" / "teste_trial_DAS.pdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(d.pdf)
    det = d.detalhes[0] if d.detalhes else None
    print(f"OK — PDF válido ({lido.paginas} pág.) salvo em {destino}")
    if det:
        print(f"   documento {det.numero_documento} · vencimento {det.data_vencimento} · total {det.total}")
    print(f"   leitura do PDF: {json.dumps(lido.dict(), ensure_ascii=False)}")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dasmei", description=f"Central de DAS MEI {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("configurar", "testar", "testar-trial", "servico", "status", "backup"):
        sub.add_parser(n)
    asi = sub.add_parser("assistido")
    asi.add_argument("--empresa", action="append", help="id da empresa no gestor (pode repetir)")
    ex = sub.add_parser("executar")
    ex.add_argument("--empresa", action="append", help="id da empresa no gestor (pode repetir)")
    a = ap.parse_args(argv)
    if a.cmd == "configurar":
        return configurar()
    try:
        cfg = cfgmod.carregar()
    except (FileNotFoundError, ValueError) as e:
        print(e)
        return 2
    logmod.configurar(cfg.pasta_sistema)
    seg = Segredos()
    if a.cmd == "testar":
        return 0 if testar(cfg, seg) else 1
    if a.cmd == "testar-trial":
        return 0 if testar_trial(cfg) else 1
    if a.cmd == "status":
        b = Banco(cfg.banco)
        for e in b.todos("SELECT id,inicio,fim,origem,estado,resumo FROM execucoes ORDER BY inicio DESC LIMIT 10"):
            r = json.loads(e["resumo"] or "{}")
            print(f"{e['inicio']} {e['estado']:<12} {e['origem']:<9} processados {r.get('processados', '-')}/"
                  f"{r.get('total_clientes', '-')} · guias {r.get('guias_emitidas', '-')} · erros {r.get('erros_n', '-')}")
        return 0
    if a.cmd == "backup":
        b = Banco(cfg.banco)
        p = b.backup(cfg.pasta_backup / f"dasmei-manual-{dt.datetime.now():%Y%m%d-%H%M%S}.db")
        print(f"Backup salvo em {p}")
        return 0
    banco, gestor = montar(cfg, seg)
    if a.cmd == "assistido":
        from .assistido import SessaoAssistida
        from .relatorio import texto_curto
        r = SessaoAssistida(cfg, banco, gestor).executar(a.empresa)
        print(texto_curto(r))
        return 0
    if a.cmd == "executar":
        from .motor import Motor
        r = Motor(cfg, banco, gestor, fabrica_serpro(cfg, seg)).executar("manual", a.empresa)
        from .relatorio import texto_curto
        print(texto_curto(r) if "processados" in r else r)
        return 0
    if a.cmd == "servico":
        from .agendador import Servico, trava_instancia
        trava = trava_instancia()
        if not trava:
            logging.getLogger("dasmei").info("O serviço já está rodando neste computador.")
            return 0
        Servico(cfg, banco, gestor, fabrica_serpro(cfg, seg)).rodar()
        return 0


if __name__ == "__main__":
    sys.exit(main())
