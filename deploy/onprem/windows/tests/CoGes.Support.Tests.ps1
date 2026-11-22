# Tests Pester 5 du support à distance (lot 6, ADR 0129).
#
# Joués comme ceux des lots 3 à 5 : sous Linux (pwsh) et sous Windows (5.1 et pwsh). Docker
# n'est jamais appelé : Invoke-Docker est remplacé par un faux. Les pings vont à un vrai petit
# serveur HTTP local (TcpListener dans un runspace) ou à un faux Invoke-CogesPingRequest.
#
#   Invoke-Pester -Path deploy/onprem/windows/tests

BeforeAll {
    $windows = Split-Path -Parent $PSScriptRoot
    $script:Onprem = Split-Path -Parent $windows
    . (Join-Path $windows 'CoGes.Install.ps1')
    $script:Model = [IO.File]::ReadAllText((Join-Path $script:Onprem 'coges.env.example'))
    $script:Fields = Get-CogesFieldList
    $script:Slug = 'keur-fatou'
    $script:UpCode = 0
    $script:LogLines = 300

    function New-DockerResult {
        param([int] $Code, [string[]] $Lines)
        [pscustomobject]@{ ExitCode = $Code; Output = $Lines; Stdout = $Lines }
    }

    function New-TestInstall {
        <# Une installation factice : réglages aux secrets connus, sauvegarde au nom de la boutique,
           journal qui contient un secret, état de mise à jour, support.json actif. #>
        param([string] $Url = 'http://127.0.0.1:9/ping')
        $paths = Get-CogesPath (Join-Path $TestDrive ('r-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)))
        New-Item -ItemType Directory -Force -Path $paths.Reglages, $paths.Journaux, $paths.Programme | Out-Null
        [IO.File]::WriteAllText($paths.Version, "v0.4.0`n")
        $values = New-CogesSecretSet
        $values['COGES_IMAGE_TAG'] = 'v0.4.0'
        $values['COGES_HTTP_PORT'] = '80'
        $values['COGES_PUBLIC_URL'] = 'http://localhost'
        Write-CogesEnvFile -Path $paths.EnvFile -Text (ConvertTo-CogesEnvText -Model $script:Model -Values $values)
        $script:Secrets = @($values.Keys | Where-Object { $_ -match 'PASSWORD|SECRET|KEY' } | ForEach-Object { [string]$values[$_] })
        $backup = Get-CogesBackupPath $paths
        New-Item -ItemType Directory -Force -Path $backup.Dossier | Out-Null
        $name = 'coges-{0}-{1}-v0.4.0.coges' -f $script:Slug, (Get-Date).AddHours(-2).ToString('yyyyMMdd-HHmm')
        foreach ($suffix in @('', '.sha256', '.manifest.json')) { [IO.File]::WriteAllText((Join-Path $backup.Dossier ($name + $suffix)), 'x') }
        Write-CogesBackupState -Paths $paths -Changes @{ derniere_copie_hors_pc = (Get-Date).AddDays(-1).ToString('o'); dernier_essai = (Get-Date).AddDays(-3).ToString('o'); dernier_essai_ok = $true }
        [IO.File]::WriteAllText((Join-Path $paths.Journaux ('sauvegarde-{0}.log' -f (Get-Date).ToString('yyyyMMdd'))),
            ('{0} [ECHEC] sauvegarde en échec : mot de passe {1}, boutique {2}' -f (Get-Date).AddHours(-1).ToString('yyyy-MM-dd HH:mm:ss'), $values['COGES_APP_PASSWORD'], $script:Slug) + "`n")
        $script:CogesState.LogPath = Join-Path $paths.Journaux ('support-{0}.log' -f (Get-Date).ToString('yyyyMMdd'))
        $script:CogesState.Simulation = $false
        $script:CogesState.NonInteractif = $true
        $script:CogesState.Output.Clear()
        Write-CogesSupportSetting -Paths $paths -Setting @{ pc = ('0123456789abcdef' * 2); remontee = $true; telephone_coges = '+221 77 000 00 00'
            adresses = @{ vie = ($Url + '/vie-' + ('a' * 24)); sauvegarde = ($Url + '/sauvegarde-' + ('b' * 24)); 'mise-a-jour' = ($Url + '/maj-' + ('c' * 24)) } }
        [void](Get-CogesSetting $paths)
        return $paths
    }

    function Invoke-FakeDocker {
        param([string[]] $Arguments)
        $text = $Arguments -join ' '
        if ($text -match 'Platform\.Name') { return New-DockerResult 0 @('Docker Desktop 4.37.1 (178610)|27.4.0') }
        if ($text -match '^version') { return New-DockerResult 0 @('linux') }
        if ($text -match ' ps -a --format json') {
            $lines = foreach ($service in $script:CogesServices) {
                $health = 'healthy'
                if ($service -eq 'beat') { $health = 'unhealthy' }
                if ($service -eq 'autoheal') { $health = '' }
                (@{ Service = $service; State = 'running'; Health = $health } | ConvertTo-Json -Compress)
            }
            return New-DockerResult 0 @($lines)
        }
        if ($text -match 'base\.py licence') { return New-DockerResult 0 @('{"societes": 1, "etats": {"active": 1}, "offres": ["starter"], "sans_fin": 1}') }
        if ($text -match ' logs ') {
            $tail = [int]($Arguments[[array]::IndexOf($Arguments, '--tail') + 1])
            $lines = @(1..$tail | ForEach-Object { 'api | ligne {0} postgresql://coges_app:{1}@postgres/coges {2}{3}' -f $_, $script:Secrets[0], [Guid]::NewGuid().ToString('N'), [Guid]::NewGuid().ToString('N') })
            return New-DockerResult 0 $lines
        }
        if ($text -match ' up -d') { return New-DockerResult $script:UpCode @('up') }
        return New-DockerResult 0 @()
    }

    function Start-TestPingServer {
        <# Un serveur HTTP minimal sur 127.0.0.1 (TcpListener, sans droit d'administrateur) :
           'ok' répond 200 et garde les corps, '404' répond 404, 'lent' ne répond jamais. #>
        param([ValidateSet('ok', '404', 'lent')] [string] $Mode = 'ok')
        $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback, 0)
        $listener.Start()
        $port = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
        $requests = [Collections.ArrayList]::Synchronized((New-Object Collections.ArrayList))
        $runspace = [powershell]::Create()
        [void]$runspace.AddScript({
                param($listener, $mode, $requests)
                while ($true) {
                    try { $client = $listener.AcceptTcpClient() } catch { return }
                    if ($mode -eq 'lent') { $requests.Add('lent') | Out-Null; continue }
                    $stream = $client.GetStream()
                    $buffer = New-Object byte[] 65536
                    $data = New-Object IO.MemoryStream
                    $length = -1
                    $headerEnd = -1
                    while ($true) {
                        $read = $stream.Read($buffer, 0, $buffer.Length)
                        if ($read -le 0) { break }
                        $data.Write($buffer, 0, $read)
                        $text = [Text.Encoding]::UTF8.GetString($data.ToArray())
                        if ($headerEnd -lt 0) {
                            $headerEnd = $text.IndexOf("`r`n`r`n")
                            if ($headerEnd -ge 0 -and $text -match '(?im)^content-length:\s*(\d+)') { $length = [int]$Matches[1] }
                            elseif ($headerEnd -ge 0) { $length = 0 }
                        }
                        if ($headerEnd -ge 0 -and ($data.Length - $headerEnd - 4) -ge $length) { break }
                    }
                    $raw = [Text.Encoding]::UTF8.GetString($data.ToArray())
                    $first = ($raw -split "`r`n")[0]
                    $body = ''
                    if ($headerEnd -ge 0) { $body = $raw.Substring($headerEnd + 4) }
                    $requests.Add([pscustomobject]@{ Line = $first; Body = $body }) | Out-Null
                    $status = 'HTTP/1.1 200 OK'
                    if ($mode -eq '404') { $status = 'HTTP/1.1 404 Not Found' }
                    $answer = [Text.Encoding]::ASCII.GetBytes($status + "`r`nContent-Length: 2`r`nConnection: close`r`n`r`nOK")
                    $stream.Write($answer, 0, $answer.Length)
                    $client.Close()
                }
            }).AddArgument($listener).AddArgument($Mode).AddArgument($requests)
        $handle = $runspace.BeginInvoke()
        return [pscustomobject]@{ Url = ('http://127.0.0.1:{0}' -f $port); Requests = $requests; Listener = $listener; Runspace = $runspace; Handle = $handle }
    }

    function Stop-TestPingServer {
        param($Server)
        $Server.Listener.Stop()
        try { [void]$Server.Runspace.EndInvoke($Server.Handle) } catch { Write-Verbose 'fin' }
        $Server.Runspace.Dispose()
    }

    function Get-FreePort {
        $listener = New-Object Net.Sockets.TcpListener ([Net.IPAddress]::Loopback, 0)
        $listener.Start()
        $port = ([Net.IPEndPoint]$listener.LocalEndpoint).Port
        $listener.Stop()
        return $port
    }
}

Describe 'La liste fermée de ce qui sort (bloc A)' {
    It 'lit support\champs.txt : 25 champs, règles ancrées' {
        $script:Fields.Count | Should -Be 25
        $script:Fields[0].Name | Should -Be 'format'
        foreach ($field in $script:Fields) { $field.Rule | Should -Match '^\^\(\?:.*\)\$$' }
    }

    It 'le résumé minimal passe la liste, tient en moins de 2 Ko, dans l''ordre de la liste' {
        $report = Get-CogesReport -Facts (Get-CogesMinimalFact -Pc ('ab' * 16) -Signal 'vie' -Failure $false) -Fields $script:Fields
        $text = Format-CogesReport $report
        [Text.Encoding]::UTF8.GetByteCount($text) | Should -BeLessThan 2048
        (@($text.TrimEnd("`n") -split "`n" | ForEach-Object { $_.Split(':')[0] }) -join ',') | Should -Be ((@($script:Fields | ForEach-Object { $_.Name })) -join ',')
    }

    It 'refuse un champ en trop' {
        $facts = Get-CogesMinimalFact -Pc ('ab' * 16) -Signal 'vie' -Failure $false
        $facts['chiffre_affaires'] = '125000'
        { Get-CogesReport -Facts $facts -Fields $script:Fields } | Should -Throw '*chiffre_affaires*champs.txt*'
    }

    It 'refuse un champ manquant et une valeur hors de sa règle (aucun texte libre)' {
        $facts = Get-CogesMinimalFact -Pc ('ab' * 16) -Signal 'vie' -Failure $false
        $facts.Remove('disque_go')
        { Get-CogesReport -Facts $facts -Fields $script:Fields } | Should -Throw '*disque_go*manque*'
        foreach ($case in @(@('raison', 'base coges inaccessible : Awa Diop'), @('pc', 'keur-fatou'), @('services_ko', 'api,inconnu-x'), @('version', 'v1.2.3 Keur Fatou'))) {
            $facts = Get-CogesMinimalFact -Pc ('ab' * 16) -Signal 'vie' -Failure $true
            $facts[$case[0]] = $case[1]
            { Get-CogesReport -Facts $facts -Fields $script:Fields } | Should -Throw ('*{0}*hors de sa règle*' -f $case[0])
        }
    }

    It 'un échec sans raison connue part en « autre »' {
        (Get-CogesMinimalFact -Pc ('ab' * 16) -Signal 'sauvegarde' -Failure $true).raison | Should -Be 'autre'
    }

    It 'traduit les messages d''échec en codes de la liste' {
        Get-CogesFailureCode 'Pas assez de place sur le disque (1,2 Go libres)' | Should -Be 'place-disque'
        Get-CogesFailureCode 'Aucune clé publique de sauvegarde sur ce PC' | Should -Be 'cle-absente'
        Get-CogesFailureCode 'Sauvegarde trop petite : 10 octets' | Should -Be 'taille'
        Get-CogesFailureCode 'L''empreinte relue ne correspond pas.' | Should -Be 'empreinte'
        Get-CogesFailureCode 'Docker ne répond pas' | Should -Be 'docker-arrete'
        Get-CogesFailureCode 'quelque chose de neuf' | Should -Be 'autre'
        $rule = @($script:Fields | Where-Object { $_.Name -eq 'raison' })[0].Rule
        foreach ($code in @('place-disque', 'cle-absente', 'taille', 'empreinte', 'docker-arrete', 'verrou', 'demarrage', 'autre')) { $code | Should -Match $rule }
    }

    It 'le résumé d''un vrai PC factice ne contient aucun secret, ni code de boutique, ni adresse de ping' {
        $paths = New-TestInstall
        Mock Invoke-Docker { Invoke-FakeDocker -Arguments $Arguments }
        $facts = Read-CogesReportFact -Paths $paths -Pc ('0123456789abcdef' * 2) -Signal 'vie' -Failure $false
        $text = Format-CogesReport (Get-CogesReport -Facts $facts -Fields $script:Fields)
        foreach ($secret in $script:Secrets) { $text | Should -Not -Match ([regex]::Escape($secret)) }
        $text | Should -Not -Match $script:Slug
        $text | Should -Not -Match 'Keur|Fatou|127\.0\.0\.1|ping'
        $text | Should -Match 'services_ok: 8/9'
        $text | Should -Match 'services_ko: beat'
        $text | Should -Match 'licence: active'
        $text | Should -Match 'offre: starter'
        $text | Should -Match 'docker: 4\.37\.1'
        $text | Should -Match 'version: v0\.4\.0'
        $text | Should -Match 'erreurs_24h: sauvegarde=1'
        $text | Should -Match 'essai: ok'
        $text | Should -Not -Match 'sauvegarde_le: jamais'
    }

    It 'Docker arrêté : services et licence « inconnu », le résumé passe quand même' {
        $paths = New-TestInstall
        Mock Invoke-Docker { New-DockerResult 1 @('error during connect') }
        $facts = Read-CogesReportFact -Paths $paths -Pc ('0123456789abcdef' * 2) -Signal 'sauvegarde' -Failure $true -Reason 'docker-arrete'
        $report = Get-CogesReport -Facts $facts -Fields $script:Fields
        $report.services_ok | Should -Be 'inconnu'
        $report.licence | Should -Be 'inconnue'
        $report.raison | Should -Be 'docker-arrete'
    }

    It 'licence : suspendue l''emporte, offres sans doublon' {
        (ConvertTo-CogesLicenseFact ('{"etats": {"active": 1, "suspended": 1}, "offres": ["starter", "business"]}' | ConvertFrom-Json)).licence | Should -Be 'suspendue'
        (ConvertTo-CogesLicenseFact ('{"etats": {"active": 1, "suspended": 1}, "offres": ["starter", "business"]}' | ConvertFrom-Json)).offre | Should -Be 'business,starter'
        (ConvertTo-CogesLicenseFact $null).licence | Should -Be 'inconnue'
        (ConvertTo-CogesLicenseFact ('{"etats": {}, "offres": []}' | ConvertFrom-Json)).licence | Should -Be 'aucune'
    }
}

Describe 'Réglages du support (bloc B)' {
    It 'Installer tire un identifiant de PC, remontée inactive ; Reparer ne le change jamais' {
        $paths = Get-CogesPath (Join-Path $TestDrive 'neuf')
        New-Item -ItemType Directory -Force -Path $paths.Reglages | Out-Null
        $script:CogesState.Simulation = $false
        $script:CogesState.LogPath = $null
        Initialize-CogesSupportSetting -Paths $paths -Options @{ Support = '' }
        $first = Read-CogesSupportSetting $paths
        $first.pc | Should -Match '^[0-9a-f]{32}$'
        $first.remontee | Should -BeFalse
        Initialize-CogesSupportSetting -Paths $paths -Options @{ Support = '' }
        (Read-CogesSupportSetting $paths).pc | Should -Be $first.pc
        $file = Join-Path $TestDrive 'support-technicien.json'
        [IO.File]::WriteAllText($file, (@{ pc = ('f' * 32); telephone_coges = '+221 33 000 00 00'
                    adresses = @{ vie = 'https://hc-ping.com/aaaaaaaa-1111'; sauvegarde = 'https://hc-ping.com/bbbbbbbb-2222'; 'mise-a-jour' = 'https://hc-ping.com/cccccccc-3333' } } | ConvertTo-Json))
        Initialize-CogesSupportSetting -Paths $paths -Options @{ Support = $file }
        $after = Read-CogesSupportSetting $paths
        $after.pc | Should -Be $first.pc
        $after.remontee | Should -BeTrue
        $after.adresses['mise-a-jour'] | Should -Be 'https://hc-ping.com/cccccccc-3333'
        $after.telephone_coges | Should -Be '+221 33 000 00 00'
        [IO.File]::ReadAllText((Get-CogesSupportPath $paths).Reglage) | Should -Not -Match 'COGES_'
    }

    It 'refuse un fichier du technicien sans les trois adresses https' {
        $file = Join-Path $TestDrive 'support-faux.json'
        [IO.File]::WriteAllText($file, (@{ adresses = @{ vie = 'https://hc-ping.com/a'; sauvegarde = 'http://exemple.com/b' } } | ConvertTo-Json))
        { Read-CogesSupportFile $file } | Should -Throw '*sauvegarde*'
        { Read-CogesSupportFile (Join-Path $TestDrive 'absent.json') } | Should -Throw '*introuvable*'
    }

    It 'les adresses de ping sont masquées dans le journal, et Etat ne les montre jamais' {
        $paths = New-TestInstall -Url 'https://hc-ping.com'
        $url = (Read-CogesSupportSetting $paths).adresses['vie']
        Write-Log -Message ('envoi vers ' + $url)
        $log = [IO.File]::ReadAllText($script:CogesState.LogPath)
        $log | Should -Not -Match ([regex]::Escape($url))
        $log | Should -Not -Match ('a' * 24)
        $script:CogesState.Output.Clear()
        Mock Write-Host { }
        Show-CogesSupportState -Paths $paths
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match 'Remontée vers CoGes : active \(3 adresse'
        $text | Should -Not -Match 'hc-ping'
        $text | Should -Match 'Journaux'
    }
}

Describe 'Envoi : jamais bloquant (bloc B)' {
    BeforeEach {
        Mock Invoke-Docker { Invoke-FakeDocker -Arguments $Arguments }
        $script:CogesPingTimeoutSeconds = 1
        $script:CogesPingPauseSeconds = 0
    }
    AfterEach { $script:CogesPingTimeoutSeconds = 10; $script:CogesPingPauseSeconds = 2 }

    It 'serveur qui répond : POST du résumé, /fail en cas d''échec, état noté' {
        $server = Start-TestPingServer -Mode ok
        try {
            $paths = New-TestInstall -Url ($server.Url + '/ping')
            Send-CogesPing -Paths $paths -Signal 'sauvegarde' | Should -BeTrue
            Send-CogesPing -Paths $paths -Signal 'sauvegarde' -Failure -Reason 'place-disque' | Should -BeTrue
            $server.Requests.Count | Should -Be 2
            $server.Requests[0].Line | Should -Match ('^POST /ping/sauvegarde-b{24} HTTP')
            $server.Requests[1].Line | Should -Match ('^POST /ping/sauvegarde-b{24}/fail HTTP')
            $server.Requests[1].Body | Should -Match "raison: place-disque"
            $server.Requests[1].Body | Should -Match "resultat: echec"
            foreach ($request in $server.Requests) {
                foreach ($line in ($request.Body.TrimEnd("`n") -split "`n")) { @($script:Fields | ForEach-Object { $_.Name }) | Should -Contain ($line.Split(':')[0]) }
                foreach ($secret in $script:Secrets) { $request.Body | Should -Not -Match ([regex]::Escape($secret)) }
            }
            (Read-CogesSupportState $paths)['dernier_signal'] | Should -Be 'sauvegarde'
        }
        finally { Stop-TestPingServer $server }
    }

    It 'serveur en panne (port fermé) : rend faux, n''échoue pas, journal seulement' {
        $paths = New-TestInstall -Url ('http://127.0.0.1:{0}' -f (Get-FreePort))
        { Send-CogesPing -Paths $paths -Signal 'vie' } | Should -Not -Throw
        Send-CogesPing -Paths $paths -Signal 'vie' | Should -BeFalse
        [IO.File]::ReadAllText($script:CogesState.LogPath) | Should -Match 'signal vie : .*\(essai 2\)'
        (Read-CogesSupportState $paths)['dernier_echec_envoi'] | Should -Not -BeNullOrEmpty
    }

    It 'serveur lent : abandon après 2 essais bornés par le délai, rend faux' {
        $server = Start-TestPingServer -Mode lent
        try {
            $paths = New-TestInstall -Url ($server.Url + '/ping')
            $watch = [Diagnostics.Stopwatch]::StartNew()
            Send-CogesPing -Paths $paths -Signal 'vie' | Should -BeFalse
            $watch.Elapsed.TotalSeconds | Should -BeLessThan 15
        }
        finally { Stop-TestPingServer $server }
    }

    It 'réponse 404 : rend faux, deux essais, rien ne lève' {
        $server = Start-TestPingServer -Mode '404'
        try {
            $paths = New-TestInstall -Url ($server.Url + '/ping')
            Send-CogesPing -Paths $paths -Signal 'mise-a-jour' | Should -BeFalse
            @($server.Requests).Count | Should -Be 2
        }
        finally { Stop-TestPingServer $server }
    }

    It 'remontée inactive, ou simulation : aucune requête' {
        $paths = New-TestInstall
        Mock Invoke-CogesPingRequest { throw 'ne doit pas être appelé' }
        $setting = Read-CogesSupportSetting $paths
        $setting.remontee = $false
        Write-CogesSupportSetting -Paths $paths -Setting $setting
        Send-CogesPing -Paths $paths -Signal 'vie' | Should -BeFalse
        $setting.remontee = $true
        Write-CogesSupportSetting -Paths $paths -Setting $setting
        $script:CogesState.Simulation = $true
        try { Send-CogesPing -Paths $paths -Signal 'vie' | Should -BeFalse } finally { $script:CogesState.Simulation = $false }
        Should -Invoke Invoke-CogesPingRequest -Times 0
    }

    It 'TesterSupport : dit lequel a répondu, lève si l''un ne répond pas' {
        $paths = New-TestInstall
        Mock Write-Host { }
        Mock Invoke-CogesPingRequest { if ($Url -match 'maj-') { throw 'injoignable' } else { 200 } }
        { Invoke-CogesTestSupport -Paths $paths } | Should -Throw '*1 adresse(s) sans réponse*'
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match 'vie +: reçu par CoGes'
        $text | Should -Match 'mise-a-jour +: PAS de réponse'
        Should -Invoke Invoke-CogesPingRequest -ParameterFilter { $Body -match 'signal: test' -and $Url -notmatch '/fail$' } -Times 4
    }
}

Describe 'Le bon signal au bon moment (bloc B)' {
    BeforeEach {
        $script:Sent = New-Object Collections.ArrayList
        Mock Invoke-CogesPingRequest { [void]$script:Sent.Add([pscustomobject]@{ Url = $Url; Body = $Body }); 200 }
        Mock Invoke-Docker { Invoke-FakeDocker -Arguments $Arguments }
        Mock Show-CogesToast { $true }
        $script:UpCode = 0
    }

    It 'ouverture de session : « vie » après le démarrage ; /fail si up -d échoue ou si Docker se tait' {
        $paths = New-TestInstall
        Start-CogesAtLogon -Racine $paths.Racine -LockWaitSeconds 0 | Should -Be 0
        $script:Sent[-1].Url | Should -Match '/vie-a{24}$'
        $script:UpCode = 1
        Start-CogesAtLogon -Racine $paths.Racine -LockWaitSeconds 0 | Should -Be 1
        $script:Sent[-1].Url | Should -Match '/vie-a{24}/fail$'
        $script:Sent[-1].Body | Should -Match 'raison: demarrage'
        Start-CogesAtLogon -Racine $paths.Racine -TimeoutSeconds 0 | Should -Be 1
        $script:Sent[-1].Url | Should -Match '/vie-a{24}/fail$'
        $script:Sent[-1].Body | Should -Match 'raison: docker-arrete'
    }

    It 'un ping qui échoue ne change pas le code de l''ouverture de session' {
        $paths = New-TestInstall
        Mock Invoke-CogesPingRequest { throw 'Internet coupé' }
        Start-CogesAtLogon -Racine $paths.Racine -LockWaitSeconds 0 | Should -Be 0
    }

    It 'sauvegarde planifiée réussie : « vie » puis « sauvegarde »' {
        $paths = New-TestInstall
        Mock New-CogesBackup { [pscustomobject]@{ Name = 'x.coges'; Path = 'x'; Size = 1; Offsite = @() } }
        Invoke-CogesScheduledBackup -Racine $paths.Racine -Now (Get-Date).AddDays(2) | Should -Be 0
        @($script:Sent | ForEach-Object { ($_.Url -replace '^.*/ping/', '') -replace '-[abc]{24}', '' }) -join ',' | Should -Be 'vie,sauvegarde'
    }

    It 'sauvegarde planifiée ratée : /fail « sauvegarde » avec le code de la raison' {
        $paths = New-TestInstall
        Mock New-CogesBackup { Stop-CogesStep -Probleme 'Pas assez de place sur le disque (1,0 Go libres).' -QuoiFaire 'Libérez de la place.' }
        Invoke-CogesScheduledBackup -Racine $paths.Racine -Now (Get-Date).AddDays(2) | Should -Be 1
        $script:Sent[-1].Url | Should -Match '/sauvegarde-b{24}/fail$'
        $script:Sent[-1].Body | Should -Match 'raison: place-disque'
        $script:Sent[-1].Body | Should -Not -Match 'Libérez'
    }

    It 'Docker arrêté à l''heure d''une sauvegarde due : /fail « sauvegarde » docker-arrete' {
        $paths = New-TestInstall
        Mock Invoke-Docker { New-DockerResult 1 @('error during connect') }
        Invoke-CogesScheduledBackup -Racine $paths.Racine -Now (Get-Date).AddDays(2) | Should -Be 0
        $script:Sent[-1].Url | Should -Match '/sauvegarde-b{24}/fail$'
        $script:Sent[-1].Body | Should -Match 'raison: docker-arrete'
    }

    It 'rien à sauvegarder : « vie » seulement (un PC jamais éteint ne se tait pas)' {
        $paths = New-TestInstall
        Mock Test-CogesBackupDue { $false }
        Mock Test-CogesTrialDue { $false }
        Invoke-CogesScheduledBackup -Racine $paths.Racine | Should -Be 0
        $script:Sent.Count | Should -Be 1
        $script:Sent[0].Url | Should -Match '/vie-a{24}$'
    }

    It 'essai du dimanche raté : /fail « sauvegarde » essai-rate' {
        $paths = New-TestInstall
        Mock Test-CogesTrialDue { $true }
        Mock New-CogesBackup { Write-CogesBackupState -Paths $Paths -Changes @{ dernier_essai = (Get-Date).ToString('o'); dernier_essai_ok = $false }; [pscustomobject]@{ Name = 'x.coges'; Path = 'x'; Size = 1; Offsite = @() } }
        Invoke-CogesScheduledBackup -Racine $paths.Racine | Should -Be 0
        $script:Sent[-1].Url | Should -Match '/sauvegarde-b{24}/fail$'
        $script:Sent[-1].Body | Should -Match 'raison: essai-rate'
    }

    It 'une version prête depuis plus de 3 jours : /fail « mise-a-jour » une fois par jour' {
        $paths = New-TestInstall
        $now = Get-Date
        Send-CogesUpdateWaitPing -Paths $paths -Now $now | Should -BeTrue
        Send-CogesUpdateWaitPing -Paths $paths -Now $now | Should -BeFalse
        Send-CogesUpdateWaitPing -Paths $paths -Now $now.AddDays(1) | Should -BeTrue
        $script:Sent.Count | Should -Be 2
        $script:Sent[0].Url | Should -Match '/maj-c{24}/fail$'
        $script:Sent[0].Body | Should -Match 'raison: attente-3-jours'
    }

    It 'la mise à jour envoie « mise-a-jour » à la réussite, /fail au retour arrière et au retour raté' {
        $text = [IO.File]::ReadAllText((Join-Path (Split-Path -Parent $PSScriptRoot) 'CoGes.Install.ps1'))
        $start = $text.IndexOf('function Invoke-CogesUpdateLocked')
        $body = $text.Substring($start, $text.IndexOf('function Invoke-CogesUpdateCleanup') - $start)
        $body | Should -Match "Send-CogesPing -Paths \`$Paths -Signal 'mise-a-jour' -Failure -Reason 'retour-arriere'"
        $body | Should -Not -Match '\(lot 6\)'
        $body | Should -Match "Send-CogesPing -Paths \`$Paths -Signal 'mise-a-jour' -Failure -Reason 'retour-rate'"
        $body | Should -Match "Send-CogesPing -Paths \`$Paths -Signal 'mise-a-jour'\)"
    }
}

Describe 'Journaux bornés (bloc E)' {
    It 'supprime au-delà de 60 jours, plafonne le total, garde toujours le journal du jour' {
        $script:CogesState.LogPath = $null
        $folder = Join-Path $TestDrive 'journaux-rotation'
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        $now = Get-Date
        $make = {
            param($name, $days, $size)
            $file = Join-Path $folder $name
            [IO.File]::WriteAllBytes($file, (New-Object byte[] $size))
            (Get-Item -LiteralPath $file).LastWriteTime = $now.AddDays(-$days)
        }
        & $make 'sauvegarde-vieux.log' 61 10
        & $make 'installation-ancien.log' 30 400
        & $make 'mise-a-jour-moyen.log' 10 400
        & $make ('sauvegarde-{0}.log' -f $now.ToString('yyyyMMdd')) 0 2000
        $removed = Invoke-CogesLogRotation -Folder $folder -Now $now -MaxBytes 2500
        $removed | Should -Be 2
        Test-Path (Join-Path $folder 'sauvegarde-vieux.log') | Should -BeFalse
        Test-Path (Join-Path $folder 'installation-ancien.log') | Should -BeFalse
        Test-Path (Join-Path $folder 'mise-a-jour-moyen.log') | Should -BeTrue
        Test-Path (Join-Path $folder ('sauvegarde-{0}.log' -f $now.ToString('yyyyMMdd'))) | Should -BeTrue
        # Le journal du jour seul dépasse le plafond : gardé quand même.
        Invoke-CogesLogRotation -Folder $folder -Now $now -MaxBytes 100 | Should -Be 1
        Test-Path (Join-Path $folder ('sauvegarde-{0}.log' -f $now.ToString('yyyyMMdd'))) | Should -BeTrue
    }

    It 'un dossier absent ne lève pas' {
        Invoke-CogesLogRotation -Folder (Join-Path $TestDrive 'nulle-part') | Should -Be 0
    }
}

Describe 'Diagnostic (bloc C)' {
    BeforeEach {
        Mock Invoke-Docker { Invoke-FakeDocker -Arguments $Arguments }
        Mock Write-Host { }
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
    }

    It 'zip sur le Bureau : le contenu attendu, aucun secret, aucune adresse de ping, coges.env en noms seulement' {
        $paths = New-TestInstall -Url 'https://hc-ping.com'
        $desktop = Join-Path $TestDrive 'bureau-diag'
        $previous = $env:COGES_BUREAU_ESSAI
        $env:COGES_BUREAU_ESSAI = $desktop
        try { $zip = New-CogesDiagnostic -Paths $paths -Now (Get-Date -Year 2026 -Month 11 -Day 22 -Hour 9 -Minute 5) }
        finally { $env:COGES_BUREAU_ESSAI = $previous }
        Split-Path -Leaf $zip | Should -Be 'CoGes-diagnostic-20261122-0905.zip'
        Split-Path -Parent $zip | Should -Be $desktop
        (Get-Item $zip).Length | Should -BeLessThan 10MB
        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            $names = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
            foreach ($expected in @('etat.txt', 'resume.txt', 'docker.txt', 'reglages.txt', 'sauvegardes.txt', 'systeme.txt', 'services/api.log', 'services/postgres.log')) { $names | Should -Contain $expected }
            @($names | Where-Object { $_ -like 'journaux/*' }).Count | Should -BeGreaterThan 0
            $all = foreach ($entry in $archive.Entries) {
                $reader = New-Object IO.StreamReader ($entry.Open())
                try { $reader.ReadToEnd() } finally { $reader.Dispose() }
            }
            $text = $all -join "`n"
        }
        finally { $archive.Dispose() }
        foreach ($secret in $script:Secrets) { $text | Should -Not -Match ([regex]::Escape($secret)) }
        $text | Should -Not -Match 'hc-ping\.com'
        $text | Should -Not -Match ('a' * 24)
        $text | Should -Match 'COGES_APP_PASSWORD'
        $text | Should -Match '\*\*\*\*\*\*\*\*'
        $text | Should -Match 'format: COGES-RESUME-1'
        $text | Should -Match 'coges-keur-fatou-.*\.coges'
    }

    It 'plus de 10 Mo : journaux des services raccourcis (300, puis 100, puis 30 lignes)' {
        $paths = New-TestInstall
        # La taille du zip dépend de la machine (journaux, système) : on mesure le zip à 100 et à
        # 3 lignes, puis on place le plafond entre les deux, pour que seul le dernier passe.
        try {
            $script:CogesDiagnosticTails = @(100)
            $big = (Get-Item (New-CogesDiagnostic -Paths $paths -Destination (Join-Path $TestDrive 'mesure-100'))).Length
            $script:CogesDiagnosticTails = @(3)
            $small = (Get-Item (New-CogesDiagnostic -Paths $paths -Destination (Join-Path $TestDrive 'mesure-3'))).Length
            $small | Should -BeLessThan ($big - 2KB)
            $script:CogesDiagnosticMaxBytes = [long](($big + $small) / 2)
            $script:CogesDiagnosticTails = @(300, 100, 3)
            $zip = New-CogesDiagnostic -Paths $paths -Destination (Join-Path $TestDrive 'bureau-petit')
            $limit = $script:CogesDiagnosticMaxBytes
        }
        finally { $script:CogesDiagnosticMaxBytes = 10MB; $script:CogesDiagnosticTails = @(300, 100, 30) }
        (Get-Item $zip).Length | Should -BeLessOrEqual $limit
        Should -Invoke Invoke-Docker -ParameterFilter { ($Arguments -join ' ') -match '--tail 300 api' }
        Should -Invoke Invoke-Docker -ParameterFilter { ($Arguments -join ' ') -match '--tail 100 api' }
        Should -Invoke Invoke-Docker -ParameterFilter { ($Arguments -join ' ') -match '--tail 3 api' }
    }

    It '-Simulation : rien d''écrit, rien de lancé' {
        $racine = Join-Path $TestDrive 'simulation-diag'
        $previous = $env:COGES_BUREAU_ESSAI
        $env:COGES_BUREAU_ESSAI = Join-Path $TestDrive 'bureau-simulation'
        try { Invoke-CogesMain -Action Diagnostic -Racine $racine -Simulation | Should -Be 0 }
        finally { $env:COGES_BUREAU_ESSAI = $previous }
        Test-Path $racine | Should -BeFalse
        Test-Path (Join-Path $TestDrive 'bureau-simulation') | Should -BeFalse
        Should -Invoke Invoke-Docker -Times 0
        ($script:CogesState.Output -join "`n") | Should -Match '\[simulation\] zip de 10 Mo au plus sur le Bureau'
    }

    It 'coges.env réduit aux noms : jamais une valeur' {
        $names = ConvertTo-CogesEnvNameList "# commentaire`nCOGES_APP_PASSWORD=secret-de-test-123`nCOGES_HTTP_PORT=80`n"
        ($names -join ',') | Should -Be 'COGES_APP_PASSWORD,COGES_HTTP_PORT'
    }
}

Describe 'Raccourcis et aide (blocs D et F)' {
    It 'pose « Aide CoGes » et « Diagnostic CoGes », puis les retire ; support.json reste' {
        $paths = New-TestInstall
        $desktop = Join-Path $TestDrive 'bureau-raccourcis'
        $previous = $env:COGES_BUREAU_ESSAI
        $env:COGES_BUREAU_ESSAI = $desktop
        Mock Write-Host { }
        try {
            Install-CogesSupportShortcut -Paths $paths
            $help = [IO.File]::ReadAllText((Join-Path $desktop 'Aide CoGes.cmd'))
            $help | Should -Match '-Action Aide -Bureau'
            $help | Should -Match ([regex]::Escape((Join-Path $paths.Programme 'windows\installer.ps1')))
            [IO.File]::ReadAllText((Join-Path $desktop 'Diagnostic CoGes.cmd')) | Should -Match '-Action Diagnostic -Bureau'
            Remove-CogesSupportShortcut
            Test-Path (Join-Path $desktop 'Aide CoGes.cmd') | Should -BeFalse
            Test-Path (Join-Path $desktop 'Diagnostic CoGes.cmd') | Should -BeFalse
            Test-Path (Get-CogesSupportPath $paths).Reglage | Should -BeTrue
        }
        finally { $env:COGES_BUREAU_ESSAI = $previous }
    }

    It 'en simulation, les raccourcis sont annoncés, pas posés' {
        $paths = Get-CogesPath (Join-Path $TestDrive 'simulation-raccourcis')
        $desktop = Join-Path $TestDrive 'bureau-sim-raccourcis'
        $previous = $env:COGES_BUREAU_ESSAI
        $env:COGES_BUREAU_ESSAI = $desktop
        Mock Write-Host { }
        $script:CogesState.Simulation = $true
        try { Install-CogesSupportShortcut -Paths $paths }
        finally { $script:CogesState.Simulation = $false; $env:COGES_BUREAU_ESSAI = $previous }
        Test-Path $desktop | Should -BeFalse
    }

    It 'Aide : le numéro de CoGes et trois phrases ; rien installé' {
        $lines = Get-CogesHelpText '+221 77 000 00 00'
        $lines.Count | Should -Be 3
        $lines[0] | Should -Be 'Appelez CoGes au +221 77 000 00 00.'
        $lines[1] | Should -Match 'code'
        $lines[2] | Should -Match 'Acceptez'
        (Get-CogesHelpText '')[0] | Should -Be 'Appelez CoGes.'
        $text = [IO.File]::ReadAllText((Join-Path (Split-Path -Parent $PSScriptRoot) 'CoGes.Install.ps1'))
        $text | Should -Not -Match '(?i)rustdesk|teamviewer|anydesk|winget install|Add-AppxPackage'
    }

    It 'aucun port ouvert ni service qui écoute dans le script (toujours sortant)' {
        $text = [IO.File]::ReadAllText((Join-Path (Split-Path -Parent $PSScriptRoot) 'CoGes.Install.ps1'))
        $text | Should -Not -Match '\b(HttpListener|TcpListener|New-NetFirewallRule|netsh)\b'
    }
}
