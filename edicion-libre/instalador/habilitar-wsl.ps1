# Esta parte requiere elevación de Windows; no modifica otras distribuciones WSL.
param([Parameter(Mandatory=$true)][string]$PaqueteMsi)
$ErrorActionPreference = 'Stop'
try {
    $identidad = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identidad)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Se necesita el permiso de administrador para habilitar WSL.'
    }
    if ((Get-AuthenticodeSignature -FilePath $PaqueteMsi).Status -ne 'Valid') {
        throw 'La firma del instalador Microsoft WSL no es válida.'
    }
    foreach ($funcion in @('Microsoft-Windows-Subsystem-Linux','VirtualMachinePlatform')) {
        $estado = Get-WindowsOptionalFeature -Online -FeatureName $funcion
        if ($estado.State -ne 'Enabled') {
            Enable-WindowsOptionalFeature -Online -FeatureName $funcion -All -NoRestart | Out-Null
        }
    }
    $proceso = Start-Process -FilePath "$env:SystemRoot\System32\msiexec.exe" -ArgumentList @('/i', ('"' + $PaqueteMsi + '"'), '/qn', '/norestart') -PassThru -Wait
    if ($proceso.ExitCode -notin @(0,3010)) { throw "La instalación WSL terminó con código $($proceso.ExitCode)." }
    exit 3010
} catch {
    Write-Error $_
    exit 1
}
