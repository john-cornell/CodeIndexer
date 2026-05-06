param(
    [Parameter(Mandatory = $true)]
    [string]$RepoRoot
)

$dir = [System.IO.Path]::GetFullPath($RepoRoot.TrimEnd('\', '/'))
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
if ($null -eq $userPath) {
    $userPath = ''
}

$segments = @(
    $userPath.Split(';', [StringSplitOptions]::RemoveEmptyEntries) |
        ForEach-Object { $_.Trim() } |
        Where-Object { $_ }
)

$already = $segments | Where-Object { $_ -ieq $dir }
if ($already) {
    Write-Host 'Already on User PATH - nothing to do.' -ForegroundColor Yellow
    exit 0
}

$newPath = if ($segments.Count -eq 0) {
    $dir
} else {
    ($segments + $dir) -join ';'
}

[Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
Write-Host 'Added to User PATH:' -ForegroundColor Green
Write-Host ('  ' + $dir)
Write-Host 'Open a NEW terminal (restart Cursor or VS Code) so PATH updates.'
