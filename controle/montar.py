#!/usr/bin/env python3
"""Monta o Controle a partir do Gestor de Tarefas (index.html).

O Controle é o Gestor idêntico, com dados separados (outra organização no banco,
escolhida pelo cabeçalho x-app: controle) e com o módulo de Pró-labore e folha.
Rodar: python3 controle/montar.py <saida/index.html>
Toda atualização do Gestor entra no Controle na próxima publicação.
"""
import pathlib, sys

raiz = pathlib.Path(__file__).resolve().parent.parent
s = (raiz / 'index.html').read_text(encoding='utf-8')
folha = (raiz / 'controle' / 'folha.js').read_text(encoding='utf-8')

# Preferências do Controle ficam separadas das do Gestor (mesmo site); o login é o mesmo.
SHIM = ("<script>(function(){var S=Storage.prototype,g=S.getItem,t=S.setItem,r=S.removeItem;"
        "function P(k){k=String(k);return /^gt\\.auth/.test(k)?k:'ctl:'+k}"
        "S.getItem=function(k){return g.call(this,P(k))};S.setItem=function(k,v){return t.call(this,P(k),v)};"
        "S.removeItem=function(k){return r.call(this,P(k))}})();</script>")
MSG = "No Controle, o acesso de novas pessoas é liberado pelo Claude. Peça no chat."

trocas = [
    # dados separados do Gestor
    ("<head>", "<head>" + SHIM, 1),
    ("storageKey:'gt.auth'}}", "storageKey:'gt.auth'},global:{headers:{'x-app':'controle'}}}", 1),
    ("siteUrl:'https://pazzolline-ai.github.io/gestor-tarefas/'", "siteUrl:'https://pazzolline-ai.github.io/gestor-tarefas/controle/'", 1),
    ("sb.from('membros')", "sb.from('membros_ctl')", 1),
    ("{event:'*',schema:'public',table:'docs'}", "{event:'*',schema:'public',table:'docs',filter:'org_id=eq.00000000-0000-0000-0000-000000000000'}", 1),
    ("canalOk=st==='SUBSCRIBED'", "canalOk=false", 1),
    ("sb.channel('presenca'", "sb.channel('presenca-controle'", 1),
    ("GT.fn=async(acao,body)=>{", "GT.fn=async(acao,body)=>{body=Object.assign({app:'controle'},body||{});", 1),
    ("GT.linkAgenda=async(novo)=>{", "GT.linkAgenda=async(novo)=>{throw new Error('O link da agenda fica no Gestor de Tarefas.');", 1),
    # app de celular próprio do Controle
    ("releases/latest/download/Gestor-de-Tarefas-Instalador.exe", "releases/download/programa-windows-controle/Controle-Lucas-Instalador.exe", 1),
    ("gestor-tarefas/releases/download/app-android/Gestor-de-Tarefas.apk", "gestor-tarefas/releases/download/app-android-controle/Controle-Lucas.apk", 1),
    # nome
    ("<title>Gestor de Tarefas</title>", "<title>Controle Lucas</title>", 1),
    ("mk.app_nome||'Gestor de Tarefas'", "mk.app_nome||'Controle Lucas'", 2),
    ("mk.app_sub||'Londe & Rodrigues'", "mk.app_sub||'Lucas Pazolline'", 1),
    ("o.app_nome||'Gestor de Tarefas'", "o.app_nome||'Controle Lucas'", 2),
    ("o.app_sub||'Londe & Rodrigues'", "o.app_sub||'Lucas Pazolline'", 2),
    # módulo Pró-labore e folha
    ("['financeiro','Financeiro','money']];", "['financeiro','Financeiro','money'],['folha','Pró-labore e folha','money']];", 1),
    ("propostas:vPropostas}[UI.view]", "propostas:vPropostas,folha:vFolha}[UI.view]", 1),
    ("['dp','Depto. Pessoal','#4f8fe8',['@dp']]", "['dp','Depto. Pessoal','#4f8fe8',['@dp','folha']]", 1),
    ("const titles={dashboard:['Início',''],", "const titles={dashboard:['Início',''],folha:['Pró-labore e folha','Recibos de pró-labore e de colaboradores, com INSS, IRRF e FGTS do mês'],", 1),
    ("agcfg:new Map(),irpf:new Map(),salmat:new Map()};", "agcfg:new Map(),irpf:new Map(),salmat:new Map(),folha:new Map()};", 1),
    ("agcfg:false,irpf:false,salmat:false};", "agcfg:false,irpf:false,salmat:false,folha:false};", 1),
    ("'compromissos','agcfg','leads','irpf','salmat']", "'compromissos','agcfg','leads','irpf','salmat','folha']", None),
    ("\nboot();\n})();", "\n" + folha + "\nboot();\n})();", 1),
]
for de, para, n in trocas:
    c = s.count(de)
    if (n is None and c < 1) or (n is not None and c != n):
        sys.exit(f'Controle: trecho do Gestor mudou ({c}x, esperado {n}): {de[:70]}')
    s = s.replace(de, para)

saida = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else raiz / 'controle' / 'index.html')
saida.parent.mkdir(parents=True, exist_ok=True)
saida.write_text(s, encoding='utf-8')
print('Controle montado:', saida, len(s), 'bytes')
