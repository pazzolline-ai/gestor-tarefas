@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Abrindo o PGMEI cliente por cliente. Resolva o "nao sou um robo" e gere o DAS: o robo salva o PDF sozinho.
.venv\Scripts\python -m dasmei assistido %*
pause
