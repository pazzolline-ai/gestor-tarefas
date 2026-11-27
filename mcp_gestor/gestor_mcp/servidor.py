"""Servidor MCP do Gestor de Tarefas.

Rodar:  python -m gestor_mcp   (stdio, para Claude Desktop / Claude Code)
Variáveis: GESTOR_EMAIL e GESTOR_SENHA (obrigatórias); GESTOR_URL e GESTOR_CHAVE (opcionais)
"""
from __future__ import annotations

import os
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from .banco import Banco, BancoSupabase
from .tarefas import Tarefas

# Endereço e chave PÚBLICA (anon) do Supabase: os mesmos já publicados no index.html.
# Quem protege os dados é o login de cada pessoa + RLS, não esta chave.
URL_PADRAO = "https://nhrbbsgmipkwqeqqkgjj.supabase.co"
CHAVE_PADRAO = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im5ocmJic2dtaXBrd3FlcXFrZ2pqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTE3OTYxODEsImV4cCI6MjEwNzM3MjE4MX0.o9hUAuGTJTnaW9hhPZ7vLdOjUecdpp6PUCNCHI_T02g"

Status = Literal["afazer", "andamento", "aguard_cliente", "aguard_orgao", "concluida"]
Prioridade = Literal["normal", "media", "alta", "urgente"]

LEITURA = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
ESCRITA = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)


def criar_servidor(banco: Banco | None = None) -> MCPServer:
    _t: list[Tarefas] = []

    def T() -> Tarefas:
        if not _t:
            _t.append(Tarefas(banco or BancoSupabase(
                os.environ.get("GESTOR_URL") or URL_PADRAO, os.environ.get("GESTOR_CHAVE") or CHAVE_PADRAO,
                os.environ.get("GESTOR_EMAIL"), os.environ.get("GESTOR_SENHA"))))
        return _t[0]

    mcp = MCPServer(
        name="gestor-tarefas",
        title="Gestor de Tarefas — Londe & Rodrigues",
        instructions=(
            "Acesso às tarefas do escritório. Status: afazer, andamento, aguard_cliente, aguard_orgao, concluida. "
            "Datas em AAAA-MM-DD. Para vincular uma empresa, busque o id com listar_empresas. "
            "Antes de criar ou alterar tarefas, confirme com a pessoa o que será gravado."
        ),
    )

    @mcp.tool(annotations=LEITURA)
    def listar_tarefas(status: Status | None = None, responsavel: str | None = None, empresa: str | None = None,
                       texto: str | None = None, somente_atrasadas: bool = False,
                       incluir_concluidas: bool = False, limite: int = 50) -> list[dict]:
        """Lista tarefas, ordenadas por prazo. Sem status, traz só as abertas.
        Filtros de responsável, empresa e texto aceitam parte do nome."""
        return T().listar(status, responsavel, empresa, texto, somente_atrasadas, incluir_concluidas, limite)

    @mcp.tool(annotations=LEITURA)
    def ver_tarefa(id: str) -> dict:
        """Mostra uma tarefa completa, com descrição e histórico recente."""
        return T().ver(id)

    @mcp.tool(annotations=LEITURA)
    def resumo_tarefas() -> dict:
        """Panorama das tarefas abertas: atrasadas, que vencem hoje, por status e por responsável."""
        return T().resumo()

    @mcp.tool(annotations=LEITURA)
    def listar_empresas(texto: str | None = None, limite: int = 30) -> list[dict]:
        """Busca empresas (clientes) por nome, razão social ou CNPJ. Devolve o id usado em criar_tarefa."""
        return T().empresas(texto, limite)

    @mcp.tool(annotations=LEITURA)
    def listar_equipe() -> list[dict]:
        """Pessoas ativas da equipe (nomes usados como responsável)."""
        return T().equipe()

    @mcp.tool(annotations=ESCRITA)
    def criar_tarefa(titulo: str, responsavel: str | None = None, prazo: str | None = None,
                     prioridade: Prioridade = "normal", empresa_id: str | None = None,
                     descricao: str = "", categoria: str = "") -> dict:
        """Cria uma tarefa 'A fazer'. Sem responsável, fica com o usuário conectado. Prazo em AAAA-MM-DD."""
        return T().criar(titulo, responsavel, prazo, prioridade, empresa_id, descricao, categoria)

    @mcp.tool(annotations=ESCRITA)
    def mudar_status(id: str, status: Status, observacao: str = "") -> dict:
        """Muda o status de uma tarefa (ex.: concluir) e registra no histórico."""
        return T().mudar_status(id, status, observacao)

    @mcp.tool(annotations=ESCRITA)
    def editar_tarefa(id: str, titulo: str | None = None, responsavel: str | None = None,
                      prazo: str | None = None, prioridade: Prioridade | None = None,
                      descricao: str | None = None) -> dict:
        """Altera campos de uma tarefa. Envie só o que muda; prazo '' remove o prazo."""
        return T().editar(id, titulo, responsavel, prazo, prioridade, descricao)

    @mcp.tool(annotations=ESCRITA)
    def anotar_tarefa(id: str, texto: str) -> dict:
        """Adiciona uma anotação ao histórico da tarefa."""
        return T().anotar(id, texto)

    return mcp


def main():
    criar_servidor().run("stdio")
