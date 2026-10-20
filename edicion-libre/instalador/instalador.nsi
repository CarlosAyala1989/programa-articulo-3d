Unicode true
!cd ".."
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
Name "Agente Ciel Libre"
OutFile "dist/Agente-Ciel-Libre-0.3.0-Setup.exe"
InstallDir "$LOCALAPPDATA\AgenteCielLibre"
RequestExecutionLevel user
SetCompressor /SOLID lzma
SetCompressorDictSize 32
ShowInstDetails show
!define MUI_ABORTWARNING
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "instalador/CONDICIONES.txt"
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "Spanish"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "Se necesita Windows de 64 bits con CPU Intel o AMD."
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd

Section "Aplicación libre"
  SetOutPath "$INSTDIR"
  File "dist/programa.zip"
  File "instalador/dependencias-windows.json"
  File "instalador/preparar-windows.ps1"
  File "instalador/funciones-windows.ps1"
  File "instalador/abrir.vbs"
  File "instalador/CONDICIONES.txt"
  File "dist/paquete.json"
  CreateDirectory "$SMPROGRAMS\Agente Ciel Libre"
  CreateShortcut "$SMPROGRAMS\Agente Ciel Libre\Agente Ciel Libre.lnk" "$WINDIR\System32\wscript.exe" '"$INSTDIR\abrir.vbs"'
  CreateShortcut "$DESKTOP\Agente Ciel Libre.lnk" "$WINDIR\System32\wscript.exe" '"$INSTDIR\abrir.vbs"'
  CreateShortcut "$SMPROGRAMS\Agente Ciel Libre\Detener servicios.lnk" "$WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe" '-NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\preparar-windows.ps1" -Modo Detener'
  CreateShortcut "$SMPROGRAMS\Agente Ciel Libre\Diagnóstico.lnk" "$WINDIR\explorer.exe" '"$INSTDIR\registros"'
  CreateDirectory "$DOCUMENTS\CielLibre\Resultados"
  CreateShortcut "$SMPROGRAMS\Agente Ciel Libre\Resultados.lnk" "$WINDIR\explorer.exe" '"$DOCUMENTS\CielLibre\Resultados"'
  WriteUninstaller "$INSTDIR\Desinstalar.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielLibre" "DisplayName" "Agente Ciel Libre"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielLibre" "DisplayVersion" "0.3.0"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielLibre" "UninstallString" '"$INSTDIR\Desinstalar.exe"'
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\RunOnce" "AgenteCielLibre"
  DetailPrint "Usando Docker Desktop y Ollama de Windows. La preparación se muestra en una ventana PowerShell."
  ; ExecWait evita capturar como ANSI la salida Unicode de PowerShell.
  ExecWait '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "$INSTDIR\preparar-windows.ps1" -Modo Preparar' $0
  ${If} $0 != "0"
    MessageBox MB_ICONEXCLAMATION "La preparación no terminó. Puedes reabrir el acceso directo para reanudar. Consulta Diagnóstico en el menú Inicio."
    SetErrorLevel 1
  ${EndIf}
SectionEnd

Section "Uninstall"
  SetRegView 64
  Delete "$DESKTOP\Agente Ciel Libre.lnk"
  RMDir /r "$SMPROGRAMS\Agente Ciel Libre"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AgenteCielLibre"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "AgenteCielLibre"
  DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\RunOnce" "AgenteCielLibre"
  ; Conservar modelos de Ollama, volúmenes Docker y resultados del usuario.
  MessageBox MB_ICONINFORMATION "Se retiraron los accesos directos. Se conservan los modelos de Ollama Windows, los volúmenes Docker, los resultados y los registros."
  Delete "$INSTDIR\Desinstalar.exe"
SectionEnd
