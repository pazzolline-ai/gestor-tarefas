# Servidor MCP do Gestor de Tarefas

Permite que o Claude (Desktop, Claude Code ou outro cliente MCP) consulte e mexa nas tarefas do
Gestor. Ele entra com **e-mail e senha de um usuário do sistema** e segue as mesmas permissões
da tela (RLS do Supabase), sem chave de administrador. As mudanças aparecem na tela na hora e
ficam no histórico da tarefa ("Tarefa criada pelo Claude (MCP)", mudanças de status, anotações).

## Ferramentas

| Ferramenta | O que faz |
|---|---|
| `resumo_tarefas` | abertas, atrasadas, que vencem hoje, por status e por responsável |
| `listar_tarefas` | filtros: status, responsável, empresa, texto, só atrasadas |
| `ver_tarefa` | tarefa completa com histórico |
| `listar_empresas` / `listar_equipe` | busca de clientes (id para vincular) e da equipe |
| `criar_tarefa` | cria "A fazer" (título, responsável, prazo, prioridade, empresa, descrição) |
| `mudar_status` | afazer · andamento · aguard_cliente · aguard_orgao · concluida |
| `editar_tarefa` | título, responsável, prazo, prioridade, descrição |
| `anotar_tarefa` | anotação no histórico |

Nada é apagado: não há ferramenta de exclusão.

## Instalação (Windows)

1. Instale o Python 3.11 ou mais novo (marque "Add Python to PATH").
2. Nesta pasta: `pip install -r requirements.txt`
3. Recomendado: crie em **Equipe › Usuários** um usuário próprio (ex.: "Claude"), assim o histórico
   mostra quem fez cada mudança.

### Claude Desktop
Em *Configurações › Desenvolvedor › Editar configuração* (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "gestor-tarefas": {
      "command": "python",
      "args": ["-m", "gestor_mcp"],
      "cwd": "C:\\caminho\\para\\gestor-tarefas\\mcp_gestor",
      "env": { "GESTOR_EMAIL": "claude@seuescritorio.com.br", "GESTOR_SENHA": "senha-do-usuario" }
    }
  }
}
```
Reinicie o Claude Desktop.

### Claude Code
```
claude mcp add gestor-tarefas -e GESTOR_EMAIL=... -e GESTOR_SENHA=... -- python -m gestor_mcp
```
(rodando de dentro da pasta `mcp_gestor`).

A senha fica no arquivo de configuração do seu computador: não a coloque no repositório.

## Exemplos de pedidos
- "Quais tarefas estão atrasadas?"
- "Crie uma tarefa para a Ana emitir o alvará da Padaria Sol até sexta, prioridade alta."
- "Marque a tarefa do DAS da Padaria Sol como concluída."

## Testes
`pip install pytest` e `python -m pytest` nesta pasta.
