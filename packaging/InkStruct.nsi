Unicode true
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
VIAddVersionKey "ProductName" "InkStruct"
VIAddVersionKey "FileDescription" "InkStruct Windows x64 Installer"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

Var Isolated

Function .onInit
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP "InkStruct requires 64-bit Windows."
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
