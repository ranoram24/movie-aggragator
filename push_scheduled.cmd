@echo off
REM Scheduled wrapper around push_local.py.
REM
REM Exists mainly to pin the working directory: push_local.py loads .env from
REM the current directory, and Task Scheduler starts tasks in system32 unless
REM told otherwise. Launched from there it would find no INGEST_TOKEN and fail
REM every run with nothing obvious to point at.
REM
REM Output is appended to push.log so a failure that happens while nobody is
REM watching is still discoverable afterwards.

setlocal
set "PROJECT=%~dp0"
cd /d "%PROJECT%"

set "LOG=%PROJECT%push.log"

REM Keep the log from growing without bound: past ~1MB, start it again.
for %%A in ("%LOG%") do if %%~zA GTR 1000000 del "%LOG%"

echo. >> "%LOG%"
echo ======== %DATE% %TIME% ======== >> "%LOG%"

"%PROJECT%venv\Scripts\python.exe" "%PROJECT%push_local.py" >> "%LOG%" 2>&1
set "RC=%ERRORLEVEL%"

if "%RC%"=="0" (
  echo -- finished OK >> "%LOG%"
) else (
  echo -- FAILED with exit code %RC% >> "%LOG%"
)

endlocal & exit /b %RC%
