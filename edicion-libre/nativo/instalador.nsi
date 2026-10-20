Unicode true
!cd ".."
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
Name "Agente Ciel Nativo"
OutFile "dist-nativo/Agente-Ciel-Nativo-0.5.0-Setup.exe"
InstallDir "$LOCALAPPDATA\AgenteCielNativo"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
ShowInstDetails show
VIProductVersion "0.5.0.0"
VIAddVersionKey "ProductName" "Agente Ciel Nativo"
VIAddVersionKey "FileDescription" "Instalador Windows nativo de 1.350 ejecuciones"
VIAddVersionKey "FileVersion" "0.5.0"
VIAddVersionKey "LegalCopyright" "Proyecto Agente Ciel"
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "nativo/CONDICIONES.txt"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Se necesita Windows de 64 bits con procesador Intel o AMD."
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "Aplicación nativa"
  SetOutPath "$INSTDIR"
  File "dist-nativo/programa.zip"
  File "dist-nativo/paquete.json"
  File "nativo/dependencias.json"
  File "nativo/preparar.ps1"
  File "nativo/funciones.ps1"
  File "nativo/abrir.vbs"
  File "nativo/requirements-api.txt"
  File "nativo/requirements-cadquery.txt"
  File "nativo/requirements-build123d.txt"
  File "nativo/CONDICIONES.txt"
  File "nativo/README.md"
  SetOutPath "$INSTDIR\herramientas"
  File "nativo/herramientas/7zr.exe"
  File "nativo/herramientas/7zip-LICENSE.txt"
  File "nativo/herramientas/7zip-LGPL.txt"
  File "nativo/herramientas/ORIGEN.txt"
  SetOutPath "$INSTDIR"
  CreateDirectory "$SMPROGRAMS\Agente Ciel Nativo"
  CreateShortcut "$SMPROGRAMS\Agente Ciel Nativo\Agente Ciel Nativo.lnk" "$WINDIR\System32\wscript.exe" '"$INSTDIR\abrir.vbs"'
  CreateShortcut "$DESKTOP\Agente Ciel Nativo.lnk" "$WINDIR\System32\wscript.exe" '"$INSTDIR\abrir.vbs"'
  CreateShortcut "$SMPROGRAMS\Agente Ciel Nativo\Diagnóstico.lnk" "$WINDIR\explorer.exe" '"$INSTDIR\registros"'
  CreateShortcut "$SMPROGRAMS\Agente Ciel Nativo\Instrucciones.lnk" "$WINDIR\notepad.exe" '"$INSTDIR\README.md"'
  CreateDirectory "$DOCUMENTS\CielLibre\Resultados"
  CreateShortcut "$SMPROGRAMS\Agente Ciel Nativo\Resultados.lnk" "$WINDIR\explorer.exe" '"$DOCUMENTS\CielLibre\Resultados"'
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielNativo" "DisplayName" "Agente Ciel Nativo"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielNativo" "DisplayVersion" "0.5.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielNativo" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  DetailPrint "Preparando Python y motores CAD nativos. Ollama debe estar abierto con los cinco modelos instalados."
  ; ExecWait muestra Unicode directamente en PowerShell sin capturarlo como ANSI.
  ExecWait '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\preparar.ps1" -Modo Preparar' $0
  ${If} $0 != "0"
    MessageBox MB_ICONEXCLAMATION "La preparación no terminó. Abre el acceso directo para reanudar. El error completo está en $INSTDIR\ultimo-error.txt y los registros en $INSTDIR\registros."
    SetErrorLevel 1
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetRegView 64
  Delete "$DESKTOP\Agente Ciel Nativo.lnk"
  RMDir /r "$SMPROGRAMS\Agente Ciel Nativo"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielNativo"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AgenteCielNativo"
  ; Conservar toda la evidencia experimental y las dependencias nativas.
  MessageBox MB_ICONINFORMATION "Accesos directos retirados. Se conservan los modelos de Ollama, SQLite, resultados, bibliotecas y registros. Cierra la ventana de la aplicación para detener el lote."
  Delete "$INSTDIR\Desinstalar.exe"
SectionEnd
