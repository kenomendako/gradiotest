# characters_backup.ps1
# Nexus Ark キャラクターデータ自動バックアップスクリプト

$charactersPath = "c:\Users\baken\OneDrive\デスクトップ\gradio_github\gradiotest\characters"
$logFile = "$charactersPath\backup_log.txt"

# ログ関数
function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Add-Content -Path $logFile
}

try {
    Set-Location $charactersPath
    
    # 変更があるかチェック
    $status = git status --porcelain
    
    if ($status) {
        # 変更がある場合のみコミット
        git add .
        $commitMessage = "自動バックアップ: $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
        git commit -m $commitMessage
        Write-Log "バックアップ成功: $commitMessage"
    } else {
        Write-Log "変更なし - スキップ"
    }
} catch {
    Write-Log "エラー: $_"
}
