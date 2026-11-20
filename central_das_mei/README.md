# Central de DAS MEI: robô fiscal

Robô que roda no PC do escritório, cuida dos DAS de **todos os clientes MEI** cadastrados no Gestor de Tarefas e mostra tudo na tela **Fiscal › Central de DAS MEI**.

Ele funciona de dois jeitos:

| | **Modo assistido** (padrão, gratuito) | **Modo automático** (com contrato SERPRO) |
|---|---|---|
| Como acessa a Receita | abre o **PGMEI oficial** no Edge/Chrome do PC | API oficial **Integra Contador** (SERPRO) |
| Captcha "não sou um robô" | **uma pessoa resolve** (o robô nunca mexe no captcha) | não existe |
| O que a pessoa faz | resolve o captcha e gera o DAS (uns 20 a 30 s por cliente) | nada |
| O que o robô faz | preenche o CNPJ, captura o PDF, confere, arquiva, atualiza o gestor e abre o próximo cliente | tudo, sozinho, às 07:00 |
| Confirmar pagamento | alguém informa na tela, depois de conferir o comprovante | consulta oficial PAGTOWEB |
| Custo | nenhum | cobrança por consulta/guia (Loja SERPRO) |

A mudança de modo é só configuração: tudo do modo automático já está pronto para quando o escritório contratar.

E pode ser usado de dois lugares:

| | **Integrado ao Gestor de Tarefas** | **Versão separada** |
|---|---|---|
| Tela | Fiscal › Central de DAS MEI, no gestor (qualquer PC ou celular da equipe) | programa próprio no PC do robô: atalho **"Central de DAS MEI"** na área de trabalho |
| Cadastro de clientes | o de Empresas do gestor (regime "MEI") | cadastro próprio na aba **Clientes**: um por um ou **importando planilha** (CSV/Excel) |
| Onde ficam os dados | Supabase do gestor (resumo) + banco local | só no PC (banco local), nada vai para a internet |
| Extras | atalho no painel "Guias DAS-MEI" do Início | **Abrir PDF**, **Abrir pasta** e **WhatsApp** com a mensagem pronta em cada guia |

Na instalação, a pergunta "Integrar ao Gestor de Tarefas? (s/n)" escolhe. Para ter as duas, instale a pasta duas vezes em PCs (ou usuários do Windows) diferentes. No mesmo usuário roda só uma, porque o serviço tem trava de instância única.

> **Guia emitida ou baixada não significa guia paga.** "Pago confirmado" só aparece com a consulta oficial da Receita ou quando alguém informa na tela que conferiu o comprovante (fica registrado quem e quando).

---

## 1. Instalação no PC do escritório

Precisa de:
- Windows 10/11;
- Python 3.11 ou mais novo (python.org, marcando "Add python.exe to PATH");
- Microsoft Edge (já vem no Windows).

1. No gestor, crie o usuário do robô: **Equipe › Usuários › novo usuário "Robô DAS"** (papel comum).
2. Copie esta pasta `central_das_mei` para o PC (por exemplo `C:\CentralDasMei`).
3. Dê dois cliques em **`instalar.bat`**. Ele:
   - cria o ambiente Python e instala tudo;
   - pergunta e-mail e senha do Robô DAS, se há contrato SERPRO (responda **n**) e a pasta dos documentos (padrão `C:\CENTRAL_DAS_MEI`);
   - testa o login no gestor e a abertura do navegador;
   - protege a pasta dos documentos (só o usuário, Administradores e Sistema);
   - cria no **Agendador de Tarefas do Windows** o serviço que inicia com o Windows e o "garantir" diário às 06:40.
4. Abra o gestor em **Fiscal › Central de DAS MEI**. O ponto verde mostra "Robô ativo no PC … · modo assistido".

A chave pública (anon) do Supabase é a mesma do `index.html` do sistema (`SB_KEY`). Senhas vão para o **Cofre de Credenciais do Windows**; o `config.toml` (em `%LOCALAPPDATA%\CentralDasMei`) não guarda nenhuma.

### Versão separada

1. Rode `instalar.bat` e responda **n** em "Integrar ao Gestor de Tarefas?". Não precisa de usuário no gestor.
2. Abra pelo atalho **Central de DAS MEI** na área de trabalho (ou `abrir_central.bat`). O navegador abre a tela em `http://127.0.0.1:8777`.
3. Na aba **Clientes**, cadastre os MEI ou clique em **Importar planilha**:
   - a primeira linha deve ter a coluna **CNPJ** e o nome (Razão social, Nome ou Cliente);
   - opcionais: Nome fantasia, WhatsApp/Telefone, Responsável, E-mail;
   - importar de novo atualiza pelo CNPJ, sem duplicar.
4. O resto é igual: sessão assistida, rotina, relatórios, informar pagamento. Em cada guia há **Abrir PDF**, **Abrir pasta** e **WhatsApp**, este último com a mensagem pronta para o cliente; o PDF você anexa.

Segurança da versão separada:
- a tela só abre neste PC (127.0.0.1) e só com a chave que o atalho usa (cookie protegido);
- PDFs e pastas só são abertos se estiverem dentro de `CENTRAL_DAS_MEI`.

## 2. Rotina do mês (modo assistido)

1. Todo dia às 07:00 o robô atualiza a situação de cada cliente: quem precisa da guia do mês, o que está pendente ou vencido, e os pagamentos informados.
2. Na tela, clique em **Abrir sessão assistida**. Também dá para usar o `sessao_assistida.bat` no PC do robô.
3. No PC do robô o PGMEI abre já com o CNPJ do primeiro cliente e uma **barra preta de instruções** embaixo. Para cada cliente:
   1. o CNPJ já vem preenchido: clique em **Continuar**. Se o PGMEI mostrar o desafio de imagens do hCaptcha, resolva;
   2. vá em **Emitir Guia de Pagamento (DAS)**, escolha o ano, marque o mês e clique em **Apurar/Gerar DAS** e depois em **Imprimir/Visualizar PDF**;
   3. o robô pega o PDF sozinho, confere o CNPJ, lê período, vencimento, valor e número, salva em `CENTRAL_DAS_MEI\CNPJ\ANO\MÊS\` e **vai para o próximo cliente**.
4. Botões da barra:
   - **Emitir outro mês deste cliente**, para gerar mais de um mês;
   - **Pular cliente**;
   - **Próximo cliente**;
   - **Encerrar sessão**.

Se você gerar o PDF de outro CNPJ por engano, o robô recusa e não salva nada. Só entram na fila os clientes que ainda não têm guia válida do mês e não têm pagamento informado.

Para **informar pagamento**: abra o cliente na Central, clique em **Informar pagamento**, escolha competência, data e valor (opcional). Use depois de conferir o comprovante ou o "Pago" que o próprio PGMEI mostra. Dá para desfazer. O robô aplica na rotina seguinte.

## 3. Tela do gestor

- Indicadores:
  - clientes MEI, consultados e não consultados;
  - guias emitidas e baixadas, e quem **precisa de guia**;
  - competências pendentes e DAS vencidos;
  - aguardando autenticação e erros;
  - última e próxima execução.
- **Precisa de você**: o que exige ação humana.
- Tabela de clientes com filtros e busca. Em **Detalhes**, cada competência mostra situação, vencimento, guia (número, valor, até quando pagar, caminho do PDF) e pagamento, com a evidência.
- **Rotina** (gestores): horário, dias, meses acompanhados, emitir mês/vencidos, pausar.
- **Histórico** e **relatórios** de cada execução e sessão.

Quem entra no robô: empresas com **regime "MEI"**, não inativas e com "Emite guia DAS-MEI todo mês" marcado. Cadastre o cliente uma vez em Empresas.

## 4. Situações

| Situação | Significado |
|---|---|
| Não consultado | ainda não verificado. No modo assistido, meses antigos ficam assim até alguém informar o pagamento |
| Consultado / Em dia | as competências acompanhadas estão com pagamento confirmado |
| DAS emitido → disponível → Guia baixada | ciclo do documento: recebido → PDF validado → arquivado com SHA-256 |
| Pendente | a pagar, no prazo |
| Vencido | passou do vencimento (dia 20, ou o próximo dia útil) sem pagamento confirmado |
| Pago confirmado | consulta oficial ou pagamento informado com comprovante (com registro de quem informou) |
| Aguardando autenticação | (modo automático) falta a procuração eletrônica do cliente |
| Erro de consulta | falha temporária; o robô tenta de novo |
| Exige intervenção humana | PDF inválido ou divergente, cadastro sem CNPJ, recusa da Receita, pagamento sem identificação clara |

## 5. Proteções

- **Um cliente por vez**: o erro de um não para os outros.
- **Sem duplicidade**:
  - operações com identificador único;
  - o mesmo PDF ou número de documento não é registrado duas vezes;
  - não emite de novo guia ainda válida.
- **Nunca sobrescreve**: arquivo igual é reaproveitado; arquivo diferente com o mesmo nome vira `_v2`.
- **Validação do PDF**: estrutura, CNPJ do cliente, período, vencimento e valor.
- **LGPD**:
  - PDFs só no PC do escritório, em pasta restrita;
  - o gestor recebe apenas o resumo;
  - logs sem senhas ou tokens;
  - backup diário do banco local (30 dias) em `CENTRAL_DAS_MEI\_SISTEMA\backups`;
  - auditoria de cada ação.
- O robô **não** declara, transmite ou altera nada na Receita.

## 6. Quando contratar o SERPRO (modo automático)

1. Contrate o **Integra Contador** na Loja SERPRO para receber *Consumer Key* e *Consumer Secret*.
2. Tenha o **e-CNPJ A1** do escritório (`.pfx`).
3. Peça a cada MEI a **procuração eletrônica no e-CAC** para o CNPJ do escritório.
4. Rode `instalar.bat` de novo e responda **s** para o contrato SERPRO.
5. Rode `python -m dasmei testar-trial` para emitir um DAS de demonstração da SERPRO, sem custo.
6. Teste um cliente com **Processar só este cliente agora**.

A partir daí o robô consulta pagamentos e emite tudo sozinho às 07:00. Para limitar o custo, ele não reemite guia válida nem consulta mês já pago.

## 7. Comandos

```
python -m dasmei configurar     # refazer a configuração
python -m dasmei testar         # gestor + navegador (+ certificado e SERPRO, se contratado)
python -m dasmei assistido [--empresa ID]
python -m dasmei executar [--empresa ID]   # rotina (atualiza situação; no modo automático emite)
python -m dasmei status         # últimas execuções
python -m dasmei backup
python -m dasmei servico        # o que o Agendador do Windows executa
python -m dasmei abrir          # versão separada: abre a tela local
```
- Logs: `%LOCALAPPDATA%\CentralDasMei\logs\dasmei.log`.
- `desinstalar.bat` remove as tarefas automáticas, sem apagar documentos nem histórico.
- O PC precisa estar **ligado e com o usuário conectado** (a tela pode estar bloqueada).

E-mail e WhatsApp do relatório estão **preparados, mas desligados** (`dasmei/notificacoes.py`).

## 8. Testes automatizados

```
pip install pytest
python -m pytest -q
```
São 92 testes com dados fictícios. Cobrem:
- regras de CNPJ, vencimentos e status;
- PDFs e pastas;
- formato exato dos pedidos à API SERPRO e erros, lote completo, idempotência e retomada;
- **sessão assistida** num navegador real contra um PGMEI simulado: PDF visualizado e baixado, PDF de outro CNPJ recusado, barra de instruções;
- rotina sem SERPRO, pagamento informado e desfeito;
- agendamento e pedidos vindos da tela;
- versão separada: cadastro, importação CSV/Excel sem duplicar, chave de acesso da tela, proteção contra CSRF e contra abrir arquivos fora da pasta.

A abertura do PGMEI real foi testada (campo de CNPJ preenchido e barra de instruções exibida). A emissão do DAS de verdade depende do captcha e de um CNPJ real, então **faça a primeira sessão assistida com 1 ou 2 clientes e confira os PDFs salvos.** Se a Receita mudar o nome do campo de CNPJ, a barra pede para digitar o CNPJ; todo o resto continua funcionando.
