# Pruebas sin descargas, inferencias ni cambios en Windows o Docker Desktop.
$ErrorActionPreference = 'Stop'
$Base = Split-Path $PSScriptRoot -Parent
. (Join-Path $Base 'instalador/funciones-windows.ps1')
$script:Pruebas = 0
function Afirmar($Condicion, [string]$Mensaje) {
    if (-not $Condicion) { throw $Mensaje }
}
function Probar([string]$Nombre, [scriptblock]$Accion) {
    & $Accion
    $script:Pruebas++
    Write-Host ('OK: ' + $Nombre)
}
function Exigir-Error([scriptblock]$Accion, [string]$Patron) {
    $Capturado = $null
    try { & $Accion } catch { $Capturado = $_.Exception.Message }
    Afirmar ($Capturado -and $Capturado -match $Patron) ('Se esperaba un error: ' + $Patron)
}
$Temporal = Join-Path ([IO.Path]::GetTempPath()) ('ciel prueba ' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $Temporal | Out-Null
try {
    Probar 'Los errores UTF-16 no se truncan a una letra' {
        $Texto = ([char[]]'Error completo' | ForEach-Object { [string]$_ + [char]0 }) -join ''
        Afirmar ((Limpiar-Texto $Texto) -eq 'Error completo') 'Se perdio el mensaje completo.'
    }
    Probar 'Docker Linux Hyper-V aceptado' {
        Comprobar-MotorDocker ([PSCustomObject]@{OSType='linux'; KernelVersion='6.10.14-linuxkit'; OperatingSystem='Docker Desktop'})
    }
    Probar 'Docker WSL rechazado con instrucciones de Hyper-V' {
        Exigir-Error { Comprobar-MotorDocker ([PSCustomObject]@{OSType='linux'; KernelVersion='6.6.87.2-microsoft-standard-WSL2'; OperatingSystem='Docker Desktop'}) } 'Hyper-V'
    }
    Probar 'Contenedores Windows rechazados' {
        Exigir-Error { Comprobar-MotorDocker ([PSCustomObject]@{OSType='windows'; KernelVersion='10.0'; OperatingSystem='Docker Desktop'}) } 'Linux containers'
    }
    Probar 'Motor remoto rechazado' {
        Exigir-Error { Comprobar-MotorDocker ([PSCustomObject]@{OSType='linux'; KernelVersion='6.8'; OperatingSystem='Ubuntu'}) } 'remoto'
    }
    Probar 'stderr y codigo nativo conservados, con ruta que contiene espacios' {
        $Ruta = Join-Path $Temporal 'respuesta nativa.ps1'
        [IO.File]::WriteAllText($Ruta, 'param([string]$Dato); [Console]::WriteLine($Dato); [Console]::Error.WriteLine("Error nativo completo"); exit 7')
        $MotorPs = (Get-Process -Id $PID).Path
        $Resultado = Invocar-Nativo $MotorPs @('-NoProfile','-File',$Ruta,'-Dato','argumento con espacios')
        Afirmar ($Resultado.Codigo -eq 7) 'Se perdio el codigo nativo.'
        Afirmar ($Resultado.Texto -match 'argumento con espacios' -and $Resultado.Texto -match 'Error nativo completo') 'Se perdieron argumentos o stderr.'
    }
    Probar 'Reanudacion de archivo completo evita volver a descargarlo' {
        $Peso = Join-Path $Temporal 'completo.gguf'
        [IO.File]::WriteAllBytes(($Peso + '.parcial'), [Text.Encoding]::ASCII.GetBytes('GGUF'))
        $Hash = (Get-FileHash -LiteralPath ($Peso + '.parcial')).Hash.ToLowerInvariant()
        function Ejecutar-Nativo { throw 'No debe descargar un archivo ya completo.' }
        Descargar-Modelo ([PSCustomObject]@{bytes=4; sha256=$Hash}) $Peso 'curl-simulado'
        Afirmar (Test-Path -LiteralPath $Peso) 'No se recupero el archivo completo.'
    }
    Probar 'SHA-256 incorrecto impide importar pesos' {
        $Peso = Join-Path $Temporal 'incorrecto.gguf'
        function Ejecutar-Nativo($Ejecutable, $Argumentos, $Etapa) {
            $Indice = [array]::IndexOf($Argumentos, '--output')
            [IO.File]::WriteAllBytes($Argumentos[$Indice + 1], [Text.Encoding]::ASCII.GetBytes('MALO'))
        }
        Exigir-Error { Descargar-Modelo ([PSCustomObject]@{nombre='modelo simulado'; bytes=4; sha256=('a' * 64); url='https://ejemplo.invalid'}) $Peso 'curl-simulado' } 'SHA-256'
        Afirmar (-not (Test-Path -LiteralPath ($Peso + '.parcial'))) 'No se elimino la descarga corrupta.'
    }
    Probar 'Importacion interrumpida se reanuda y conserva los cinco perfiles exactos' {
        $Programa = Join-Path $Temporal 'programa con espacios'
        $Activos = Join-Path $Programa 'datos/modelos_libres'
        New-Item -ItemType Directory -Force -Path $Activos | Out-Null
        $Manifiesto = Get-Content -Raw -LiteralPath (Join-Path $Base 'programa/datos/modelos_libres/modelos.json') | ConvertFrom-Json
        $HashPeso = $null
        $Descargas = Join-Path $Temporal 'descargas modelos'
        New-Item -ItemType Directory -Path $Descargas | Out-Null
        foreach ($Modelo in $Manifiesto.modelos) {
            foreach ($Nombre in @($Modelo.plantilla, $Modelo.licencia_archivo)) {
                Copy-Item -LiteralPath (Join-Path $Base ('programa/datos/modelos_libres/' + $Nombre)) -Destination $Activos
            }
            $Peso = Join-Path $Descargas ($Modelo.codigo + '.gguf')
            [IO.File]::WriteAllBytes($Peso, [Text.Encoding]::ASCII.GetBytes('GGUF'))
            $HashPeso = (Get-FileHash -LiteralPath $Peso).Hash.ToLowerInvariant()
            $Modelo.bytes = 4
            $Modelo.sha256 = $HashPeso
        }
        Guardar-Json (Join-Path $Activos 'modelos.json') $Manifiesto
        $EstadoSimulado = @{creados=(New-Object 'Collections.Generic.List[string]'); modelos=@{}; fallar=$true}
        function Consultar-ModelosOllama { return @($EstadoSimulado.modelos.Values) }
        function Ejecutar-Nativo($Ejecutable, $Argumentos, $Etapa) {
            Afirmar ($Argumentos[0] -eq 'create') 'No se permiten descargas de red en esta prueba.'
            $Modelo = @($Manifiesto.modelos | Where-Object { $_.etiqueta -eq $Argumentos[1] })[0]
            if ($Modelo.codigo -eq 'L03' -and $EstadoSimulado.fallar) { $EstadoSimulado.fallar = $false; throw 'Interrupcion simulada' }
            $Modelfile = [IO.File]::ReadAllText($Argumentos[3])
            Afirmar ($Modelfile.StartsWith('FROM ./' + $Modelo.codigo + '.gguf')) 'Ruta GGUF incompatible con espacios.'
            Afirmar ($Modelfile.Contains('PARAMETER num_ctx 16384')) 'Cambio el contexto del experimento.'
            $EstadoSimulado.creados.Add($Modelo.codigo)
            $EstadoSimulado.modelos[$Modelo.codigo] = [PSCustomObject]@{name=$Modelo.etiqueta; digest=('a' * 64); details=@{quantization_level=$Modelo.cuantizacion}}
        }
        Exigir-Error { Preparar-ModelosWindows $Programa $Descargas 'ollama-simulado' 'curl-simulado' } 'Interrupcion'
        $Parcial = Get-Content -Raw -LiteralPath (Join-Path $Programa 'modelos_instalados.json') | ConvertFrom-Json
        Afirmar ($Parcial.estado -eq 'descargando' -and $Parcial.modelos.L02.digest) 'Se perdio el checkpoint.'
        Preparar-ModelosWindows $Programa $Descargas 'ollama-simulado' 'curl-simulado'
        Preparar-ModelosWindows $Programa $Descargas 'ollama-simulado' 'curl-simulado'
        Afirmar (($EstadoSimulado.creados -join ',') -eq 'L01,L02,L03,L04,L05') 'Se importaron modelos duplicados.'
        $Completo = Get-Content -Raw -LiteralPath (Join-Path $Programa 'modelos_instalados.json') | ConvertFrom-Json
        Afirmar ($Completo.estado -eq 'completo' -and @($Completo.modelos.PSObject.Properties).Count -eq 5) 'Registro final incompleto.'
        Afirmar ($Completo.modelos.L04.cuantizacion -eq 'Q6_K' -and $Completo.modelos.L03.cuantizacion -eq 'Q5_K_M') 'Se cambiaron cuantizaciones.'
        Afirmar (-not (Get-ChildItem $Descargas -Filter '*.gguf')) 'Se conservaron copias duplicadas de los pesos.'
        # Cambiar la licencia debe impedir reparar una identidad manipulada.
        $EstadoSimulado.modelos['L01'].digest = 'b' * 64
        [IO.File]::WriteAllText((Join-Path $Activos $Manifiesto.modelos[0].licencia_archivo), 'licencia alterada')
        Exigir-Error { Preparar-ModelosWindows $Programa $Descargas 'ollama-simulado' 'curl-simulado' } 'licencia'
    }
    Write-Host ($script:Pruebas.ToString() + ' pruebas de instalador Windows correctas; sin red ni inferencias.')
} finally { Remove-Item -Recurse -Force -LiteralPath $Temporal }
