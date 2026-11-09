param([ValidateSet('Preparar','Abrir')][string]$Modo = 'Preparar')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Origen = $PSScriptRoot
$Raiz = Join-Path $env:LOCALAPPDATA 'AgenteCielNativo'
$Registro = Join-Path $Raiz 'ultimo-error.txt'
$Transcripcion = $false
$Mutex = $null
$Bloqueado = $false
$CodigoSalida = 0
try {
    if ($env:OS -ne 'Windows_NT') { throw 'Esta preparacion solo se permite en Windows. No ejecuta el lote en Ubuntu.' }
    . (Join-Path $Origen 'funciones.ps1')
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { throw 'Se requiere Windows x64 con procesador Intel o AMD.' }
    New-Item -ItemType Directory -Force -Path $Raiz,(Join-Path $Raiz 'registros'),(Join-Path $Raiz 'descargas') | Out-Null
    $Mutex = New-Object Threading.Mutex($false, 'Local\AgenteCielNativoPreparacion')
    $Bloqueado = $Mutex.WaitOne(0)
    if (-not $Bloqueado) {
        if ($Modo -eq 'Preparar') { throw 'Hay otra ventana de Agente Ciel abierta. Cierra la aplicacion y su ventana de preparacion antes de actualizar; despues vuelve a ejecutar el instalador.' }
        Start-Process 'http://127.0.0.1:8020'
        exit 0
    }
    $Registro = Join-Path $Raiz ('registros/preparacion-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    Start-Transcript -Path $Registro -Append | Out-Null
    $Transcripcion = $true
    $Windows = Get-CimInstance Win32_OperatingSystem
    if ([int]$Windows.BuildNumber -lt 19045) { throw 'Se requiere Windows 10 22H2 o Windows 11 x64.' }
    if ([int64]$Windows.TotalVisibleMemorySize -lt (15GB / 1KB)) { throw 'Estos perfiles necesitan al menos 16 GB de RAM; se recomiendan 32 GB.' }
    try { $Activo = Invoke-RestMethod 'http://127.0.0.1:8020/api/opciones' -TimeoutSec 2 } catch { $Activo = $null }
    if ($Modo -eq 'Abrir' -and $Activo -and $Activo.version_protocolo -eq 'ciel-nativo-windows-manual-v1') {
        Start-Process 'http://127.0.0.1:8020'
        exit 0
    }
    if ($Activo -and $Activo.ejecucion_nativa) {
        throw 'Cierra la ventana de la versión anterior de Agente Ciel Nativo antes de actualizar. Sus resultados quedan guardados; despues vuelve a ejecutar este instalador.'
    }
    $Programa = Join-Path $Raiz 'programa'
    if (Test-Path -LiteralPath (Join-Path $Origen 'programa.zip')) {
        $Paquete = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Origen 'paquete.json') | ConvertFrom-Json
        if ((Get-FileHash -LiteralPath (Join-Path $Origen 'programa.zip')).Hash.ToLowerInvariant() -ne $Paquete.sha256_programa) { throw 'El paquete del programa no coincide con su SHA-256.' }
        Expand-Archive -Force -LiteralPath (Join-Path $Origen 'programa.zip') -DestinationPath $Programa
    } else { $Programa = [IO.Path]::GetFullPath((Join-Path $Origen '../programa')) }
    Write-Host 'Los modelos de Ollama se detectaran al abrir la interfaz; podras elegirlos antes de ejecutar.'
    $Disco = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Raiz))
    $EspacioNecesario = 15GB
    $EntornosPreparados = $true
    foreach ($NombreEntorno in @('api','cadquery','build123d')) {
        $DirectorioEntorno = Join-Path $Raiz ('entornos/' + $NombreEntorno)
        if (-not (Test-Path -LiteralPath (Join-Path $DirectorioEntorno 'Scripts/python.exe')) -or
            -not (Test-Path -LiteralPath (Join-Path $DirectorioEntorno 'requisitos.sha256'))) { $EntornosPreparados = $false }
    }
    if ($EntornosPreparados) { $EspacioNecesario = 3GB }
    if ($Disco.AvailableFreeSpace -lt $EspacioNecesario) {
        throw ('Se necesitan al menos ' + ($EspacioNecesario / 1GB) + ' GB libres para completar la preparacion nativa, ademas del espacio de resultados.')
    }
    $Dependencias = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Origen 'dependencias.json') | ConvertFrom-Json
    $Descargas = Join-Path $Raiz 'descargas'
    $PythonBase = Join-Path $Raiz 'python311/python.exe'
    if (-not (Test-Path -LiteralPath $PythonBase)) {
        # Reutilizar una instalación 3.11 x64 evita entrar en mantenimiento del instalador.
        foreach ($Clave in @('HKCU:\Software\Python\PythonCore\3.11\InstallPath', 'HKLM:\Software\Python\PythonCore\3.11\InstallPath')) {
            if (Test-Path $Clave) {
                $Instalado = Get-ItemProperty $Clave
                $Candidato = $Instalado.ExecutablePath
                if (-not $Candidato -and $Instalado.'(default)') { $Candidato = Join-Path $Instalado.'(default)' 'python.exe' }
                if ($Candidato -and (Test-Path -LiteralPath $Candidato)) { $PythonBase = $Candidato; break }
            }
        }
    }
    if (-not (Test-Path -LiteralPath $PythonBase)) {
        $InstaladorPython = Descargar-Verificado $Dependencias.python $Descargas
        if ((Get-AuthenticodeSignature -FilePath $InstaladorPython).Status -ne 'Valid') { throw 'No se pudo comprobar la firma del instalador oficial de Python.' }
        $Instalacion = Start-Process -FilePath $InstaladorPython -Wait -PassThru -ArgumentList @('/passive','InstallAllUsers=0',
            ('TargetDir="' + (Join-Path $Raiz 'python311') + '"'),'Include_launcher=0','Include_pip=1','Include_test=0','Include_doc=0',
            'Include_tcltk=0','Shortcuts=0','PrependPath=0','AssociateFiles=0')
        if ($Instalacion.ExitCode -notin @(0,3010) -or -not (Test-Path -LiteralPath $PythonBase)) { throw ('No se pudo preparar Python nativo. Codigo: ' + $Instalacion.ExitCode) }
    }
    Invocar-Nativo $PythonBase @('-I','-c','import sys, struct; assert sys.version_info[:2] == (3, 11) and struct.calcsize(chr(80)) == 8, (sys.version, struct.calcsize(chr(80)))')
    $PythonApi = Preparar-Entorno 'api' $PythonBase $Raiz $Origen
    Preparar-Entorno 'cadquery' $PythonBase $Raiz $Origen | Out-Null
    Preparar-Entorno 'build123d' $PythonBase $Raiz $Origen | Out-Null
    Preparar-Entorno 'metrologia' $PythonBase $Raiz $Origen | Out-Null
    $FreecadDir = Join-Path $Raiz 'freecad'
    $FreecadBin = Encontrar-FreecadBin $FreecadDir
    $ExtraccionCompleta = $false
    $MarcaFreecad = Join-Path $FreecadDir '.extraccion-completa.json'
    if (Test-Path -LiteralPath $MarcaFreecad) {
        try {
            $Extraido = Get-Content -Raw -Encoding UTF8 -LiteralPath $MarcaFreecad | ConvertFrom-Json
            $ExtraccionCompleta = $Extraido.extraccion_completa -and
                $Extraido.sha256_portable -eq $Dependencias.freecad.sha256 -and
                $Extraido.sha256_extractor -eq $Dependencias.extractor_7zip.sha256
        } catch { $ExtraccionCompleta = $false }
    }
    if (-not $ExtraccionCompleta -or -not $FreecadBin -or -not (Test-Path -LiteralPath (Join-Path $FreecadBin 'python.exe'))) {
        # Reutiliza la descarga verificada. Una carpeta parcial no cuenta como instalación completa.
        $Portable = Descargar-Verificado $Dependencias.freecad $Descargas
        $Extractor = Join-Path $Origen $Dependencias.extractor_7zip.archivo
        if (-not (Test-Path -LiteralPath $Extractor)) { throw 'Falta herramientas/7zr.exe. Ejecuta el instalador nativo 0.8.0 para completar la actualizacion.' }
        Invocar-Nativo $PythonApi @((Join-Path $Programa 'nativo/descomprimir_freecad.py'),'--archivo',$Portable,'--destino',$FreecadDir,
            '--extractor',$Extractor,'--sha256-portable',$Dependencias.freecad.sha256,'--sha256-extractor',$Dependencias.extractor_7zip.sha256)
        $FreecadBin = Encontrar-FreecadBin $FreecadDir
        if (-not $FreecadBin) { throw 'No se encontro una carpeta bin de FreeCAD con FreeCAD.exe y python.exe en el paquete portable.' }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FreecadBin 'python.exe') -PathType Leaf)) { throw ('Falta python.exe dentro de la carpeta bin seleccionada: ' + $FreecadBin) }
    Write-Host ('Directorio bin de FreeCAD seleccionado: ' + $FreecadBin)
    Invocar-Nativo $PythonApi @((Join-Path $Programa 'nativo/fijar_runtimes.py'),'--raiz',$Raiz,'--freecad-bin',$FreecadBin)
    $Resultados = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'CielLibre/Resultados'
    New-Item -ItemType Directory -Force -Path $Resultados | Out-Null
    Guardar-Json (Join-Path $Raiz 'instalacion.json') @{version=$Dependencias.version; programa=$Programa; resultados=$Resultados; freecad=$FreecadBin}
    $Inicio = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
    if (Test-Path $Inicio) { Remove-ItemProperty -Path $Inicio -Name 'AgenteCielNativo' -ErrorAction SilentlyContinue }
    Write-Host 'Preparacion nativa completa. Abriendo la interfaz para seleccionar una campana.'
    Write-Host ('Resultados: ' + $Resultados)
    Write-Host ('SQLite: ' + (Join-Path $Raiz 'datos/ciel.sqlite'))
    # El instalador termina; la aplicación mantiene su propia ventana y Job Objects.
    $ProcesoAplicacion = Start-Process -FilePath $PythonApi -WorkingDirectory $Programa -WindowStyle Normal -PassThru -ArgumentList @('-m','nativo.iniciar',
        '--raiz',('"' + $Raiz + '"'),'--resultados',('"' + $Resultados + '"'))
    $Disponible = $false
    $LimiteArranque = (Get-Date).AddMinutes(3)
    while ((Get-Date) -lt $LimiteArranque) {
        $ProcesoAplicacion.Refresh()
        if ($ProcesoAplicacion.HasExited) { throw 'La aplicacion termino durante el arranque. Consulta registros/aplicacion.log.' }
        try {
            $EstadoApi = Invoke-RestMethod 'http://127.0.0.1:8020/api/opciones' -TimeoutSec 2
            if ($EstadoApi.ejecucion_nativa -and $EstadoApi.version_protocolo -eq 'ciel-nativo-windows-manual-v1') { $Disponible = $true; break }
        } catch {}
        Start-Sleep -Seconds 1
    }
    if (-not $Disponible) { throw 'La aplicacion no respondio en el plazo de arranque. Consulta registros/aplicacion.log y los registros de servicios.' }
    Write-Host 'La aplicacion nativa responde en http://127.0.0.1:8020.'
} catch {
    $CodigoSalida = 1
    $Mensaje = ([string]$_.Exception.Message).Replace([string][char]0, '')
    [Console]::Error.WriteLine($Mensaje)
    try { [IO.File]::WriteAllText((Join-Path $Raiz 'ultimo-error.txt'), ($Mensaje + "`r`nRegistro: " + $Registro), (New-Object Text.UTF8Encoding($false))) } catch {}
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show(($Mensaje + "`r`nRegistro: " + $Registro), 'Agente Ciel Nativo 0.8.0') | Out-Null
    } catch {}
} finally {
    if ($Transcripcion) { try { Stop-Transcript | Out-Null } catch {} }
    if ($Bloqueado) { $Mutex.ReleaseMutex() }
    if ($Mutex) { $Mutex.Dispose() }
}
exit $CodigoSalida
