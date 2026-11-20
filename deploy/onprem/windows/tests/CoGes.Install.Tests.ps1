# Tests Pester 5 du script d'installation Windows (ADR 0126).
#
# Joués par le workflow « Sur site » sous Linux (pwsh) et sous Windows (Windows PowerShell
# 5.1 ET pwsh). Docker n'est jamais appelé : Invoke-Docker est remplacé quand un test en a
# besoin, et la simulation le refuse d'elle-même.
#
#   Invoke-Pester -Path deploy/onprem/windows/tests

BeforeAll {
    $windows = Split-Path -Parent $PSScriptRoot
    $onprem = Split-Path -Parent $windows
    $script:Onprem = $onprem
    . (Join-Path $windows 'CoGes.Install.ps1')
    $script:Model = [IO.File]::ReadAllText((Join-Path $onprem 'coges.env.example'))
    $script:Checker = Join-Path $onprem 'check_onprem_env.py'
    $script:IsWin = ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)

    function Get-TestPython {
        $candidates = @('python3', 'python')
        if ($script:IsWin) { $candidates = @('python', 'python3') }
        foreach ($candidate in $candidates) {
            if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
            $previous = $ErrorActionPreference
            $ErrorActionPreference = 'Continue'
            try { $major = & $candidate -c 'import sys; print(sys.version_info[0])' 2>$null } catch { $major = $null }
            finally { $ErrorActionPreference = $previous }
            if ($LASTEXITCODE -eq 0 -and "$major".Trim() -eq '3') { return $candidate }
        }
        return $null
    }

    function New-TestEnvFile {
        param([string] $Folder, [int] $Port = 80, [string] $Version = 'v1.2.3')
        New-Item -ItemType Directory -Force -Path $Folder | Out-Null
        $values = New-CogesSecretSet
        $values['COGES_IMAGE_TAG'] = $Version
        $values['COGES_HTTP_PORT'] = [string]$Port
        $values['COGES_PUBLIC_URL'] = Get-CogesPublicUrl $Port
        $path = Join-Path $Folder 'coges.env'
        Write-CogesEnvFile -Path $path -Text (ConvertTo-CogesEnvText -Model $script:Model -Values $values)
        return $path
    }

    function Invoke-TestChecker {
        param([string] $Path)
        $python = Get-TestPython
        $previous = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try { $output = @(& $python $script:Checker --env-file $Path 2>&1 | ForEach-Object { [string]$_ }) }
        finally { $ErrorActionPreference = $previous }
        return [pscustomobject]@{ ExitCode = $LASTEXITCODE; Output = ($output -join "`n") }
    }

    function New-DockerResult {
        param([int] $Code, [string[]] $Lines)
        [pscustomobject]@{ ExitCode = $Code; Output = $Lines; Stdout = $Lines }
    }

    $script:Answers = @{
        NomBoutique = 'Boutique Diallo'; CodeBoutique = 'boutique-diallo'; NomGerant = 'Awa Diallo'
        TelephoneGerant = '77 123 45 67'; EmailGerant = ''; Offre = 'business'
        NoteContrat = "Contrat du 17/11/2026, maintenance jusqu'au 17/11/2027"
    }
}

Describe 'Secrets tirés au hasard' {
    It 'un mot de passe : 64 caractères hexadécimaux, jamais deux fois le même' {
        $first = New-CogesHexSecret
        $second = New-CogesHexSecret
        $first | Should -MatchExactly '^[0-9a-f]{64}$'
        $second | Should -MatchExactly '^[0-9a-f]{64}$'
        $first | Should -Not -Be $second
    }

    It 'la clé de chiffrement : 43 caractères base64 url-safe, 32 octets' {
        $key = New-CogesMfaKey
        $key | Should -MatchExactly '^[A-Za-z0-9_-]{43}$'
        $padded = $key.Replace('-', '+').Replace('_', '/') + '='
        [Convert]::FromBase64String($padded).Length | Should -Be 32
    }

    It 'le jeu : les huit mots de passe tous différents et la clé' {
        $set = New-CogesSecretSet
        $set.Count | Should -Be 9
        $passwords = @($script:CogesSecretKeys | ForEach-Object { $set[$_] })
        @($passwords | Sort-Object -Unique).Count | Should -Be 8
        $set['COGES_MFA_ENCRYPTION_KEY'].Length | Should -Be 43
        (New-CogesSecretSet)['COGES_JWT_SECRET'] | Should -Not -Be $set['COGES_JWT_SECRET']
    }

    It 'aucun tirage par Get-Random' {
        $code = [IO.File]::ReadAllText((Join-Path (Split-Path -Parent $PSScriptRoot) 'CoGes.Install.ps1'))
        $code | Should -Not -Match 'Get-Random'
        $code | Should -Match 'RandomNumberGenerator'
    }
}

Describe 'Fichier de réglages' {
    It 'UTF-8 sans BOM, fins de ligne LF, port et adresse concordants' {
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive 'a') -Port 8080
        $bytes = [IO.File]::ReadAllBytes($path)
        ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB) | Should -BeFalse
        [Array]::IndexOf($bytes, [byte]13) | Should -Be -1
        $values = Read-CogesEnvFile $path
        $values['COGES_HTTP_PORT'] | Should -Be '8080'
        $values['COGES_PUBLIC_URL'] | Should -Be 'http://localhost:8080'
        $values['COGES_IMAGE_TAG'] | Should -Be 'v1.2.3'
        $values['COGES_IMAGE_REGISTRY'] | Should -Be 'ghcr.io/papa-bothie/coges'
    }

    It 'le port 80 va avec http://localhost' {
        (Read-CogesEnvFile (New-TestEnvFile -Folder (Join-Path $TestDrive 'b')))['COGES_PUBLIC_URL'] | Should -Be 'http://localhost'
    }

    It 'garde les commentaires du modèle' {
        $text = [IO.File]::ReadAllText((New-TestEnvFile -Folder (Join-Path $TestDrive 'c')))
        $text | Should -Match '1\. À REMPLIR'
        $text | Should -Match 'NE PAS TOUCHER'
    }

    It 'n''écrase jamais un fichier existant' {
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive 'd')
        $before = [IO.File]::ReadAllText($path)
        { Write-CogesEnvFile -Path $path -Text "COGES_IMAGE_TAG=v9.9.9`n" } | Should -Throw
        [IO.File]::ReadAllText($path) | Should -Be $before
    }

    It 'refuse un modèle sans la ligne d''un réglage' {
        { ConvertTo-CogesEnvText -Model "COGES_IMAGE_TAG=`n" -Values ([ordered]@{ COGES_JWT_SECRET = 'x' }) } | Should -Throw
    }

    It 'relu par le vrai check_onprem_env.py : OK (port <port>)' -ForEach @(@{ Port = 80 }, @{ Port = 8080 }) {
        if (-not (Get-TestPython)) { Set-ItResult -Skipped -Because 'Python 3 absent' ; return }
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive ('check-' + $Port)) -Port $Port
        $result = Invoke-TestChecker $path
        $result.Output | Should -Match '^OK'
        $result.ExitCode | Should -Be 0
    }

    It 'le contrôle refuse un port et une adresse qui ne vont pas ensemble (témoin)' {
        if (-not (Get-TestPython)) { Set-ItResult -Skipped -Because 'Python 3 absent' ; return }
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive 'temoin') -Port 8080
        Set-CogesEnvValue -Path $path -Values ([ordered]@{ COGES_PUBLIC_URL = 'http://localhost' })
        $result = Invoke-TestChecker $path
        $result.ExitCode | Should -Be 1
        $result.Output | Should -Match 'REFUS'
    }

    It 'ne change que le port, l''adresse et la version' {
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive 'e')
        $before = Read-CogesEnvFile $path
        Set-CogesEnvValue -Path $path -Values ([ordered]@{ COGES_HTTP_PORT = '8081'; COGES_PUBLIC_URL = 'http://localhost:8081'; COGES_IMAGE_TAG = 'v1.3.0' })
        $after = Read-CogesEnvFile $path
        $after['COGES_HTTP_PORT'] | Should -Be '8081'
        $after['COGES_IMAGE_TAG'] | Should -Be 'v1.3.0'
        foreach ($key in $script:CogesSecretKeys) { $after[$key] | Should -Be $before[$key] }
        { Set-CogesEnvValue -Path $path -Values ([ordered]@{ COGES_JWT_SECRET = 'abc' }) } | Should -Throw
        (Read-CogesEnvFile $path)['COGES_JWT_SECRET'] | Should -Be $before['COGES_JWT_SECRET']
    }

    It 'garde les fins de ligne d''un fichier enregistré par le Bloc-notes (CRLF)' {
        $path = Join-Path $TestDrive 'notepad.env'
        [IO.File]::WriteAllText($path, "# note`r`nCOGES_IMAGE_TAG=v1.0.0`r`nCOGES_HTTP_PORT=80`r`n")
        Set-CogesEnvValue -Path $path -Values ([ordered]@{ COGES_IMAGE_TAG = 'v1.1.0' })
        [IO.File]::ReadAllText($path) | Should -Be "# note`r`nCOGES_IMAGE_TAG=v1.1.0`r`nCOGES_HTTP_PORT=80`r`n"
    }

    It 'les droits du fichier : ce compte, SYSTEM et Administrateurs seulement (Windows)' {
        if (-not $script:IsWin) { Set-ItResult -Skipped -Because 'icacls : Windows seulement' ; return }
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive 'acl')
        Set-CogesPrivateAcl $path
        $acl = Get-Acl -LiteralPath $path
        $acl.AreAccessRulesProtected | Should -BeTrue
        $sids = @($acl.Access | ForEach-Object { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } | Sort-Object -Unique)
        $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $expected = @($me, 'S-1-5-18', 'S-1-5-32-544') | Sort-Object -Unique
        ($sids -join ',') | Should -Be ($expected -join ',')
    }
}

Describe 'Choix du port' {
    It '80 libre : 80' { Select-CogesPort -Listening @(135, 445) | Should -Be 80 }
    It '80 pris : 8080' { Select-CogesPort -Listening @(80, 443) | Should -Be 8080 }
    It '80 et 8080 pris : le premier libre au-dessus' { Select-CogesPort -Listening @(80, 8080, 8081) | Should -Be 8082 }
    It '-Port l''emporte' { Select-CogesPort -Requested 9000 -Listening @(80) | Should -Be 9000 }
    It 'l''adresse suit le port' {
        Get-CogesPublicUrl 80 | Should -Be 'http://localhost'
        Get-CogesPublicUrl 8080 | Should -Be 'http://localhost:8080'
    }
}

Describe 'Validations' {
    It 'version <value> refusée' -ForEach @(@{ Value = '' }, @{ Value = 'latest' }, @{ Value = 'v1.4' }, @{ Value = '1.4.0' }, @{ Value = 'V1.4.0' }, @{ Value = 'v1.4.0-rc1' }) {
        Test-CogesVersion $Value | Should -BeFalse
        { Assert-CogesVersion $Value } | Should -Throw
    }
    It 'version v1.4.0 acceptée' { Test-CogesVersion 'v1.4.0' | Should -BeTrue }

    It 'code de boutique <value> : <ok>' -ForEach @(
        @{ Value = 'boutique-diallo'; Ok = $true }, @{ Value = 'b2'; Ok = $true },
        @{ Value = 'Boutique'; Ok = $false }, @{ Value = 'boutique--diallo'; Ok = $false },
        @{ Value = '-boutique'; Ok = $false }, @{ Value = 'boutique_diallo'; Ok = $false }, @{ Value = ''; Ok = $false }
    ) {
        Test-CogesSlug $Value | Should -Be $Ok
    }

    It 'le code proposé à partir du nom' {
        ConvertTo-CogesSlug 'Boutique Diallo & Fils' | Should -Be 'boutique-diallo-fils'
        ConvertTo-CogesSlug '  Épicerie Ndèye  ' | Should -Be 'epicerie-ndeye'
        Test-CogesSlug (ConvertTo-CogesSlug 'Quincaillerie « Le Bon Prix » n°2') | Should -BeTrue
    }

    It 'l''offre, en minuscules seulement' {
        Test-CogesPlan 'business' | Should -BeTrue
        Test-CogesPlan 'Business' | Should -BeFalse
        Test-CogesPlan 'gold' | Should -BeFalse
    }

    It 'un texte sans guillemet double ni retour à la ligne' {
        Test-CogesText 'Contrat du 17/11/2026' -Max 500 | Should -BeTrue
        Test-CogesText 'dit "bonjour"' | Should -BeFalse
        Test-CogesText "deux`nlignes" | Should -BeFalse
        Test-CogesText ('x' * 501) -Max 500 | Should -BeFalse
    }
}

Describe 'Journal sans secret' {
    It 'Mask-Secrets retire les valeurs de coges.env' {
        $secret = New-CogesHexSecret
        Mask-Secrets -Line ('postgresql://coges_app:' + $secret + '@postgres') -Values @($secret) | Should -Be 'postgresql://coges_app:********@postgres'
        Mask-Secrets -Line 'rien à cacher' -Values @($secret) | Should -Be 'rien à cacher'
        Mask-Secrets -Line 'un mot court' -Values @('court') | Should -Be 'un mot court'
    }

    It 'Write-Log n''écrit jamais une valeur lue dans coges.env' {
        $path = New-TestEnvFile -Folder (Join-Path $TestDrive 'log')
        $values = Read-CogesEnvFile $path
        $script:CogesState.Simulation = $false
        $script:CogesState.MaskValues = Get-CogesMaskValue $values
        $script:CogesState.LogPath = Join-Path $TestDrive 'installation.log'
        try {
            Write-Log -Message ('JWT=' + $values['COGES_JWT_SECRET'] + ' MFA=' + $values['COGES_MFA_ENCRYPTION_KEY'])
            Write-CogesLine ('docker : ' + $values['COGES_APP_PASSWORD']) 6>$null
        }
        finally { $script:CogesState.LogPath = $null }
        $log = [IO.File]::ReadAllText((Join-Path $TestDrive 'installation.log'))
        foreach ($key in @($script:CogesSecretKeys) + 'COGES_MFA_ENCRYPTION_KEY') {
            $log.Contains($values[$key]) | Should -BeFalse
        }
        $log | Should -Match 'JWT=\*{8}'
    }
}

Describe 'PATH de l''utilisateur' {
    It 'ajoute le dossier une seule fois' {
        $once = Add-CogesPathEntry -PathValue 'C:\Windows;%USERPROFILE%\bin' -Directory 'C:\CoGes\bin'
        $once | Should -Be 'C:\Windows;%USERPROFILE%\bin;C:\CoGes\bin'
        Add-CogesPathEntry -PathValue $once -Directory 'C:\CoGes\bin' | Should -Be $once
        Add-CogesPathEntry -PathValue 'c:\coges\bin\;C:\Windows' -Directory 'C:\CoGes\bin' | Should -Be 'c:\coges\bin\;C:\Windows'
        Add-CogesPathEntry -PathValue '' -Directory 'C:\CoGes\bin' | Should -Be 'C:\CoGes\bin'
    }
    It 'retire le dossier sans toucher au reste' {
        Remove-CogesPathEntry -PathValue 'C:\Windows;C:\CoGes\bin;%USERPROFILE%\bin' -Directory 'C:\CoGes\bin' | Should -Be 'C:\Windows;%USERPROFILE%\bin'
    }
}

Describe 'Lectures de docker et de la CLI' {
    It 'docker compose ps : une ligne JSON par conteneur' {
        $lines = @(
            '{"Service":"api","State":"running","Health":"healthy"}',
            '{"Service":"autoheal","State":"running","Health":""}'
        )
        $items = @(ConvertFrom-CogesComposeStatus $lines)
        $items.Count | Should -Be 2
        $items[0].Service | Should -Be 'api'
    }

    It 'docker compose ps : un tableau JSON (anciennes versions)' {
        $items = @(ConvertFrom-CogesComposeStatus @('[{"Service":"api","State":"running","Health":"starting"},{"Service":"redis","State":"running"}]'))
        $items.Count | Should -Be 2
        $items[1].Health | Should -Be ''
    }

    It 'les services en attente : absents, arrêtés, pas encore « healthy »' {
        $ready = foreach ($service in $script:CogesServices) { [pscustomobject]@{ Service = $service; State = 'running'; Health = 'healthy' } }
        @(Get-CogesWaitingService $ready).Count | Should -Be 0
        $partial = @($ready | Where-Object { $_.Service -ne 'beat' }) + [pscustomobject]@{ Service = 'beat'; State = 'running'; Health = 'starting' }
        (@(Get-CogesWaitingService $partial) -join ',') | Should -Be 'beat'
        @(Get-CogesWaitingService @()).Count | Should -Be 9
    }

    It 'licence relue : actif et sans fin' {
        $ok = @('Entreprise       : Boutique Diallo (boutique-diallo)', 'Accès            : actif', 'Fin de période   : sans fin')
        Test-CogesLicenseActive $ok | Should -BeTrue
        Test-CogesLicenseActive @('Accès            : essai', 'Fin de période   : sans fin') | Should -BeFalse
        Test-CogesLicenseActive @('Accès            : actif', 'Fin de période   : 17/12/2026') | Should -BeFalse
    }

    It 'société inconnue : code 3 ou « Entreprise introuvable »' {
        Test-CogesCompanyMissing -ExitCode 3 -Lines @() | Should -BeTrue
        Test-CogesCompanyMissing -ExitCode 1 -Lines @('Entreprise introuvable : « x »') | Should -BeTrue
        Test-CogesCompanyMissing -ExitCode 1 -Lines @('could not connect') | Should -BeFalse
    }

    It 'docker version : accès refusé, moteur éteint, autre' {
        Get-CogesDockerProblem @('permission denied while trying to connect to the Docker daemon socket') | Should -Be 'acces'
        Get-CogesDockerProblem @('error during connect: open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.') | Should -Be 'eteint'
        Get-CogesDockerProblem @('quelque chose') | Should -Be 'autre'
    }

    It 'port pris au démarrage' {
        Test-CogesPortInUseError @('Error response from daemon: Ports are not available: exposing port TCP 127.0.0.1:80') | Should -BeTrue
        Test-CogesPortInUseError @('Bind for 127.0.0.1:80 failed: port is already allocated') | Should -BeTrue
        Test-CogesPortInUseError @('no such image') | Should -BeFalse
    }

    It 'Docker Desktop : « Start when you sign in » lu sans rien inventer' {
        Get-CogesDockerAutoStart '{"AutoStart": true}' | Should -BeTrue
        Get-CogesDockerAutoStart '{"autoStart": false}' | Should -BeFalse
        Get-CogesDockerAutoStart '{"other": 1}' | Should -BeNullOrEmpty
        Get-CogesDockerAutoStart 'pas du json' | Should -BeNullOrEmpty
        Get-CogesDockerAutoStart $null | Should -BeNullOrEmpty
    }
}

Describe 'Ligne de commande passée à docker' {
    It 'chaque argument reste entier' {
        ConvertTo-CogesCommandLine @('compose', '--env-file', 'C:\CoGes\reglages\coges.env') | Should -Be 'compose --env-file C:\CoGes\reglages\coges.env'
        ConvertTo-CogesCommandLine @('--name', 'Boutique Diallo') | Should -Be '--name "Boutique Diallo"'
        ConvertTo-CogesCommandLine @('--note', "maintenance jusqu'au 17/11/2027") | Should -Be "--note `"maintenance jusqu'au 17/11/2027`""
        ConvertTo-CogesCommandLine @('') | Should -Be '""'
        ConvertTo-CogesCommandLine @("N'Diaye") | Should -Be "`"N'Diaye`""
        ConvertTo-CogesCommandLine @('a "b"') | Should -Be '"a \"b\""'
        ConvertTo-CogesCommandLine @('C:\dos sier\') | Should -Be '"C:\dos sier\\"'
    }

    It 'bin\coges.cmd : la fonction coges du guide, arguments transmis' {
        $text = New-CogesCmdText -EnvFile 'C:\CoGes\reglages\coges.env' -Compose 'C:\CoGes\programme\docker-compose.yml'
        $text | Should -Match 'docker compose --env-file "C:\\CoGes\\reglages\\coges.env" -f "C:\\CoGes\\programme\\docker-compose.yml" %\*'
        $text | Should -Match '^@echo off'
    }

    It 'raccourci du Bureau vers l''adresse' {
        New-CogesShortcutText 'http://localhost:8080' | Should -Match 'URL=http://localhost:8080/'
    }
}

Describe 'Société et licence (docker remplacé)' {
    BeforeEach {
        $script:CogesState.Simulation = $false
        $script:CogesState.LogPath = $null
        $script:Calls = New-Object System.Collections.Generic.List[object]
        $script:Paths = Get-CogesPath (Join-Path $TestDrive 'coges')
        $script:Given = [pscustomobject]$script:Answers
    }

    It 'jamais --password dans create-company' {
        $arguments = Get-CogesCompanyArgument $script:Given
        $arguments | Should -Not -Contain '--password'
        ($arguments -join ' ') | Should -Match 'create-company --name Boutique Diallo --slug boutique-diallo --manager-name Awa Diallo --manager-phone 77 123 45 67'
        ($arguments -join ' ') | Should -Match 'run --rm -e PYTHONWARNINGS=error::getpass.GetPassWarning cli create-company'
    }

    It 'conteneur sans terminal : arrêt GetPassWarning, create-company jamais lancé' {
        Mock Assert-CogesConsole {}
        Mock Invoke-Docker {
            $script:Calls.Add($Arguments)
            if ($Arguments -contains 'license-status') { return New-DockerResult 3 @('Entreprise introuvable : boutique-diallo') }
            New-DockerResult 1 @()
        }
        { New-CogesCompany -Paths $script:Paths -Answers $script:Given 6>$null } | Should -Throw '*GetPassWarning*'
        ($script:Calls | Where-Object { $_ -contains 'create-company' }) | Should -BeNullOrEmpty
        ($script:Calls[1] -join ' ') | Should -Match 'run --rm --entrypoint test cli -t 0'
    }

    It 'GetPassWarning dans create-company : un seul essai, aucun repli' {
        Mock Assert-CogesConsole {}
        Mock Invoke-Docker {
            $script:Calls.Add($Arguments)
            if ($Arguments -contains 'license-status') { return New-DockerResult 3 @('Entreprise introuvable : boutique-diallo') }
            if ($Arguments -contains 'create-company') { return New-DockerResult 1 @() }
            New-DockerResult 0 @()
        }
        { New-CogesCompany -Paths $script:Paths -Answers $script:Given 6>$null } | Should -Throw '*GetPassWarning*'
        @($script:Calls | Where-Object { $_ -contains 'create-company' }).Count | Should -Be 1
        foreach ($call in $script:Calls) { $call | Should -Not -Contain '--password' }
    }

    It 'société déjà créée : rien n''est créé, « on continue »' {
        Mock Invoke-Docker {
            $script:Calls.Add($Arguments)
            New-DockerResult 0 @('Accès            : actif')
        }
        New-CogesCompany -Paths $script:Paths -Answers $script:Given 6>$null
        $script:Calls.Count | Should -Be 1
        ($script:Calls[0] -join ' ') | Should -Match 'license-status --slug boutique-diallo'
        ($script:CogesState.Output -join "`n") | Should -Match 'déjà créée, on continue'
    }

    It 'une erreur de lecture n''est pas prise pour « introuvable »' {
        Mock Invoke-Docker { New-DockerResult 1 @('could not connect to server') }
        { New-CogesCompany -Paths $script:Paths -Answers $script:Given 6>$null } | Should -Throw '*license-status*'
        Should -Invoke Invoke-Docker -Times 1 -Exactly
    }

    It 'licence : « rien à faire » est un succès' {
        Mock Invoke-Docker {
            if ($Arguments -contains 'activate-license') {
                return New-DockerResult 0 @('Licence déjà active, offre business : rien à faire.')
            }
            New-DockerResult 0 @('Accès            : actif', 'Fin de période   : sans fin')
        }
        { Set-CogesLicense -Paths $script:Paths -Answers $script:Given 6>$null } | Should -Not -Throw
        Should -Invoke Invoke-Docker -Times 2 -Exactly
    }

    It 'licence relue sans « sans fin » : échec' {
        Mock Invoke-Docker { New-DockerResult 0 @('Accès            : actif', 'Fin de période   : 01/01/2027') }
        { Set-CogesLicense -Paths $script:Paths -Answers $script:Given 6>$null } | Should -Throw '*sans fin*'
    }

    It 'attente des services : le service en cause et ses journaux, puis échec' {
        Mock Invoke-Docker {
            if ($Arguments -contains 'logs') { return New-DockerResult 0 @('api  | COGES_JWT_SECRET manque') }
            $running = foreach ($service in $script:CogesServices) {
                $health = 'healthy'
                if ($service -eq 'api') { $health = 'unhealthy' }
                '{"Service":"' + $service + '","State":"running","Health":"' + $health + '"}'
            }
            New-DockerResult 0 $running
        }
        { Wait-CogesHealthy -Paths $script:Paths -TimeoutSeconds 1 -IntervalSeconds 1 6>$null } | Should -Throw '*api*'
        Should -Invoke Invoke-Docker -ParameterFilter { $Arguments -contains 'logs' -and $Arguments -contains '40' -and $Arguments -contains 'api' }
    }
}

Describe 'Pose du programme' {
    BeforeAll {
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        function New-TestArchive {
            param([string] $Path, [hashtable] $Files)
            $zip = [IO.Compression.ZipFile]::Open($Path, [IO.Compression.ZipArchiveMode]::Create)
            try {
                foreach ($name in $Files.Keys) {
                    $entry = $zip.CreateEntry($name)
                    $writer = New-Object IO.StreamWriter ($entry.Open(), (New-Object Text.UTF8Encoding $false))
                    try { $writer.Write($Files[$name]) } finally { $writer.Dispose() }
                }
            }
            finally { $zip.Dispose() }
        }
        $script:Good = @{
            'CoGes-1.2.3/README.md'                                    = 'le reste du dépôt'
            'CoGes-1.2.3/backend/app/cli.py'                           = 'print()'
            'CoGes-1.2.3/deploy/onprem/docker-compose.yml'             = "name: coges-onprem`n"
            'CoGes-1.2.3/deploy/onprem/Caddyfile'                      = "http://localhost {`n}`n"
            'CoGes-1.2.3/deploy/onprem/maintenance.html'               = "<p>x</p>`n"
            'CoGes-1.2.3/deploy/onprem/coges.env.example'              = "COGES_IMAGE_TAG=`n"
            'CoGes-1.2.3/deploy/onprem/check_onprem_env.py'            = "print('OK')`n"
            'CoGes-1.2.3/deploy/onprem/postgres-init/01-roles.sql'     = "CREATE ROLE x;`n"
            'CoGes-1.2.3/deploy/onprem/windows/installer.ps1'          = "# installeur`n"
            'CoGes-1.2.3/deploy/onprem/windows/sauvegarde.ps1'         = "# tâche de sauvegarde`n"
            'CoGes-1.2.3/deploy/onprem/sauvegarde/pg.sh'               = "#!/bin/sh`n"
            'CoGes-1.2.3/deploy/onprem/sauvegarde/coffre.py'           = "print()`n"
            'CoGes-1.2.3/deploy/onprem/sauvegarde/base.py'             = "print()`n"
            'CoGes-1.2.3/deploy/onprem/sauvegarde/verify_restore.py'   = "print()`n"
            'CoGes-1.2.3/deploy/onprem/__pycache__/check.cpython-312.pyc' = 'binaire'
        }
    }

    It 'ne pose que deploy/onprem, avec sa version, sans toucher aux réglages' {
        $racine = Join-Path $TestDrive 'pose'
        $reglages = Join-Path $racine 'reglages'
        New-Item -ItemType Directory -Force -Path $reglages | Out-Null
        [IO.File]::WriteAllText((Join-Path $reglages 'coges.env'), "garde`n")
        $old = Join-Path $racine 'programme'
        New-Item -ItemType Directory -Force -Path $old | Out-Null
        [IO.File]::WriteAllText((Join-Path $old 'ancien.txt'), 'x')
        $archive = Join-Path $TestDrive 'bon.zip'
        New-TestArchive -Path $archive -Files $script:Good
        $count = Install-Programme -Archive $archive -Racine $racine -Version 'v1.2.3'
        $count | Should -Be 12
        $paths = Get-CogesPath $racine
        Test-CogesProgramme -Paths $paths -Version 'v1.2.3' | Should -BeTrue
        Test-CogesProgramme -Paths $paths -Version 'v1.2.4' | Should -BeFalse
        Test-Path (Join-Path $old 'ancien.txt') | Should -BeFalse
        Test-Path (Join-Path $old 'README.md') | Should -BeFalse
        Test-Path (Join-Path $old '__pycache__') | Should -BeFalse
        Test-Path (Join-Path (Join-Path $old 'windows') 'installer.ps1') | Should -BeTrue
        [IO.File]::ReadAllText((Join-Path $reglages 'coges.env')) | Should -Be "garde`n"
        (@(Get-ChildItem -LiteralPath $racine -Directory | ForEach-Object { $_.Name } | Sort-Object) -join ',') | Should -Be 'programme,reglages'
    }

    It 'refuse un Caddyfile en CRLF et garde l''ancien programme' {
        $racine = Join-Path $TestDrive 'crlf'
        $archive = Join-Path $TestDrive 'bon2.zip'
        New-TestArchive -Path $archive -Files $script:Good
        Install-Programme -Archive $archive -Racine $racine -Version 'v1.2.3' | Out-Null
        $bad = @{} + $script:Good
        $bad['CoGes-1.2.3/deploy/onprem/Caddyfile'] = "http://localhost {`r`n}`r`n"
        $archiveBad = Join-Path $TestDrive 'crlf.zip'
        New-TestArchive -Path $archiveBad -Files $bad
        { Install-Programme -Archive $archiveBad -Racine $racine -Version 'v1.2.4' } | Should -Throw '*CRLF*'
        Get-CogesInstalledVersion (Get-CogesPath $racine) | Should -Be 'v1.2.3'
        (@(Get-ChildItem -LiteralPath $racine -Directory | ForEach-Object { $_.Name }) -join ',') | Should -Be 'programme'
    }

    It 'refuse une archive sans docker-compose.yml' {
        $bad = @{} + $script:Good
        $bad.Remove('CoGes-1.2.3/deploy/onprem/docker-compose.yml')
        $archive = Join-Path $TestDrive 'incomplet.zip'
        New-TestArchive -Path $archive -Files $bad
        { Install-Programme -Archive $archive -Racine (Join-Path $TestDrive 'incomplet') -Version 'v1.2.3' } | Should -Throw '*docker-compose.yml*'
    }
}

Describe 'Point d''entrée' {
    BeforeEach {
        $script:Racine = Join-Path $TestDrive ('racine-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
        Mock Invoke-Docker { throw 'docker ne doit pas être appelé ici' }
    }

    It 'Installer en simulation : chaque étape annoncée, rien d''écrit dans -Racine' {
        $given = @{} + $script:Answers
        $code = Invoke-CogesMain -Action Installer -Version 'v1.2.3' -Racine $script:Racine -Simulation -NonInteractif @given 6>$null
        $code | Should -Be 0
        Test-Path -LiteralPath $script:Racine | Should -BeFalse
        Should -Invoke Invoke-Docker -Times 0 -Exactly
        $out = $script:CogesState.Output -join "`n"
        foreach ($step in @(
                'Contrôle du PC', 'Contrôle de Docker Desktop', 'Contrôle d''Internet', 'Contrôle de la version v1.2.3',
                'licence sur site dans cette version', 'Pose du programme v1.2.3', 'Choix du port', 'création de',
                'COPIE-FAITE', 'Téléchargement des images', 'Contrôle des réglages', 'migrations', 'Démarrage de CoGes',
                'Société boutique-diallo', 'Licence business', 'Dernier contrôle', 'Commande « coges »',
                'Raccourci « CoGes »', 'Tâche planifiée', 'Clé de sauvegarde', 'CoGes - sauvegarde', 'Première sauvegarde',
                'clé USB de sauvegarde', 'Simulation terminée')) {
            $out | Should -BeLike ('*' + $step + '*')
        }
    }

    It '<action> en simulation : rien d''écrit dans -Racine' -ForEach @(@{ Action = 'Reparer' }, @{ Action = 'Etat' }, @{ Action = 'Desinstaller' }) {
        $code = Invoke-CogesMain -Action $Action -Version 'v1.2.3' -Racine $script:Racine -Simulation -NonInteractif -CodeBoutique 'boutique-diallo' 6>$null
        $code | Should -Be 0
        Test-Path -LiteralPath $script:Racine | Should -BeFalse
        Should -Invoke Invoke-Docker -Times 0 -Exactly
    }

    It 'sans -Version : échec clair, rien d''écrit' -ForEach @(@{ Version = '' }, @{ Version = 'latest' }, @{ Version = 'v1.4' }) {
        $given = @{} + $script:Answers
        $code = Invoke-CogesMain -Action Installer -Version $Version -Racine $script:Racine -NonInteractif @given 6>$null
        $code | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match 'vX\.Y\.Z'
        Test-Path -LiteralPath $script:Racine | Should -BeFalse
    }

    It '-NonInteractif refuse une réponse manquante (<missing>)' -ForEach @(@{ Missing = 'NomBoutique' }, @{ Missing = 'Offre' }, @{ Missing = 'NoteContrat' }) {
        $given = @{} + $script:Answers
        $given.Remove($Missing)
        $code = Invoke-CogesMain -Action Installer -Version 'v1.2.3' -Racine $script:Racine -Simulation -NonInteractif @given 6>$null
        $code | Should -Be 1
        $out = $script:CogesState.Output -join "`n"
        $out | Should -Match 'Réponse manquante'
        $out | Should -Match ('-' + $Missing)
    }

    It '-NonInteractif : une réponse fausse est refusée, pas corrigée' {
        $given = @{} + $script:Answers
        $given['Offre'] = 'Business'
        Invoke-CogesMain -Action Installer -Version 'v1.2.3' -Racine $script:Racine -Simulation -NonInteractif @given 6>$null | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match '-Offre'
    }

    It '-NonInteractif : l''effacement des données est refusé' {
        Invoke-CogesMain -Action Desinstaller -Racine $script:Racine -NonInteractif -EffacerLesDonnees 6>$null | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match 'personne devant le PC'
    }

    It 'sans -CopieFaite, -NonInteractif s''arrête au rappel de copie' {
        # Hors simulation : le contrôle du PC est remplacé, la pose du programme aussi.
        Mock Test-CogesPrerequisite { }
        Mock Save-CogesArchive { }
        Mock Install-Programme {
            $p = Get-CogesPath $Racine
            New-Item -ItemType Directory -Force -Path $p.Programme | Out-Null
            Copy-Item -LiteralPath (Join-Path $script:Onprem 'coges.env.example') -Destination $p.Programme
            return 1
        }
        Mock Get-CogesListeningPort { @() }
        Mock Set-CogesPrivateAcl { }
        $given = @{} + $script:Answers
        $code = Invoke-CogesMain -Action Installer -Version 'v1.2.3' -Racine $script:Racine -NonInteractif @given 6>$null
        $code | Should -Be 1
        $out = $script:CogesState.Output -join "`n"
        $out | Should -Match 'gestionnaire de mots de passe'
        $out | Should -Match '-CopieFaite'
        Test-Path -LiteralPath (Join-Path (Join-Path $script:Racine 'reglages') 'coges.env') | Should -BeTrue
        Should -Invoke Invoke-Docker -Times 0 -Exactly
        $logs = @(Get-ChildItem -LiteralPath (Join-Path $script:Racine 'journaux') -Filter 'installation-*.log')
        $logs.Count | Should -Be 1
        $values = Read-CogesEnvFile (Join-Path (Join-Path $script:Racine 'reglages') 'coges.env')
        $log = [IO.File]::ReadAllText($logs[0].FullName)
        foreach ($key in @($script:CogesSecretKeys) + 'COGES_MFA_ENCRYPTION_KEY') { $log.Contains($values[$key]) | Should -BeFalse }
    }
}
