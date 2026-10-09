@echo off
setlocal
if "%~1"=="--help" goto help
if "%~1"=="-h" goto help
for %%I in ("%~dp0.") do set "RIGEXEC_VIZ_ROOT=%%~fI"
set "RIGEXEC_VIZ_AUTOOPEN=1"
if not defined RIG for %%I in ("%~dp0..\usdRig") do set "RIG=%%~fI"
if not exist "%RIG%\bin\launch_usdview.bat" (
    echo usdRig launcher not found. Set RIG to your usdRig checkout. 1>&2
    exit /b 1
)
if "%~1"=="" (
    call "%RIG%\bin\launch_usdview.bat" "%RIG%\examples\biped\Biped_stack.usda"
) else (
    call "%RIG%\bin\launch_usdview.bat" %*
)
exit /b %errorlevel%

:help
echo Usage: launch_usdview.bat [stage.usda] [usdview options]
echo With no arguments, opens the biped with Live Graph and Threads.
echo Set RIG to use another usdRig checkout; USD and PY override dependencies.
echo Set RIGEXEC_VIZ_RIG to select a specific rig prim path.
exit /b 0
