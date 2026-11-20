@echo off
chcp 65001 >nul
echo Removendo as tarefas automaticas da Central de DAS MEI (documentos e historico NAO sao apagados)...
powershell -NoProfile -Command "Unregister-ScheduledTask -TaskName 'Central de DAS MEI' -Confirm:$false -ErrorAction SilentlyContinue; Unregister-ScheduledTask -TaskName 'Central de DAS MEI - garantir' -Confirm:$false -ErrorAction SilentlyContinue"
echo Feito.
pause
