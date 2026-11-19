@echo off
rem Build the native accelerator for the 32-bit embedded Python in runtime\.
rem Run this from a "x86 Native Tools Command Prompt for VS 2022" (or let the
rem script call vcvars for you).  Produces ..\frontier_native.pyd
setlocal

set PYBASE=%~dp0..\..
set PYINC=%PYBASE%\..\python\python38win32\include
set PYLIB=%PYBASE%\..\python\python38win32\libs

if "%VSCMD_ARG_TGT_ARCH%"=="" (
  set VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat
  if not exist "%VCVARS%" set VCVARS=%ProgramFiles%\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars32.bat
  call "%VCVARS%" >nul
)

cl /nologo /O2 /LD /EHsc /I"%PYINC%" "%~dp0frontier_native.cpp" ^
   /link /LIBPATH:"%PYLIB%" python38.lib /OUT:"%~dp0..\frontier_native.pyd" || exit /b 1

echo built %~dp0..\frontier_native.pyd
endlocal
