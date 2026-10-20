# Preparación nativa: ninguna función llama Docker, WSL ni proveedores de IA.
function Invocar-Nativo([string]$Ejecutable, [string[]]$Argumentos) {
    $Anterior = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & $Ejecutable @Argumentos 2>&1 | ForEach-Object {
            Write-Host ([string]$_).Replace([string][char]0, '')
        }
        $Codigo = $LASTEXITCODE
    } finally { $ErrorActionPreference = $Anterior }
    if ($null -eq $Codigo -or $Codigo -ne 0) { throw ('Fallo al ejecutar ' + $Ejecutable + '. Codigo: ' + $Codigo + '. Consulta el registro completo.') }
}

function Guardar-Json([string]$Ruta, $Datos) {
    [IO.File]::WriteAllText(($Ruta + '.tmp'), ($Datos | ConvertTo-Json -Depth 30), (New-Object Text.UTF8Encoding($false)))
    Move-Item -Force -LiteralPath ($Ruta + '.tmp') -Destination $Ruta
}

function Descargar-Verificado($Datos, [string]$Descargas) {
    $Destino = Join-Path $Descargas $Datos.archivo
    if ((Test-Path -LiteralPath $Destino) -and (Get-FileHash -LiteralPath $Destino -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Datos.sha256) { return $Destino }
    $Parcial = $Destino + '.parcial'
    if ((Test-Path -LiteralPath $Parcial) -and (Get-FileHash -LiteralPath $Parcial -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Datos.sha256) {
        Move-Item -Force -LiteralPath $Parcial -Destination $Destino
        return $Destino
    }
    if ($Datos.bytes -and (Test-Path -LiteralPath $Parcial) -and (Get-Item -LiteralPath $Parcial).Length -ge $Datos.bytes) {
        Remove-Item -Force -LiteralPath $Parcial
    }
    Write-Host ('Descargando dependencia nativa: ' + $Datos.archivo)
    $Curl = Join-Path $env:SystemRoot 'System32/curl.exe'
    Invocar-Nativo $Curl @('--fail','--location','--retry','5','--retry-delay','3','--connect-timeout','30','--continue-at','-','--output',$Parcial,$Datos.url)
    if ((Get-FileHash -LiteralPath $Parcial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Datos.sha256) {
        Remove-Item -Force -LiteralPath $Parcial
        throw ('SHA-256 incorrecto de ' + $Datos.archivo)
    }
    Move-Item -Force -LiteralPath $Parcial -Destination $Destino
    return $Destino
}

function Preparar-Entorno([string]$Nombre, [string]$PythonBase, [string]$Raiz, [string]$Recursos) {
    $Entorno = Join-Path $Raiz ('entornos/' + $Nombre)
    $Python = Join-Path $Entorno 'Scripts/python.exe'
    $Requisitos = Join-Path $Recursos ('requirements-' + $Nombre + '.txt')
    $Hash = (Get-FileHash -LiteralPath $Requisitos -Algorithm SHA256).Hash.ToLowerInvariant()
    $Marca = Join-Path $Entorno 'requisitos.sha256'
    if (-not (Test-Path -LiteralPath $Python)) { Invocar-Nativo $PythonBase @('-m','venv',$Entorno) }
    if (-not (Test-Path -LiteralPath $Marca) -or (Get-Content -Raw -LiteralPath $Marca).Trim() -ne $Hash) {
        Write-Host ('Instalando bibliotecas nativas de ' + $Nombre)
        Invocar-Nativo $Python @('-m','pip','install','--disable-pip-version-check','--only-binary=:all:','-r',$Requisitos)
        [IO.File]::WriteAllText($Marca, $Hash)
    }
    return $Python
}

# El portable puede incluir un lanzador FreeCAD.exe en la raíz, sin Python.
function Encontrar-FreecadBin([string]$Directorio) {
    if (-not (Test-Path -LiteralPath $Directorio)) { return $null }
    $Candidatos = Get-ChildItem -LiteralPath $Directorio -Filter 'FreeCAD.exe' -Recurse -File |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.Directory.FullName 'python.exe') -PathType Leaf } |
        Sort-Object FullName
    $Elegido = $Candidatos | Select-Object -First 1
    if ($Elegido) { return [IO.Path]::GetFullPath($Elegido.Directory.FullName) }
    return $null
}
