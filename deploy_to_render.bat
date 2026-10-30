@echo off
title OptionMargin — One-Click Render Cloud Auto-Deployer
echo ============================================================================
echo   OptionMargin — Autonomous FAR 52.222-43 Engine
echo   One-Click Local Verification, Git Commit, GitHub Push ^& Render Cloud Setup
echo ============================================================================
echo.

cd /d "%~dp0"

python auto_deploy_render.py

echo.
echo If your browser opened Render Blueprints, simply select your 'option-margin'
echo repository and click 'Apply' — render.yaml will configure your Web Service
echo and Daily Hunter Cron Job automatically!
echo.
pause
