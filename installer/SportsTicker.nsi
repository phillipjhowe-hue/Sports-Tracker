; Sports Ticker — Windows installer (NSIS 3, Modern UI 2)
; Build:  makensis -DVERSION=2.7.0 installer\SportsTicker.nsi
; Installs per user (no administrator rights needed), offers a desktop icon,
; Start menu shortcuts and "start with Windows", makes sure Python is present,
; and registers an uninstaller in Settings > Apps.

Unicode true
SetCompressor /SOLID lzma

!ifndef VERSION
  !define VERSION "0.0.0"
!endif
!define APPNAME   "Sports Ticker"
!define APPKEY    "SportsTicker"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPKEY}"

Name "${APPNAME}"
Caption "${APPNAME} ${VERSION} Setup"
BrandingText "${APPNAME} ${VERSION}"
OutFile "..\SportsTicker_Setup.exe"
InstallDir "$LOCALAPPDATA\Programs\Sports Ticker"
InstallDirRegKey HKCU "Software\${APPKEY}" "InstallDir"
RequestExecutionLevel user
ShowInstDetails show

VIProductVersion "${VERSION}.0"
VIAddVersionKey "ProductName" "${APPNAME}"
VIAddVersionKey "FileDescription" "${APPNAME} installer"
VIAddVersionKey "ProductVersion" "${VERSION}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "LegalCopyright" "Sports Ticker"

!include "MUI2.nsh"
!include "LogicLib.nsh"

!define MUI_ICON   "..\sports_ticker.ico"
!define MUI_UNICON "..\sports_ticker.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP   "welcome.bmp"
!define MUI_UNWELCOMEFINISHPAGE_BITMAP "welcome.bmp"
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_RIGHT
!define MUI_HEADERIMAGE_BITMAP "header.bmp"
!define MUI_ABORTWARNING

!define MUI_WELCOMEPAGE_TITLE "Welcome to ${APPNAME} ${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This will install ${APPNAME}: live scores for the NHL, NFL, MLB, NBA, Bundesliga and F1 in a bar along the edge of your screen, with full stats, standings and highlights for every game.$\r$\n$\r$\nIf you already have ${APPNAME}, this updates it and keeps your settings.$\r$\n$\r$\nClick Next to continue."
!insertmacro MUI_PAGE_WELCOME

!define MUI_COMPONENTSPAGE_TEXT_TOP "Choose the shortcuts you want. You can change these later by running Setup again."
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES

!define MUI_FINISHPAGE_TITLE "${APPNAME} is installed"
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_TEXT "Start ${APPNAME} now"
!define MUI_FINISHPAGE_RUN_FUNCTION LaunchApp
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Var PYW        ; pyw.exe / pythonw.exe used to start the ticker without a console

; ------------------------------------------------------------- Python ----
!macro _TryDir BASE
  ${If} $PYW == ""
    FindFirst $0 $1 "${BASE}\Python3*"
    ${DoWhile} $1 != ""
      ${If} ${FileExists} "${BASE}\$1\pythonw.exe"
        StrCpy $PYW "${BASE}\$1\pythonw.exe"
        ${Break}
      ${EndIf}
      FindNext $0 $1
    ${Loop}
    FindClose $0
  ${EndIf}
!macroend

Function FindPython
  StrCpy $PYW ""
  ${If} ${FileExists} "$LOCALAPPDATA\Programs\Python\Launcher\pyw.exe"
    StrCpy $PYW "$LOCALAPPDATA\Programs\Python\Launcher\pyw.exe"
  ${ElseIf} ${FileExists} "$WINDIR\pyw.exe"
    StrCpy $PYW "$WINDIR\pyw.exe"
  ${EndIf}
  !insertmacro _TryDir "$LOCALAPPDATA\Programs\Python"
  !insertmacro _TryDir "$PROGRAMFILES64"
  !insertmacro _TryDir "$PROGRAMFILES"
  ${If} $PYW == ""
  ${AndIf} ${FileExists} "$LOCALAPPDATA\Microsoft\WindowsApps\pythonw.exe"
    StrCpy $PYW "$LOCALAPPDATA\Microsoft\WindowsApps\pythonw.exe"   ; Microsoft Store Python
  ${EndIf}
FunctionEnd

Function EnsurePython
  Call FindPython
  ${If} $PYW != ""
    DetailPrint "Found Python: $PYW"
    Return
  ${EndIf}
  MessageBox MB_YESNO|MB_ICONQUESTION "${APPNAME} needs Python (free, from python.org), and it isn't installed on this PC yet.$\r$\n$\r$\nInstall it now? It takes about a minute and doesn't need administrator rights." IDNO manual
  DetailPrint "Installing Python with the Windows app installer (winget)..."
  ${If} ${FileExists} "$LOCALAPPDATA\Microsoft\WindowsApps\winget.exe"
    nsExec::ExecToLog '"$LOCALAPPDATA\Microsoft\WindowsApps\winget.exe" install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements'
  ${Else}
    nsExec::ExecToLog 'cmd /c winget install -e --id Python.Python.3.13 --scope user --silent --accept-package-agreements --accept-source-agreements'
  ${EndIf}
  Pop $0
  Call FindPython
  ${If} $PYW != ""
    DetailPrint "Python installed: $PYW"
    Return
  ${EndIf}
  manual:
  MessageBox MB_OK|MB_ICONINFORMATION "Python couldn't be installed automatically. Setup will open the python.org download page.$\r$\n$\r$\nInstall Python from there (tick $\"Add python.exe to PATH$\"), then start ${APPNAME} from its shortcut."
  ExecShell "open" "https://www.python.org/downloads/"
FunctionEnd

; Shortcut that starts the ticker with no console window. Falls back to the
; batch launcher (which finds or installs Python itself) if Python isn't found.
!macro MakeShortcut LNK
  SetOutPath "$INSTDIR"
  ${If} $PYW != ""
    CreateShortcut "${LNK}" "$PYW" '"$INSTDIR\sports_ticker.pyw"' "$INSTDIR\sports_ticker.ico" 0 SW_SHOWNORMAL "" "Live sports scores ticker"
  ${Else}
    CreateShortcut "${LNK}" "$INSTDIR\Start Sports Ticker.bat" "" "$INSTDIR\sports_ticker.ico" 0 SW_SHOWMINIMIZED "" "Live sports scores ticker"
  ${EndIf}
!macroend

Function LaunchApp
  ${If} $PYW != ""
    Exec '"$PYW" "$INSTDIR\sports_ticker.pyw"'
  ${Else}
    ExecShell "open" "$INSTDIR\Start Sports Ticker.bat" "" SW_SHOWMINIMIZED
  ${EndIf}
FunctionEnd

; ------------------------------------------------------------ sections ----
Section "${APPNAME} (required)" SecMain
  SectionIn RO
  SetOutPath "$INSTDIR"
  File "..\sports_ticker.pyw"
  File "..\sports_ticker.ico"
  File "..\Start Sports Ticker.bat"
  File "..\README.md"
  File "..\CHANGELOG.md"

  ; Remove shortcuts from a previous install so unticked options really go away.
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMSTARTUP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"

  Call EnsurePython

  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\${APPKEY}" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayName" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKCU "${UNINSTKEY}" "Publisher" "${APPNAME}"
  WriteRegStr HKCU "${UNINSTKEY}" "DisplayIcon" "$INSTDIR\sports_ticker.ico"
  WriteRegStr HKCU "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "NoRepair" 1
  WriteRegDWORD HKCU "${UNINSTKEY}" "EstimatedSize" 400
SectionEnd

Section "Desktop icon" SecDesktop
  !insertmacro MakeShortcut "$DESKTOP\${APPNAME}.lnk"
SectionEnd

Section "Start menu shortcuts" SecStartMenu
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  !insertmacro MakeShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"
SectionEnd

Section /o "Start ${APPNAME} when Windows starts" SecStartup
  !insertmacro MakeShortcut "$SMSTARTUP\${APPNAME}.lnk"
SectionEnd

!insertmacro MUI_FUNCTION_DESCRIPTION_BEGIN
  !insertmacro MUI_DESCRIPTION_TEXT ${SecMain}      "The ticker itself. Also checks for Python and offers to install it if it's missing."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecDesktop}   "Put a ${APPNAME} icon on your desktop."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartMenu} "Add ${APPNAME} and its uninstaller to the Start menu."
  !insertmacro MUI_DESCRIPTION_TEXT ${SecStartup}   "Start the ticker automatically every time you sign in to Windows."
!insertmacro MUI_FUNCTION_DESCRIPTION_END

; ----------------------------------------------------------- uninstall ----
Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  Delete "$SMSTARTUP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  Delete "$INSTDIR\sports_ticker.pyw"
  Delete "$INSTDIR\sports_ticker.ico"
  Delete "$INSTDIR\Start Sports Ticker.bat"
  Delete "$INSTDIR\README.md"
  Delete "$INSTDIR\CHANGELOG.md"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir /r "$INSTDIR\__pycache__"
  RMDir "$INSTDIR"
  DeleteRegKey HKCU "${UNINSTKEY}"
  DeleteRegKey HKCU "Software\${APPKEY}"
  MessageBox MB_YESNO|MB_ICONQUESTION "Also delete your ${APPNAME} settings and downloaded team logos?" IDNO keep
    RMDir /r "$APPDATA\SportsTicker"
  keep:
SectionEnd
