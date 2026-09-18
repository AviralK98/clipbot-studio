param([ValidateSet('backend','worker','frontend','check')][string]$Service='backend')
$ErrorActionPreference='Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
switch ($Service) {
 'backend' { & .\.venv\Scripts\python.exe -m uvicorn clipbot.api:app --host 127.0.0.1 --port 8000 }
 'worker' { & .\.venv\Scripts\python.exe -m clipbot.local_worker }
 'frontend' { Set-Location apps/frontend; npm.cmd run dev }
 'check' { & .\.venv\Scripts\python.exe -m pytest -q; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; & .\.venv\Scripts\python.exe -m ruff check apps/backend tests; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; Set-Location apps/frontend; npm.cmd run build }
}
