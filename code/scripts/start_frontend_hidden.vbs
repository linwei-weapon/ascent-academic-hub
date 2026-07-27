Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
codeDir = fso.GetParentFolderName(scriptDir)
frontendDir = fso.BuildPath(codeDir, "frontend")
shell.CurrentDirectory = frontendDir
command = "cmd.exe /d /c ""npm.cmd run dev -- --host 127.0.0.1 --port 3006"""
shell.Run command, 0, False
