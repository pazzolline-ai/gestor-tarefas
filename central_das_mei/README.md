# Central de DAS MEI — robô fiscal

Robô que roda no PC do escritório e, todo dia (padrão 07:00), para **todos os clientes MEI** cadastrados no Gestor de Tarefas:

1. consulta os **pagamentos oficiais** na Receita (PAGTOWEB) das competências acompanhadas;
2. marca cada competência como **Pago confirmado**, **Pendente** ou **Vencido**;
3. **emite o DAS** pelo PGMEI quando autorizado e ainda não existir guia válida;
4. **valida e baixa o PDF**, confere CNPJ/período/vencimento/valor e organiza em `CENTRAL_DAS_MEI\CNPJ\ANO\MÊS\`;
5. atualiza a tela **Fiscal › Central de DAS MEI** do gestor e o painel "Guias DAS-MEI" do Início;
6. gera um **relatório** (tela + arquivo HTML/JSON) e sinaliza quem precisa de ação humana, **sem parar os demais**.

O acesso é pela **API oficial Integra Contador (SERPRO/Receita Federal)**, sem raspagem de tela, sem contornar captcha e sem usar senha gov.br de cliente.

> **Guia emitida ou baixada não significa guia paga.** "Pago confirmado" só aparece com a evidência da consulta oficial de pagamentos.

---

## 1. O que o escritório precisa ter (uma vez)

| Item | Onde conseguir |
|---|---|
| Contrato **Integra Contador** na Loja SERPRO (gera *Consumer Key* e *Consumer Secret*) | loja.serpro.gov.br, com o e-CNPJ do escritório |
| **Certificado e-CNPJ A1** do escritório (arquivo `.pfx` + senha) | certificadora ICP-Brasil |
| **Procuração eletrônica** de cada MEI para o CNPJ do escritório, com os serviços do PGMEI e de consulta de pagamentos | o cliente concede no e-CAC (ou o escritório solicita) |
| Usuário próprio do robô no gestor: **Equipe › Usuários › novo usuário "Robô DAS"** (papel comum, nada de diretoria) | no próprio gestor |
| PC com Windows 10/11 que fique ligado de manhã, com **Python 3.11+** | python.org (marcar "Add python.exe to PATH") |

Custos: cada consulta de pagamentos e cada guia emitida é uma chamada cobrada pelo contrato SERPRO. Com a rotina diária, o robô **não emite de novo** guia que ainda é válida e **não consulta** competência já confirmada como paga. Para reduzir chamadas, dá para escolher na tela só os dias úteis ou menos meses retroativos.

Clientes **sem procuração** aparecem como **Aguardando autenticação**, com a orientação do que pedir. Os outros continuam normalmente.

## 2. Instalação no PC do escritório

1. Baixe esta pasta `central_das_mei` para o PC (por exemplo `C:\CentralDasMei`).
2. Dê dois cliques em **`instalar.bat`**. Ele:
   - cria o ambiente Python e instala as dependências;
   - pergunta os dados (e-mail e senha do usuário Robô DAS, CNPJ do escritório, caminho do `.pfx`, Consumer Key/Secret, senha do certificado, pasta dos documentos);
   - testa tudo (`testar`): login no gestor, validade do certificado e autenticação na SERPRO;
   - protege a pasta dos documentos (só o usuário atual, Administradores e Sistema);
   - cria no **Agendador de Tarefas do Windows** duas tarefas: iniciar o serviço ao entrar no Windows e um "garantir" diário às 06:40, que acorda o PC da suspensão se o hardware permitir.
3. Abra o gestor em **Fiscal › Central de DAS MEI**. O ponto verde mostra "Robô ativo no PC …".

A chave pública (anon) do Supabase é a mesma que já está no `index.html` do sistema (`SB_KEY`).

**Onde ficam os segredos:** senha do robô, Consumer Key/Secret e senha do certificado vão para o **Cofre de Credenciais do Windows** (protegido pelo login do usuário). O arquivo `config.toml` (em `%LOCALAPPDATA%\CentralDasMei`) não guarda nenhuma senha.

## 3. Primeiro uso, com segurança

1. `executar_agora.bat` não é o primeiro passo. Antes, teste a ligação com a SERPRO no **ambiente de demonstração**, com dados fictícios da própria SERPRO e sem custo:
   ```
   .venv\Scripts\python -m dasmei testar-trial
   ```
   Isso emite o DAS de demonstração, valida o PDF e salva em `CENTRAL_DAS_MEI\_SISTEMA\teste_trial_DAS.pdf`.
2. Antes de ligar a rotina para todos, **pause a rotina** (tela › Rotina › "Pausar a rotina automática") e processe **um cliente autorizado**: abra o cliente na Central e clique em **"Processar só este cliente agora"**. Confira o PDF na pasta e os dados na tela.
3. Estando tudo certo, desmarque "Pausar" e deixe a rotina automática trabalhar.

## 4. Uso no dia a dia (pela tela do gestor)

- **Executar agora**: o robô começa em até 1 minuto, mesmo fora do horário.
- **Rotina** (gestores): horário, dias da semana, quantos meses para trás, emitir o mês, emitir vencidos, consultar pagamentos, pausar. O robô aplica as mudanças em até 1 minuto.
- **Detalhes do cliente**: cada competência com situação, vencimento, guia (número, valor, até quando pode ser paga, caminho do PDF) e pagamento confirmado com a evidência. Ali também ficam "Processar só este cliente" e "Tirar do robô".
- **Precisa de você**: clientes aguardando autenticação, com erro ou que exigem intervenção.
- **Histórico de execuções** e **Último relatório**: totais, pendências, erros e operações para revisar.

Quem entra no robô: empresas do cadastro com **regime "MEI"**, não inativas e com "Emite guia DAS-MEI todo mês" marcado. Cadastre o cliente uma vez em Empresas e pronto.

## 5. Situações

| Situação | Significado |
|---|---|
| Não consultado | o robô ainda não passou por este cliente |
| Consultado / Em dia | todas as competências acompanhadas estão com pagamento confirmado |
| DAS emitido → DAS disponível para download → Guia baixada | ciclo do documento: recebido da Receita → PDF validado → arquivado com SHA-256 |
| Pendente | competência a pagar, ainda no prazo |
| Vencido | passou do vencimento legal (dia 20, ou o próximo dia útil) sem pagamento confirmado |
| Pago confirmado | a consulta oficial de pagamentos mostrou a arrecadação (data, valor e documento registrados) |
| Aguardando autenticação | falta procuração eletrônica do cliente (ou ela não cobre os serviços) |
| Erro de consulta | falha temporária mesmo após novas tentativas; o robô tenta de novo na próxima rotina |
| Exige intervenção humana | a Receita recusou o pedido, o PDF veio inválido ou divergente, o cadastro está sem CNPJ, ou há pagamento sem identificação clara |

## 6. Como o robô se protege

- **Um cliente por vez**, com pausa entre clientes e um intervalo mínimo entre chamadas à SERPRO.
- **Novas tentativas** só para falhas temporárias (rede, 429, 5xx), com espera crescente.
- **Portal fora do ar**: depois de 5 clientes seguidos com falha, a rotina é interrompida e **retomada automaticamente** a cada 30 min, do ponto onde parou. Se o PC desligar no meio da rotina, ela também é retomada.
- **Credenciais do escritório** (certificado vencido, chave errada): a rotina para e avisa, em vez de errar 300 vezes.
- **Sem duplicidade**:
  - cada operação tem identificador único;
  - nenhuma guia é emitida de novo enquanto a anterior for válida e o arquivo estiver íntegro (hash);
  - a mesma guia não é emitida duas vezes no mesmo dia;
  - o mesmo número de documento nunca é registrado duas vezes.
- **Nunca sobrescreve**: arquivo igual é reaproveitado; arquivo diferente com o mesmo nome vira `_v2`.
- **Lista fechada de serviços**: só `PGMEI/GERARDASPDF21` (emitir DAS) e `PAGTOWEB/PAGAMENTOS71` (consultar pagamentos). Nada que declare, transmita ou altere dados.
- **LGPD**:
  - os PDFs ficam só no PC do escritório, em pasta com acesso restrito;
  - o gestor recebe apenas o resumo;
  - os logs mascaram tokens e senhas;
  - o certificado é aberto em memória e o temporário cifrado é apagado com sobrescrita;
  - backup diário do banco local (30 dias) em `CENTRAL_DAS_MEI\_SISTEMA\backups`;
  - auditoria de cada ação no banco local.

## 7. Comandos

```
python -m dasmei configurar     # refazer a configuração
python -m dasmei testar         # gestor + certificado + SERPRO
python -m dasmei testar-trial   # DAS de demonstração da SERPRO (sem custo)
python -m dasmei executar [--empresa ID]
python -m dasmei status         # últimas execuções
python -m dasmei backup
python -m dasmei servico        # o que o Agendador do Windows executa
```
Logs: `%LOCALAPPDATA%\CentralDasMei\logs\dasmei.log`. Para remover as tarefas automáticas: `desinstalar.bat` (não apaga documentos nem histórico).

## 8. Requisitos e limites

- O PC precisa estar **ligado e com o usuário conectado** (a tela pode estar bloqueada) na hora da rotina. O Cofre de Credenciais do Windows só abre para o usuário logado.
- E-mail e WhatsApp do relatório estão **preparados, mas desligados** (`dasmei/notificacoes.py`). O texto já sai pronto; falta ligar um canal autorizado.
- O robô não recalcula benefícios, não declara a DASN-SIMEI e não altera nada na Receita.

## 9. Testes automatizados

```
pip install pytest
python -m pytest -q
```
São 75 testes com dados fictícios e uma SERPRO simulada. Cobrem:
- CNPJ e competências/vencimentos;
- regras de status;
- validação e leitura de PDF;
- pastas sem sobrescrita;
- formato exato dos pedidos à API e classificação de erros;
- lote completo, idempotência, retomada após queda, pagamento confirmado só com evidência;
- cliente sem procuração, PDF inválido, botão "Executar agora", agendamento e backup.
