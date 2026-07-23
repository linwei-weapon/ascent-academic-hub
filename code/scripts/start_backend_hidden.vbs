Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
codeDir = fso.GetParentFolderName(scriptDir)
pythonExe = "C:\Users\SW\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
shell.CurrentDirectory = codeDir
shell.Run """" & pythonExe & """ -X utf8 -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000", 0, False
