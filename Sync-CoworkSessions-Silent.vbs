' Sync-CoworkSessions-Silent.vbs
' Launches Sync-CoworkSessions.ps1 with no visible window.
' Used by the Scheduled Task to avoid console flash.

Dim shell, scriptDir, syncScript
Set shell = CreateObject("WScript.Shell")

' Resolve path relative to this .vbs file
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
syncScript = scriptDir & "\Sync-CoworkSessions.ps1"

' Run pwsh completely hidden (0 = hidden, False = don't wait)
shell.Run "pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & syncScript & """", 0, False
