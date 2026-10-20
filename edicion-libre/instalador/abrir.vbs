Option Explicit
Dim sistema, archivos, carpeta, comando
Set sistema = CreateObject("WScript.Shell")
Set archivos = CreateObject("Scripting.FileSystemObject")
carpeta = archivos.GetParentFolderName(WScript.ScriptFullName)
comando = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File """ & carpeta & "\preparar-windows.ps1"" -Modo Abrir"
sistema.Run comando, 1, False
