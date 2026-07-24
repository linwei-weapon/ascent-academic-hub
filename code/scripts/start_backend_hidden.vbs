Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
codeDir = fso.GetParentFolderName(scriptDir)
workspaceDir = fso.GetParentFolderName(codeDir)
pythonExe = "C:\Users\SW\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
logFile = fso.BuildPath(workspaceDir, "work\backend-hidden.log")
shell.CurrentDirectory = codeDir
command = "cmd.exe /d /c ""set PYTHONIOENCODING=utf-8&&" _
  & """" & pythonExe & """ -X utf8 -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000" _
  & " >> """ & logFile & """ 2>&1"""
shell.Run command, 0, False
