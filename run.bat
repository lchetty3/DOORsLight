@echo off
setlocal

REM === CONFIGURATION ===
set SRC="C:\Temp\doors_exports\"
set DEST1="o:\02 - System Engineering\DOORSLight\"
set DEST2= 'R:\Projects\0MJ - AEC GSR\01 - Sync Folder\02 - System Engineering\12 - DOORsLight\'
set SITE1=site
set PYTHON_SCRIPT=C:\__LocalGIT\GSR\DOORsLight\src\generate_site.py

echo === 1. COPY all files from C:\temp\doors_export to current working folder ===
echo Copying source files...
xcopy %SRC% "%~dp0exports\doors_exports" /E /Y /I 
if errorlevel 1 echo Warning: Some files may not have copied correctly.

echo === 2. RUN Python script ===
echo Running Python script...
python "%PYTHON_SCRIPT%" --exports ./exports --out ./site --project-name "Ground Survellience Radar" --logo "./src/ReutechLogo.png"
if errorlevel 1 (
    echo Python script failed. Aborting further copies.
    exit /b 1
)

echo === 3. COPY all files to O:\ ===
echo Copying files to %DEST1% ...
xcopy "%~dp0%SITE1%\" %DEST1% /E /Y /I 
if errorlevel 1 echo Warning: Copy to %DEST1% encountered errors.

echo All done.
endlocal



