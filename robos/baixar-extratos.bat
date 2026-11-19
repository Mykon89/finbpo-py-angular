@echo off
REM Baixa os extratos de todas as seguradoras do config.json (use no Agendador de Tarefas do Windows).
cd /d "%~dp0"
node finbpo-robo.mjs todas >> perfis\robo.log 2>&1
