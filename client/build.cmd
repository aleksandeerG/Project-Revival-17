@echo off
rem Project Revival 17 - created by aleksanderG - https://github.com/aleksandeerG/Project-Revival-17
setlocal
set "SRC=%~dp0src"
set "OUT=%~dp0build"
if not exist "%OUT%" mkdir "%OUT%"

call :find_vcvars
if not defined VCVARS ( echo Could not find vcvars64.bat. Install the VS C++ x64 tools. & exit /b 1 )
call "%VCVARS%" >nul
if errorlevel 1 ( echo vcvars failed & exit /b 1 )

echo Compiling version.dll ...
cl /nologo /LD /O2 /MT /EHsc /std:c++17 /DUNICODE /D_UNICODE ^
   "%SRC%\proxy.cpp" "%SRC%\config.cpp" "%SRC%\patch.cpp" "%SRC%\fut_watch.cpp" "%SRC%\auth.cpp" "%SRC%\origin.cpp" "%SRC%\worker.cpp" "%SRC%\crash_report.cpp" ^
   /Fo"%OUT%\\" /link /DLL user32.lib /OUT:"%OUT%\version.dll" /IMPLIB:"%OUT%\version.lib"
if errorlevel 1 ( echo BUILD FAILED & exit /b 1 )

echo.
echo Built %OUT%\version.dll
dumpbin /nologo /headers "%OUT%\version.dll" | findstr /C:"machine"
dumpbin /nologo /exports "%OUT%\version.dll" | findstr /C:"forwarded" | find /c "forwarded" > "%OUT%\_fw.txt"
set /p FWCOUNT=<"%OUT%\_fw.txt"
del "%OUT%\_fw.txt"
echo Forwarded version exports: %FWCOUNT% (expect 17; DLL also exports DllMain + 28 Origin functions)
for /f "tokens=1" %%N in ('dumpbin /nologo /exports "%OUT%\version.dll" ^| findstr /C:"number of names"') do set "TOTAL=%%N"
echo Total named exports: %TOTAL% (expect 46)
if not "%FWCOUNT%"=="17" ( echo EXPORT CHECK FAILED & exit /b 1 )
if not "%TOTAL%"=="46" ( echo EXPORT CHECK FAILED & exit /b 1 )
exit /b 0

:find_vcvars
for %%E in (
  "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
  "C:\Program Files\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
  "C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"
  "C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
) do if exist %%E set "VCVARS=%%~E"
exit /b 0
