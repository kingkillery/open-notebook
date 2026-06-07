param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $CommandArgs
)

$ErrorActionPreference = 'Stop'
$ScriptPath = Join-Path $PSScriptRoot 'colab_compute.py'
python $ScriptPath @CommandArgs
exit $LASTEXITCODE
