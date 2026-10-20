param(
    [ValidateSet('Preparar','Abrir','Detener')][string]$Modo = 'Preparar',
    [string]$DirectorioPrograma = ''
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Raiz = $PSScriptRoot
$Registro = Join-Path $Raiz 'ultimo-error.txt'
$Mutex = $null
$Bloqueado = $false
$Transcripcion = $false
$CodigoSalida = 0

try {
    . (Join-Path $Raiz 'funciones-windows.ps1')
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    [Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
    $OutputEncoding = [Console]::OutputEncoding
    $Logs = Join-Path $Raiz 'registros'
    $Descargas = Join-Path $Raiz 'descargas'
    New-Item -ItemType Directory -Force -Path $Logs,$Descargas | Out-Null
    $Registro = Join-Path $Logs ('preparacion-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')
    $Mutex = New-Object Threading.Mutex($false, 'Local\AgenteCielLibreWindowsInstalacion')
    $Bloqueado = $Mutex.WaitOne(0)
    if (-not $Bloqueado) { throw 'La preparacion de Agente Ciel Libre ya esta en curso.' }
    Start-Transcript -Path $Registro -Append | Out-Null
    $Transcripcion = $true
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'Esta edicion requiere Windows x64 con CPU Intel o AMD.'
    }
    $Windows = Get-CimInstance Win32_OperatingSystem
    if ([int]$Windows.BuildNumber -lt 19045) { throw 'Se requiere Windows 10 22H2 o Windows 11 actualizado y compatible con tu Docker Desktop.' }
    $Dependencias = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Raiz 'dependencias-windows.json') | ConvertFrom-Json
    $Programa = Join-Path $Raiz 'programa'
    if ($DirectorioPrograma) { $Programa = [IO.Path]::GetFullPath($DirectorioPrograma) }
    elseif (-not (Test-Path -LiteralPath (Join-Path $Raiz 'programa.zip'))) {
        $Programa = [IO.Path]::GetFullPath((Join-Path $Raiz '../programa'))
    }
    $ComandoDocker = Get-Command docker.exe -ErrorAction SilentlyContinue
    $Docker = if ($ComandoDocker) { $ComandoDocker.Source } else { Join-Path $env:ProgramFiles 'Docker/Docker/resources/bin/docker.exe' }
    if (-not (Test-Path -LiteralPath $Docker)) { throw 'No se encontro Docker Desktop para Windows. Instalalo y abrelo antes de continuar.' }
    # Contexto explícito local, sin cambiar el contexto global del usuario.
    $ContextoDocker = 'desktop-linux'
    $Contexto = Invocar-Nativo $Docker @('context','inspect',$ContextoDocker,'--format','{{.Endpoints.docker.Host}}')
    if ($Contexto.Codigo -ne 0) {
        $ContextoDocker = 'default'
        $Contexto = Invocar-Nativo $Docker @('context','inspect',$ContextoDocker,'--format','{{.Endpoints.docker.Host}}')
    }
    if ($Contexto.Codigo -ne 0 -or $Contexto.Texto.Trim() -notmatch '^npipe://') { throw 'No se encontro un contexto local de Docker Desktop. Abre Docker Desktop en modo Linux containers.' }
    $Info = Invocar-Nativo $Docker @('--context',$ContextoDocker,'info','--format','{{json .}}')
    if ($Info.Codigo -ne 0) { throw ('Docker Desktop no esta listo. Abrelo y espera a que el motor este iniciado. Hyper-V requiere virtualizacion habilitada en BIOS.' + "`n" + $Info.Texto) }
    # Docker puede escribir avisos en stderr junto al JSON de stdout.
    $JsonDocker = @($Info.Texto -split "`n" | Where-Object { $_.Trim().StartsWith('{') }) | Select-Object -Last 1
    if (-not $JsonDocker) { throw ('Docker no devolvio informacion del motor.' + "`n" + $Info.Texto) }
    $Informacion = $JsonDocker | ConvertFrom-Json
    Comprobar-MotorDocker $Informacion
    Ejecutar-Nativo $Docker @('--context',$ContextoDocker,'compose','version') 'Docker Compose no esta disponible'
    $BaseCompose = @('--context',$ContextoDocker,'compose','--project-name',$Dependencias.proyecto,'--file',(Join-Path $Programa 'compose.yaml'))
    $ResultadosWindows = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'CielLibre/Resultados'
    $env:CIEL_DIRECTORIO_RESULTADOS = $ResultadosWindows.Replace('\','/')
    if ($Modo -eq 'Detener') {
        if (-not (Test-Path -LiteralPath (Join-Path $Programa 'compose.yaml'))) { throw 'No se encontro el programa instalado.' }
        Ejecutar-Nativo $Docker ($BaseCompose + @('stop')) 'No se pudieron detener los servicios de Agente Ciel'
    } else {
        if ([int64]$Windows.TotalVisibleMemorySize -lt (15GB / 1KB)) { throw 'Se requieren al menos 16 GB de RAM; se recomiendan 32 GB.' }
        if ([int64]$Informacion.MemTotal -lt 6GB) { throw 'Docker tiene poca RAM asignada. En Settings > Resources > Advanced asigna al menos 6 GB; se recomiendan 8 GB.' }
        $ComandoOllama = Get-Command ollama.exe -ErrorAction SilentlyContinue
        $Ollama = if ($ComandoOllama) { $ComandoOllama.Source } else { Join-Path $env:LOCALAPPDATA 'Programs/Ollama/ollama.exe' }
        if (-not (Test-Path -LiteralPath $Ollama)) { throw 'No se encontro Ollama para Windows. Instalalo y abrelo antes de continuar.' }
        try { Consultar-ModelosOllama | Out-Null } catch { throw 'Ollama para Windows no responde en http://127.0.0.1:11434. Abre Ollama desde Inicio. Esta edicion usa su puerto normal 11434.' }
        $EstadoArchivo = Join-Path $Raiz 'estado-windows.json'
        $Estado = $null
        if (Test-Path -LiteralPath $EstadoArchivo) {
            try { $Estado = Get-Content -Raw -Encoding UTF8 -LiteralPath $EstadoArchivo | ConvertFrom-Json } catch {}
        }
        $Disco = New-Object IO.DriveInfo([IO.Path]::GetPathRoot($Programa))
        $MinimoDisco = if ($Estado) { 10GB } else { 60GB }
        if ($Disco.AvailableFreeSpace -lt $MinimoDisco) { throw 'Espacio insuficiente: se necesitan 60 GB libres al preparar o 10 GB al reanudar. Comprueba tambien las unidades de Docker y Ollama.' }
        $PaqueteZip = Join-Path $Raiz 'programa.zip'
        if (Test-Path -LiteralPath $PaqueteZip) {
            $Paquete = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $Raiz 'paquete.json') | ConvertFrom-Json
            if ((Get-FileHash -LiteralPath $PaqueteZip -Algorithm SHA256).Hash.ToLowerInvariant() -ne $Paquete.sha256_programa) { throw 'El SHA-256 del programa no coincide. Vuelve a ejecutar el instalador original.' }
            # El paquete no contiene el registro de modelos ni los datos de campañas.
            Expand-Archive -LiteralPath $PaqueteZip -DestinationPath $Programa -Force
            $CodigoPrograma = $Paquete.origen.codigo_sha256
        } else {
            if (-not (Test-Path -LiteralPath (Join-Path $Programa 'compose.yaml'))) { throw 'No se encontro la carpeta del codigo del programa.' }
            $CodigoPrograma = 'codigo-local-' + (Get-Date -Format o)
        }
        New-Item -ItemType Directory -Force -Path $ResultadosWindows | Out-Null
        $Curl = Join-Path $env:SystemRoot 'System32/curl.exe'
        if (-not (Test-Path -LiteralPath $Curl)) { throw 'No se encontro curl.exe. Actualiza Windows y vuelve a abrir el programa.' }
        # Pausar al consumidor antes de actualizar el registro de modelos.
        $Servicios = Invocar-Nativo $Docker ($BaseCompose + @('ps','--all','--quiet','trabajador'))
        if ($Servicios.Codigo -eq 0 -and $Servicios.Texto.Trim()) { Ejecutar-Nativo $Docker ($BaseCompose + @('stop','trabajador')) 'No se pudo pausar el trabajador durante la preparacion' }
        Guardar-Json $EstadoArchivo @{etapa='preparando-modelos'; version=$Dependencias.version}
        Preparar-ModelosWindows -Programa $Programa -Descargas $Descargas -Ollama $Ollama -Curl $Curl
        $ImagenesPresentes = Invocar-Nativo $Docker @('--context',$ContextoDocker,'image','inspect',
            'ciel-libre-aplicacion:v1','ciel-libre-supervisor:v1','ciel-libre-evaluador:v1',
            'ciel-libre-cadquery:v1','ciel-libre-build123d:v1','ciel-libre-freecad:v1','--format','{{.Id}}')
        if (-not $Estado -or $Estado.codigo_sha256 -ne $CodigoPrograma -or $Estado.etapa -ne 'completo' -or $ImagenesPresentes.Codigo -ne 0) {
            Write-Host 'Construyendo la aplicacion y los tres motores CAD en Docker Desktop.'
            Guardar-Json $EstadoArchivo @{etapa='construyendo'; version=$Dependencias.version; codigo_sha256=$CodigoPrograma}
            Ejecutar-Nativo $Docker ($BaseCompose + @('--profile','imagenes','build')) 'No se pudieron construir los contenedores. Revisa el espacio de Docker y el acceso a Internet'
        }
        Ejecutar-Nativo $Docker ($BaseCompose + @('up','-d','--force-recreate','postgres','redis','evaluador','supervisor','api')) 'No se pudieron iniciar los servicios. Comparte programa y Documentos en Docker > Settings > Resources > File sharing'
        # Verificar desde el contenedor antes de iniciar el lote automático.
        $Comprobacion = @'
from aplicacion.proveedores import modelos_configurados, verificar_modelo_local
for modelo in modelos_configurados():
    verificar_modelo_local(modelo)
print('Cinco modelos de Ollama Windows disponibles desde Docker')
'@
        $Conexion = Invocar-Nativo $Docker ($BaseCompose + @('exec','-T','api','python','-c',$Comprobacion)) -Mostrar
        if ($Conexion.Codigo -ne 0) {
            throw ('Docker no pudo verificar los modelos de Ollama Windows. Si Ollama responde en Windows pero no desde Docker, configura la variable de usuario OLLAMA_HOST=0.0.0.0:11434, sal de Ollama y vuelve a abrirlo; permite la conexion privada de Docker en el firewall. No es necesario configurar OLLAMA_ORIGINS.' + "`n" + $Conexion.Texto)
        }
        $Url = 'http://127.0.0.1:' + $Dependencias.puerto
        $Disponible = $false
        for ($Intento=0; $Intento -lt 90; $Intento++) {
            try {
                $Respuesta = Invoke-RestMethod -Uri ($Url + '/api/opciones') -TimeoutSec 3
                if ($Respuesta.edicion -ne 'libre') { throw 'El puerto esta ocupado por otra aplicacion.' }
                $Disponible = $true
                break
            } catch { Start-Sleep -Seconds 2 }
        }
        if (-not $Disponible) { throw 'La interfaz no responde en http://127.0.0.1:8010. Consulta los registros de Docker en Diagnostico.' }
        Ejecutar-Nativo $Docker ($BaseCompose + @('up','-d','--force-recreate','trabajador')) 'No se pudo iniciar el trabajador'
        Guardar-Json $EstadoArchivo @{etapa='completo'; version=$Dependencias.version; codigo_sha256=$CodigoPrograma; proyecto=$Dependencias.proyecto; contexto=$ContextoDocker}
        $Inicio = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
        New-Item -Path $Inicio -Force | Out-Null
        Set-ItemProperty -Path $Inicio -Name 'AgenteCielLibre' -Value ('wscript.exe "' + (Join-Path $Raiz 'abrir.vbs') + '"')
        Remove-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce' -Name 'AgenteCielLibre' -ErrorAction SilentlyContinue
        Remove-Item -Force -LiteralPath (Join-Path $Raiz 'ultimo-error.txt') -ErrorAction SilentlyContinue
        Write-Host 'Agente Ciel listo: Docker Desktop y Ollama de Windows. Abriendo la interfaz.'
        Start-Process $Url
    }
} catch {
    $CodigoSalida = 1
    $Mensaje = ([string]$_.Exception.Message).Replace([string][char]0, '')
    [Console]::Error.WriteLine($Mensaje)
    if ($Docker -and $BaseCompose) {
        try {
            Write-Host 'Ultimos registros de los servicios de esta edicion:'
            Invocar-Nativo $Docker ($BaseCompose + @('logs','--no-color','--tail','40','api','evaluador','supervisor')) -Mostrar | Out-Null
        } catch {}
    }
    try { [IO.File]::WriteAllText((Join-Path $Raiz 'ultimo-error.txt'), ($Mensaje + "`r`nRegistro: " + $Registro), (New-Object Text.UTF8Encoding($false))) } catch {}
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [Windows.Forms.MessageBox]::Show(($Mensaje + "`r`n`r`nRegistro: " + $Registro), 'Agente Ciel Libre 0.3.0',
            [Windows.Forms.MessageBoxButtons]::OK, [Windows.Forms.MessageBoxIcon]::Error) | Out-Null
    } catch {}
} finally {
    if ($Transcripcion) { try { Stop-Transcript | Out-Null } catch {} }
    if ($Bloqueado) { $Mutex.ReleaseMutex() }
    if ($Mutex) { $Mutex.Dispose() }
}
exit $CodigoSalida
