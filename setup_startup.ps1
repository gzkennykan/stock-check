$WScriptShell = New-Object -ComObject WScript.Shell
$Shortcut = $WScriptShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\StockBacktest.lnk")
$Shortcut.TargetPath = "D:\CC\CC TEST\launch.bat"
$Shortcut.WorkingDirectory = "D:\CC\CC TEST"
$Shortcut.WindowStyle = 7
$Shortcut.Description = "启动股票回测系统 Streamlit"
$Shortcut.Save()
Write-Output "Shortcut created successfully in Startup folder"
Write-Output "Startup folder: $env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup"
