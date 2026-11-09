Unicode true
LoadLanguageFile "${NSISDIR}\Contrib\Language files\SimpChinese.nlf"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"

Name "InkStruct ${VERSION}"
OutFile "${INSTALLER}"
InstallDir "$LOCALAPPDATA\Programs\InkStruct"
RequestExecutionLevel user
SetCompressor /SOLID lzma
Icon "${APP_ICON}"
UninstallIcon "${APP_ICON}"
VIProductVersion "${VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "InkStruct"
VIAddVersionKey /LANG=2052 "FileDescription" "InkStruct Windows x64 安装程序"
VIAddVersionKey /LANG=2052 "FileVersion" "${VERSION}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${VERSION}"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Var Isolated

!define VC_RUNTIME_KEY "Software\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
!define VC_RUNTIME_URL "https://aka.ms/vc14/vc_redist.x64.exe"

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "InkStruct 需要 64 位 Windows。"
    Abort
  ${EndIf}
  SetShellVarContext current
  SetRegView 64
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/ISOLATED" $1
  ${IfNot} ${Errors}
    StrCpy $Isolated 1
  ${EndIf}
  ReadRegDWORD $0 HKLM "${VC_RUNTIME_KEY}" "Installed"
  ReadRegDWORD $1 HKLM "${VC_RUNTIME_KEY}" "Major"
  ReadRegDWORD $2 HKLM "${VC_RUNTIME_KEY}" "Minor"
  ${If} $0 == 1
  ${AndIf} $1 == 14
  ${AndIf} $2 >= 51
  ${AndIf} ${FileExists} "$WINDIR\Sysnative\msvcp140.dll"
  ${AndIf} ${FileExists} "$WINDIR\Sysnative\vcruntime140.dll"
  ${AndIf} ${FileExists} "$WINDIR\Sysnative\vcruntime140_1.dll"
    Return
  ${EndIf}

  IfSilent missing_runtime
  MessageBox MB_ICONEXCLAMATION|MB_YESNO "InkStruct 需要 Microsoft Visual C++ x64 运行库（14.51 或更新版本）。是否打开微软官方下载？运行库安装完成后，请重新运行 InkStruct 安装程序。" IDNO missing_runtime
  ExecShell "open" "${VC_RUNTIME_URL}"
missing_runtime:
  SetErrorLevel 10
  Quit
FunctionEnd

Function un.onInit
  SetShellVarContext current
  SetRegView 64
  ${GetParameters} $0
  ClearErrors
  ${GetOptions} $0 "/ISOLATED" $1
  ${IfNot} ${Errors}
    StrCpy $Isolated 1
  ${EndIf}
FunctionEnd

Section "InkStruct"
  SetOutPath "$INSTDIR"
  File /r "${PAYLOAD}\*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $Isolated != 1
    CreateShortCut "$SMPROGRAMS\InkStruct.lnk" "$INSTDIR\InkStruct.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct" "DisplayName" "InkStruct"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct" "DisplayVersion" "${VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct" "UninstallString" '"$INSTDIR\Uninstall.exe"'
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct" "NoRepair" 1
  ${EndIf}
SectionEnd

Section "Uninstall"
  !include "${REMOVE_FILES}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ${If} $Isolated != 1
    Delete "$SMPROGRAMS\InkStruct.lnk"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct"
  ${EndIf}
SectionEnd
