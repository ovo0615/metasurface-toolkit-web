<RULE[project]>
當在 Windows 環境建立包含中文字元的批次檔 (.bat) 時，絕對不能將其儲存為預設的 UTF-8 (無論有無 BOM) 編碼，因為 Windows 繁體中文版的 CMD 預設使用 Big5 (ANSI) 解碼，會導致中文被判定為未知指令並產生執行錯誤（例如「'嚜濃echo' 不是內部或外部命令」）。請務必使用 PowerShell 將 .bat 檔明確轉換並儲存為 Big5 (Code Page 950) 編碼，範例指令：
`[System.IO.File]::WriteAllText("file.bat", $content, [System.Text.Encoding]::GetEncoding(950))`

相對地，對於 PowerShell 腳本 (.ps1)，如果內容包含中文字元，則必須儲存為「UTF-8 with BOM」，否則 PowerShell 5.1 解析時會噴出 parser 錯誤。
</RULE[project]>
