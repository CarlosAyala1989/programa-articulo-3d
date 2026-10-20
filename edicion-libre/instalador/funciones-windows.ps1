# Funciones compatibles con Windows PowerShell 5.1; no ejecutan comandos al cargarse.
function Limpiar-Texto([string]$Texto) {
    return $Texto.Replace([string][char]0, '')
}

function Guardar-Json([string]$Ruta, $Datos) {
    $Temporal = $Ruta + '.tmp'
    $Texto = $Datos | ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText($Temporal, $Texto, (New-Object Text.UTF8Encoding($false)))
    Move-Item -Force -LiteralPath $Temporal -Destination $Ruta
}

function Invocar-Nativo([string]$Ejecutable, [string[]]$Argumentos, [switch]$Mostrar) {
    # Los avisos de stderr no deben convertirse en excepciones antes de leer el código.
    $Anterior = $ErrorActionPreference
    $Lineas = New-Object 'Collections.Generic.List[string]'
    try {
        $ErrorActionPreference = 'Continue'
        & $Ejecutable @Argumentos 2>&1 | ForEach-Object {
            $Texto = Limpiar-Texto ([string]$_)
            $Lineas.Add($Texto)
            if ($Mostrar) { Write-Host $Texto }
        }
        $Codigo = $LASTEXITCODE
    } finally { $ErrorActionPreference = $Anterior }
    if ($null -eq $Codigo) { throw ('No se pudo ejecutar: ' + $Ejecutable) }
    return [PSCustomObject]@{Codigo=$Codigo; Texto=($Lineas -join "`n")}
}

function Ejecutar-Nativo([string]$Ejecutable, [string[]]$Argumentos, [string]$Etapa) {
    $Resultado = Invocar-Nativo -Ejecutable $Ejecutable -Argumentos $Argumentos -Mostrar
    if ($Resultado.Codigo -ne 0) {
        throw ($Etapa + '. Codigo: ' + $Resultado.Codigo + "`n" + $Resultado.Texto)
    }
}

function Comprobar-MotorDocker($Informacion) {
    if ($Informacion.OSType -ne 'linux') {
        throw 'Docker esta en modo Windows containers. En Docker Desktop selecciona Switch to Linux containers.'
    }
    if ($Informacion.KernelVersion -match '(?i)microsoft|wsl') {
        throw 'Docker Desktop esta usando WSL 2. Para esta edicion sin WSL usa Hyper-V: Settings > General > desmarca Use the WSL 2 based engine y aplica los cambios. Hyper-V requiere Windows Pro, Enterprise o Education y virtualizacion habilitada.'
    }
    if ($Informacion.OperatingSystem -notmatch 'Docker Desktop') {
        throw 'Se requiere el motor local de Docker Desktop para Windows; no se usara un servidor Docker remoto.'
    }
}

function Descargar-Modelo($Modelo, [string]$Destino, [string]$Curl) {
    if (Test-Path -LiteralPath $Destino) {
        if ((Get-Item -LiteralPath $Destino).Length -eq $Modelo.bytes -and
            (Get-FileHash -LiteralPath $Destino -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Modelo.sha256) {
            return
        }
        Remove-Item -Force -LiteralPath $Destino
    }
    $Parcial = $Destino + '.parcial'
    if ((Test-Path -LiteralPath $Parcial) -and (Get-Item -LiteralPath $Parcial).Length -ge $Modelo.bytes) {
        if ((Get-Item -LiteralPath $Parcial).Length -eq $Modelo.bytes -and
            (Get-FileHash -LiteralPath $Parcial -Algorithm SHA256).Hash.ToLowerInvariant() -eq $Modelo.sha256) {
            Move-Item -Force -LiteralPath $Parcial -Destination $Destino
            return
        }
        Remove-Item -Force -LiteralPath $Parcial
    }
    Write-Host ('Descargando ' + $Modelo.nombre + '. Puedes reabrir el acceso directo para reanudar.')
    Ejecutar-Nativo -Ejecutable $Curl -Argumentos @('--fail','--location','--retry','5','--retry-delay','3',
        '--connect-timeout','30','--continue-at','-','--output',$Parcial,$Modelo.url) -Etapa ('Descarga de ' + $Modelo.nombre)
    if ((Get-Item -LiteralPath $Parcial).Length -ne $Modelo.bytes -or
        (Get-FileHash -LiteralPath $Parcial -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Modelo.sha256) {
        Remove-Item -Force -LiteralPath $Parcial
        throw ('Tamano o SHA-256 incorrecto: ' + $Modelo.nombre + '. Vuelve a abrir para descargar de nuevo.')
    }
    Move-Item -Force -LiteralPath $Parcial -Destination $Destino
}

function Consultar-ModelosOllama {
    return @( (Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/tags' -TimeoutSec 15).models )
}

function Preparar-ModelosWindows([string]$Programa, [string]$Descargas, [string]$Ollama, [string]$Curl) {
    $Activos = Join-Path $Programa 'datos/modelos_libres'
    $Manifiesto = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Activos 'modelos.json') | ConvertFrom-Json
    if (@($Manifiesto.modelos).Count -ne 5) { throw 'El paquete debe contener exactamente cinco modelos fijados.' }
    $RegistroModelos = Join-Path $Programa 'modelos_instalados.json'
    $Instalado = $null
    if (Test-Path -LiteralPath $RegistroModelos) {
        try { $Instalado = Get-Content -Raw -Encoding UTF8 -LiteralPath $RegistroModelos | ConvertFrom-Json } catch {}
    }
    New-Item -ItemType Directory -Force -Path $Descargas | Out-Null
    # Conservar el registro anterior permite reanudar sin perder modelos ya importados.
    $Resultado = @{version=$Manifiesto.version; estado='descargando'; contexto=$Manifiesto.contexto; modelos=@{}}
    if ($Instalado -and $Instalado.modelos) {
        foreach ($Propiedad in $Instalado.modelos.PSObject.Properties) { $Resultado.modelos[$Propiedad.Name] = $Propiedad.Value }
    }
    Guardar-Json $RegistroModelos $Resultado
    foreach ($Modelo in $Manifiesto.modelos) {
        Write-Host ('Preparando ' + $Modelo.nombre + ' / ' + $Modelo.cuantizacion)
        $Actual = @(Consultar-ModelosOllama | Where-Object { $_.name -eq $Modelo.etiqueta }) | Select-Object -First 1
        $Anterior = $Resultado.modelos[$Modelo.codigo]
        if ($Anterior -and $Actual -and $Anterior.sha256 -eq $Modelo.sha256 -and
            $Anterior.etiqueta -eq $Modelo.etiqueta -and $Anterior.digest -eq $Actual.digest -and
            $Actual.details.quantization_level -eq $Modelo.cuantizacion) { continue }
        $Plantilla = Join-Path $Activos $Modelo.plantilla
        $Licencia = Join-Path $Activos $Modelo.licencia_archivo
        if ((Get-FileHash -LiteralPath $Plantilla -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Modelo.plantilla_sha256 -or
            (Get-FileHash -LiteralPath $Licencia -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Modelo.licencia_sha256) {
            throw ('La plantilla o licencia no coincide con el paquete: ' + $Modelo.nombre)
        }
        $Peso = Join-Path $Descargas ($Modelo.codigo + '.gguf')
        Descargar-Modelo -Modelo $Modelo -Destino $Peso -Curl $Curl
        $Entrada = [IO.File]::OpenRead($Peso)
        try {
            $Cabecera = New-Object byte[] 4
            if ($Entrada.Read($Cabecera, 0, 4) -ne 4 -or [Text.Encoding]::ASCII.GetString($Cabecera) -ne 'GGUF') {
                throw ('El archivo no es GGUF: ' + $Modelo.nombre)
            }
        } finally { $Entrada.Dispose() }
        # Ruta relativa al Modelfile: evita escapes de las barras de Windows y espacios.
        $Texto = 'FROM ./' + $Modelo.codigo + '.gguf' + "`n" +
            'TEMPLATE """' + [IO.File]::ReadAllText($Plantilla) + '"""' + "`n" +
            'LICENSE """' + [IO.File]::ReadAllText($Licencia) + '"""' + "`n" +
            'PARAMETER num_ctx ' + $Manifiesto.contexto + "`n" +
            "PARAMETER temperature 0.2`nPARAMETER top_p 0.9`nPARAMETER repeat_penalty 1.05`n"
        foreach ($Parada in $Modelo.paradas) { $Texto += 'PARAMETER stop ' + (ConvertTo-Json -Compress -InputObject $Parada) + "`n" }
        $ArchivoModelo = Join-Path $Descargas ($Modelo.codigo + '.Modelfile')
        [IO.File]::WriteAllText($ArchivoModelo, $Texto, (New-Object Text.UTF8Encoding($false)))
        $HostAnterior = $env:OLLAMA_HOST
        try {
            $env:OLLAMA_HOST = 'http://127.0.0.1:11434'
            Ejecutar-Nativo -Ejecutable $Ollama -Argumentos @('create',$Modelo.etiqueta,'-f',$ArchivoModelo) -Etapa ('Importacion de ' + $Modelo.nombre)
        } finally { $env:OLLAMA_HOST = $HostAnterior }
        $Actual = @(Consultar-ModelosOllama | Where-Object { $_.name -eq $Modelo.etiqueta }) | Select-Object -First 1
        if (-not $Actual -or $Actual.details.quantization_level -ne $Modelo.cuantizacion -or $Actual.digest -notmatch '^[a-fA-F0-9]{64}$') {
            throw ('Ollama no confirmo la cuantizacion e identidad: ' + $Modelo.nombre + '. Actualiza Ollama para Windows y reabre el programa.')
        }
        $Ficha = @{}
        foreach ($Propiedad in $Modelo.PSObject.Properties) { $Ficha[$Propiedad.Name] = $Propiedad.Value }
        $Ficha.digest = $Actual.digest
        $Ficha.detalles = $Actual.details
        $Ficha.fecha_instalacion = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $Resultado.modelos[$Modelo.codigo] = $Ficha
        Guardar-Json $RegistroModelos $Resultado
        Remove-Item -Force -LiteralPath $Peso
    }
    $Resultado.estado = 'completo'
    Guardar-Json $RegistroModelos $Resultado
}
