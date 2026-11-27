# Gestor de Tarefas — Londe & Rodrigues

- Sistema: https://pazzolline-ai.github.io/gestor-tarefas/
- Programa para Windows: página **Releases** → `Gestor-de-Tarefas-Instalador.exe`

Os dados ficam no Supabase, protegidos por login e senha de cada pessoa. Este repositório contém só a tela.

## Ao publicar uma atualização
Adicione um item no início de `NOVIDADES` (index.html) com id novo, data e o que mudou. Os usuários veem essa lista ao abrir o sistema atualizado.

## App Android
O workflow "App para Android" gera `Gestor-de-Tarefas.apk` (página Releases, tag `app-android`).
Precisa de dois segredos no repositório (Settings → Secrets and variables → Actions):
`ANDROID_KEYSTORE` (chave em base64) e `ANDROID_KEY_PASS` (senha). Guarde a chave: sem ela o app não aceita atualizações.

## Central de DAS MEI (robô fiscal)
A pasta `central_das_mei/` contém o robô que roda no PC do escritório (Python + API oficial Integra Contador/SERPRO) e alimenta a tela **Fiscal › Central de DAS MEI**. Instalação e uso: `central_das_mei/README.md`. Essa pasta não é publicada no site.

## Servidor MCP (Claude)
A pasta `mcp_gestor/` deixa o Claude consultar e criar tarefas. Instalação: `mcp_gestor/README.md`. Essa pasta não é publicada no site.
