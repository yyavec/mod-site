@echo off
chcp 65001 >nul
title NOCHEN SETUP
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = [IO.File]::ReadAllText('%~f0', [Text.Encoding]::UTF8); $i = $s.IndexOf('#PS' + 'START'); Invoke-Expression $s.Substring($i)"
echo.
pause
exit /b

#PSSTART
# ============================================================
#  노천극장 서버 설치 프로그램 (Windows)
#  - Fabric 을 자동으로 설치하고 (Java 필요 없음)
#  - .minecraft 안에 '노천극장 전용 폴더'를 따로 만들어 모드 · 설정을 넣고
#  - 런처에 '노천극장' 항목과 서버 주소를 등록한다.
#  모드가 바뀌면 이 파일을 다시 실행하면 전용 폴더의 모드만 깨끗하게 바뀐다.
#  기존 .minecraft\mods 는 건드리지 않는다 (원하면 백업 폴더로 옮겨 정리).
# ============================================================
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch {}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$SITE = if ($env:NOCHEN_SITE) { $env:NOCHEN_SITE } else { 'https://yyavec.github.io/mod-site/' }

function Say([string]$m, [string]$c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Step([int]$n, [string]$m) { Write-Host ''; Write-Host (' [' + $n + '/7] ' + $m) -ForegroundColor Cyan }
function Fetch([string]$url, [string]$out) {
  $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
  if (Test-Path $curl) {
    & $curl -L --fail --retry 3 --progress-bar -o $out $url
    if ($LASTEXITCODE -ne 0) { throw ('파일을 받지 못했어요: ' + $url) }
  } else {
    (New-Object Net.WebClient).DownloadFile($url, $out)
  }
}
function WriteJson([string]$path, $obj) {
  $json = $obj | ConvertTo-Json -Depth 50
  [IO.File]::WriteAllText($path, $json, (New-Object Text.UTF8Encoding $false))
}
# servers.dat (NBT) 만들기: 서버 하나만 들어 있는 목록
function ServersDat([string]$path, [string]$name, [string]$ip) {
  $ms = New-Object IO.MemoryStream
  function B([byte[]]$b) { $ms.Write($b, 0, $b.Length) }
  function S([string]$s) { $u = [Text.Encoding]::UTF8.GetBytes($s); B @([byte](($u.Length -shr 8) -band 255), [byte]($u.Length -band 255)); B $u }
  B @(10); S ''                      # 뿌리 묶음
  B @(9); S 'servers'; B @(10, 0, 0, 0, 1)   # servers 목록 (묶음 1개)
  B @(8); S 'name'; S $name
  B @(8); S 'ip'; S $ip
  B @(0)                             # 서버 묶음 끝
  B @(0)                             # 뿌리 끝
  [IO.File]::WriteAllBytes($path, $ms.ToArray())
}

# ---- 맨 위 그림: 주인 얼굴 + 몬스터볼 (24비트 색, 안 되면 16색으로) ----
function Banner {
  $face = '548F3E,519835,67B04B,67B04B,519835,67B04B,519835,548F3E;519835,67B04B,67B04B,67B04B,67B04B,67B04B,67B04B,519835;67B04B,67B04B,67B04B,67B04B,67B04B,67B04B,67B04B,67B04B;67B04B,67B04B,67B04B,67B04B,67B04B,67B04B,67B04B,67B04B;FFFFFF,FFFFFF,67B04B,67B04B,67B04B,67B04B,FFFFFF,FFFFFF;000000,FFFFFF,67B04B,67B04B,67B04B,67B04B,FFFFFF,000000;519835,67B04B,67B04B,67B04B,67B04B,67B04B,67B04B,519835;548F3E,519835,67B04B,67B04B,67B04B,519835,519835,548F3E'.Split(';')
  $ball = ',,1D1D25,1D1D25,1D1D25,1D1D25,,;,1D1D25,E3403A,E3403A,E3403A,E3403A,1D1D25,;1D1D25,E3403A,FF8A7E,E3403A,E3403A,E3403A,E3403A,1D1D25;1D1D25,E3403A,E3403A,1D1D25,1D1D25,E3403A,E3403A,1D1D25;1D1D25,1D1D25,1D1D25,F4F4F4,F4F4F4,1D1D25,1D1D25,1D1D25;1D1D25,F4F4F4,F4F4F4,1D1D25,1D1D25,F4F4F4,F4F4F4,1D1D25;,1D1D25,F4F4F4,F4F4F4,F4F4F4,F4F4F4,1D1D25,;,,1D1D25,1D1D25,1D1D25,1D1D25,,'.Split(';')
  $text = @('', '', @('노천극장 놀이터', 'Green'), @('코블몬 서버 설치 프로그램', 'White'), @('Cobblemon · Fabric · Minecraft 1.21.1', 'Cyan'), @('made by 주끼삐끼 (JOOKKIBBIKKI)', 'DarkGray'), '', '')
  $vt = $false
  try {
    Add-Type -Namespace Nochen -Name Con -MemberDefinition '[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int h); [DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr h, out int m); [DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr h, int m);' -ErrorAction Stop
    $h = [Nochen.Con]::GetStdHandle(-11); $m = 0
    if ([Nochen.Con]::GetConsoleMode($h, [ref]$m)) { $vt = [Nochen.Con]::SetConsoleMode($h, $m -bor 4) }
  } catch {}
  $E = [char]27
  function Px([string]$hex) {
    if (-not $hex) { Write-Host '  ' -NoNewline; return }
    if ($vt) { $r = [Convert]::ToInt32($hex.Substring(0, 2), 16); $g = [Convert]::ToInt32($hex.Substring(2, 2), 16); $bb = [Convert]::ToInt32($hex.Substring(4, 2), 16); Write-Host ("$E[48;2;$r;$g;$bb" + 'm  ' + "$E[0m") -NoNewline }
    else {
      $map = @{ '000000' = 'Black'; '1D1D25' = 'Black'; 'FFFFFF' = 'White'; 'F4F4F4' = 'White'; 'E3403A' = 'Red'; 'FF8A7E' = 'Red' }
      $col = if ($map.ContainsKey($hex)) { $map[$hex] } elseif ($hex -eq '67B04B') { 'Green' } else { 'DarkGreen' }
      Write-Host '  ' -BackgroundColor $col -NoNewline
    }
  }
  Write-Host ''
  for ($y = 0; $y -lt 8; $y++) {
    Write-Host '   ' -NoNewline
    foreach ($c in $face[$y].Split(',')) { Px $c }
    Write-Host '  ' -NoNewline
    foreach ($c in $ball[$y].Split(',')) { Px $c }
    $t = $text[$y]
    if ($t -is [array]) { Write-Host ('    ' + $t[0]) -ForegroundColor $t[1] } else { Write-Host '' }
  }
  Write-Host ''
  Write-Host '   ' -NoNewline; Write-Host (' ' * 4) -NoNewline
  Write-Host '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━' -ForegroundColor DarkRed
}

try {
  try { $Host.UI.RawUI.WindowTitle = '노천극장 놀이터 · 코블몬 설치' } catch {}
  Banner
  Say '  창을 닫지 말고 끝날 때까지 기다려 주세요.' Gray
  Say '  코블몬과 상관없는 예전 모드 · 설정 · 버전은 백업 없이 지워져요.' Yellow

  Step 1 '서버 정보 확인'
  $cfg = Invoke-RestMethod ($SITE + 'install.json?t=' + [DateTime]::Now.Ticks)
  if ($cfg.loader -ne 'Fabric') { throw ('지금 서버는 ' + $cfg.loader + ' 라서 이 프로그램으로는 설치할 수 없어요. 사이트의 직접 설치 방법을 따라 주세요.') }
  $mc = [string]$cfg.mc
  Say ('  마인크래프트 ' + $mc + ' · Fabric · ' + $cfg.server.name)

  $root = Join-Path $env:APPDATA '.minecraft'
  if (-not (Test-Path $root)) { throw '마인크래프트 폴더(.minecraft)가 없어요. 공식 런처로 게임을 한 번 켜 본 다음 다시 실행해 주세요.' }
  $warned = $false
  while (-not $env:NOCHEN_TEST -and (Get-Process -Name 'MinecraftLauncher', 'Minecraft' -ErrorAction SilentlyContinue)) {
    if (-not $warned) { Say '  마인크래프트 런처가 켜져 있어요. 런처를 닫아 주세요. 닫으면 자동으로 계속돼요...' Yellow; $warned = $true }
    Start-Sleep -Seconds 2
  }

  Step 2 'Fabric 설치'
  $loaders = Invoke-RestMethod ('https://meta.fabricmc.net/v2/versions/loader/' + $mc)
  $lv = [string]$cfg.fabricLoader
  if (-not $lv) { $lv = ($loaders | Where-Object { $_.loader.stable } | Select-Object -First 1).loader.version }
  if (-not $lv) { $lv = $loaders[0].loader.version }
  $vid = 'fabric-loader-' + $lv + '-' + $mc
  $vdir = Join-Path $root ('versions\' + $vid)
  New-Item -ItemType Directory -Force -Path $vdir | Out-Null
  Fetch ('https://meta.fabricmc.net/v2/versions/loader/' + $mc + '/' + $lv + '/profile/json') (Join-Path $vdir ($vid + '.json'))
  Say ('  Fabric ' + $lv + ' (마인크래프트 ' + $mc + ') 준비 완료')

  Step 3 '노천극장 전용 폴더 준비'
  $game = Join-Path $root ([string]$cfg.folder)
  New-Item -ItemType Directory -Force -Path $game | Out-Null
  Say ('  ' + $game)

  Step 4 '모드 받기 (시간이 좀 걸려요)'
  $tmp = Join-Path $env:TEMP 'nochen-setup'
  if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $tmp | Out-Null
  $zip = Join-Path $tmp 'mods.zip'
  Fetch ([string]$cfg.mods) $zip
  $unz = Join-Path $tmp 'mods'
  Expand-Archive -LiteralPath $zip -DestinationPath $unz -Force
  $mods = Join-Path $game 'mods'
  if (Test-Path $mods) { Remove-Item $mods -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $mods | Out-Null
  $jars = Get-ChildItem -LiteralPath $unz -Recurse -Filter '*.jar'
  foreach ($j in $jars) { Move-Item -LiteralPath $j.FullName -Destination $mods -Force }
  Say ('  모드 ' + $jars.Count + '개 설치 (예전 모드는 깨끗하게 지움)') Green

  Step 5 '설정 파일'
  if ($cfg.config) {
    $cz = Join-Path $tmp 'config.zip'
    Fetch ([string]$cfg.config) $cz
    Expand-Archive -LiteralPath $cz -DestinationPath $game -Force
    Say '  서버와 같은 설정으로 맞췄어요' Green
  } else { Say '  따로 맞출 설정이 없어요' }

  Step 6 '서버 목록 · 런처 등록'
  ServersDat (Join-Path $game 'servers.dat') ([string]$cfg.server.name) ([string]$cfg.server.address)
  $ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
  $xmx = if ($ram -ge 15) { 6 } elseif ($ram -ge 7) { 4 } else { 3 }
  $now = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ')
  $prof = [pscustomobject]@{
    name          = [string]$cfg.profileName
    type          = 'custom'
    lastVersionId = $vid
    gameDir       = $game
    icon          = 'Grass'
    javaArgs      = ('-Xmx' + $xmx + 'G -XX:+UnlockExperimentalVMOptions -XX:+UseG1GC -XX:G1NewSizePercent=20 -XX:G1ReservePercent=20 -XX:MaxGCPauseMillis=50 -XX:G1HeapRegionSize=32M')
    created       = $now
    lastUsed      = $now
  }
  $files = @('launcher_profiles.json', 'launcher_profiles_microsoft_store.json') | ForEach-Object { Join-Path $root $_ } | Where-Object { Test-Path $_ }
  if (-not $files) { $files = @(Join-Path $root 'launcher_profiles.json'); WriteJson $files[0] ([pscustomobject]@{ profiles = [pscustomobject]@{}; version = 3 }) }
  foreach ($f in $files) {
    $j = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8) | ConvertFrom-Json
    if (-not $j.profiles) { $j | Add-Member -NotePropertyName profiles -NotePropertyValue ([pscustomobject]@{}) -Force }
    $j.profiles | Add-Member -NotePropertyName 'nochen-server' -NotePropertyValue $prof -Force
    WriteJson $f $j
  }
  Say ('  런처에 "' + $cfg.profileName + '" 추가 (메모리 ' + $xmx + 'GB)') Green

  Step 7 '코블몬과 상관없는 파일 정리'
  $gone = New-Object System.Collections.Generic.List[string]
  function Wipe([string]$p, [string]$label) {
    if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue; if (-not (Test-Path -LiteralPath $p)) { $gone.Add($label) } }
  }
  # 1) .minecraft\mods 에 남은 예전 모드 (폴더는 두고 안만 비움)
  $old = Join-Path $root 'mods'
  if (Test-Path -LiteralPath $old) {
    $items = @(Get-ChildItem -LiteralPath $old -Force)
    if ($items.Count) { $items | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue; $gone.Add('.minecraft\mods 안의 예전 모드 ' + $items.Count + '개') }
  }
  # 2) 예전 모드팩이 남긴 설정 · 예전 정리 때 만든 백업
  Wipe (Join-Path $root 'config') '.minecraft\config (예전 모드 설정)'
  Wipe (Join-Path $root 'defaultconfigs') '.minecraft\defaultconfigs'
  Get-ChildItem -LiteralPath $root -Directory -Filter 'mods_backup_*' -ErrorAction SilentlyContinue | ForEach-Object { Wipe $_.FullName $_.Name }
  Get-ChildItem -LiteralPath $root -Filter '*.nochen-backup' -ErrorAction SilentlyContinue | ForEach-Object { Wipe $_.FullName $_.Name }
  if (Test-Path -LiteralPath (Join-Path $game 'defaultconfigs')) { Wipe (Join-Path $game 'defaultconfigs') '노천극장 폴더의 예전 defaultconfigs'; Wipe (Join-Path $game 'config') '노천극장 폴더의 예전 config' }
  # 3) Forge · NeoForge 버전, 노천극장용이 아닌 Fabric 버전
  $vroot = Join-Path $root 'versions'
  if (Test-Path -LiteralPath $vroot) {
    Get-ChildItem -LiteralPath $vroot -Directory | Where-Object { ($_.Name -match 'forge') -or (($_.Name -like 'fabric-loader-*') -and ($_.Name -ne $vid)) } | ForEach-Object { Wipe $_.FullName ('버전 ' + $_.Name) }
  }
  # 4) 런처 목록에서 지운 버전을 쓰던 항목
  foreach ($f in $files) {
    $j = [IO.File]::ReadAllText($f, [Text.Encoding]::UTF8) | ConvertFrom-Json
    $drop = @($j.profiles.PSObject.Properties | Where-Object { $_.Name -ne 'nochen-server' -and (([string]$_.Value.lastVersionId -match 'forge') -or ((([string]$_.Value.lastVersionId) -like 'fabric-loader-*') -and ([string]$_.Value.lastVersionId -ne $vid))) })
    foreach ($p in $drop) { $j.profiles.PSObject.Properties.Remove($p.Name); $gone.Add('런처 항목 ' + $(if ($p.Value.name) { $p.Value.name } else { $p.Value.lastVersionId })) }
    if ($drop.Count) { WriteJson $f $j }
  }
  if ($gone.Count) { foreach ($g in $gone) { Say ('  - ' + $g + ' 지움') } ; Say '  깔끔하게 정리했어요' Green } else { Say '  정리할 게 없어요. 이미 깔끔해요' Green }

  Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
  Write-Host ''
  Say '  ============================================' Green
  Say '   설치 끝! 이제 이렇게 하면 돼요' Green
  Say '  ============================================' Green
  Say ('   1. 마인크래프트 런처를 켜요')
  Say ('   2. 플레이 버튼 왼쪽 목록에서  "' + $cfg.profileName + '"  을 골라요')
  Say ('   3. 플레이! → 멀티플레이에 서버가 이미 들어 있어요')
  Say ''
  Say '   모드가 업데이트되면 이 프로그램을 다시 실행하면 돼요.' Gray
}
catch {
  Write-Host ''
  Say ('  문제가 생겼어요: ' + $_.Exception.Message) Red
  Say '  이 창을 캡처해서 디스코드로 보내 주세요. 사이트의 "직접 설치하기" 방법도 있어요.' Yellow
}
