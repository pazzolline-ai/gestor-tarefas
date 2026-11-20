@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   Central de DAS MEI - instalacao
echo ============================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python nao encontrado. Instale o Python 3.11 ou mais novo em https://www.python.org/downloads/
  echo e marque "Add python.exe to PATH". Depois rode este arquivo de novo.
  pause & exit /b 1
)
py -3 -c "import sys; sys.exit(0 if sys.version_info>=(3,11) else 1)"
if errorlevel 1 ( echo E preciso Python 3.11 ou mais novo. & pause & exit /b 1 )
if not exist .venv ( py -3 -m venv .venv || ( echo Falha ao criar o ambiente. & pause & exit /b 1 ) )
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || ( echo Falha ao instalar dependencias. & pause & exit /b 1 )
echo.
.venv\Scripts\python -m dasmei configurar || ( pause & exit /b 1 )
echo.
echo --- Testando conexoes ---
.venv\Scripts\python -m dasmei testar
if errorlevel 1 (
  echo.
  echo Algum teste falhou. Corrija e rode "instalar.bat" de novo. A tarefa automatica NAO foi criada.
  pause & exit /b 1
)
echo.
echo --- Protegendo a pasta dos documentos e criando a tarefa automatica ---
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0windows\registrar_tarefa.ps1" -Pasta "%~dp0"
if errorlevel 1 ( echo Falha ao criar a tarefa no Agendador do Windows. & pause & exit /b 1 )
echo.
echo Pronto! O robo inicia sozinho ao entrar no Windows e roda a rotina no horario configurado (padrao 07:00).
echo Versao separada: use o atalho "Central de DAS MEI" na area de trabalho.
echo Acompanhe pela tela "Central de DAS MEI" no Gestor de Tarefas.
pause
