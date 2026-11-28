Unicode true
LoadLanguageFile "${NSISDIR}\Contrib\Language files\SimpChinese.nlf"
!include "LogicLib.nsh"
!include "nsDialogs.nsh"
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
Page custom ShortcutPage ShortcutFinish
UninstPage uninstConfirm
UninstPage instfiles

Var Isolated
Var DesktopCheck
Var MenuCheck
Var DesktopDir
Var MenuDir

Function ShortcutPage
  nsDialogs::Create 1018
  Pop $0
  ${If} $0 == error
    Abort
  ${EndIf}
  ${NSD_CreateLabel} 0 0 100% 16u "安装完成。请选择从哪里打开 InkStruct。"
  Pop $0
  ${NSD_CreateCheckbox} 0 24u 100% 14u "添加桌面快捷方式"
  Pop $DesktopCheck
  ${NSD_Check} $DesktopCheck
  ${NSD_CreateCheckbox} 0 46u 100% 14u "添加到开始菜单"
  Pop $MenuCheck
  nsDialogs::Show
FunctionEnd

Function ShortcutFinish
  ${NSD_GetState} $DesktopCheck $0
  ${If} $0 == ${BST_CHECKED}
    CreateShortCut "$DesktopDir\InkStruct.lnk" "$INSTDIR\InkStruct.exe"
  ${EndIf}
  ${NSD_GetState} $MenuCheck $0
  ${If} $0 == ${BST_CHECKED}
    CreateShortCut "$MenuDir\InkStruct.lnk" "$INSTDIR\InkStruct.exe"
  ${EndIf}
FunctionEnd

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
  StrCpy $0 "$LOCALAPPDATA\InkStruct\workspace\fonts"
  StrCpy $DesktopDir "$DESKTOP"
  StrCpy $MenuDir "$SMPROGRAMS"
  ${If} $Isolated == 1
    StrCpy $0 "$INSTDIR\..\isolated-workspace\fonts"
    StrCpy $DesktopDir "$INSTDIR\..\isolated-desktop"
    StrCpy $MenuDir "$INSTDIR\..\isolated-menu"
    CreateDirectory "$DesktopDir"
    CreateDirectory "$MenuDir"
  ${EndIf}
  ExecWait '"$INSTDIR\InkStruct.exe" --install-reference-font "$0"' $1
  ${If} ${Errors}
  ${OrIf} $1 != 0
    DetailPrint "参考字体安装失败。"
    SetErrorLevel 11
    Abort "参考字体安装失败。"
  ${EndIf}
  IfSilent 0 +2
  CreateShortCut "$DesktopDir\InkStruct.lnk" "$INSTDIR\InkStruct.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  ${If} $Isolated != 1
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
    Delete "$DESKTOP\InkStruct.lnk"
    Delete "$SMPROGRAMS\InkStruct.lnk"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\InkStruct"
  ${EndIf}
SectionEnd
