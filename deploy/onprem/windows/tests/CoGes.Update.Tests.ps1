# Tests Pester 5 des mises à jour sur site (lot 5, ADR 0128).
#
# Joués comme ceux des lots 3 et 4 : sous Linux (pwsh) et sous Windows (5.1 et pwsh). Docker
# n'est jamais appelé : Invoke-Docker est remplacé par un faux qui tient l'état des bases.
#
#   Invoke-Pester -Path deploy/onprem/windows/tests

BeforeAll {
    $windows = Split-Path -Parent $PSScriptRoot
    $script:Onprem = Split-Path -Parent $windows
    . (Join-Path $windows 'CoGes.Install.ps1')
    $script:Model = [IO.File]::ReadAllText((Join-Path $script:Onprem 'coges.env.example'))
    $script:Digests = @{ front = 'sha256:' + ('a' * 64); api = 'sha256:' + ('b' * 64); worker = 'sha256:' + ('c' * 64) }

    function New-DockerResult {
        param([int] $Code, [string[]] $Lines)
        [pscustomobject]@{ ExitCode = $Code; Output = $Lines; Stdout = $Lines }
    }

    function New-TestArchive {
        <# Une archive au format de GitHub (CoGes-x/deploy/onprem/…) faite du vrai dossier. #>
        param([Parameter(Mandatory)] [string] $Path, [string] $Prefix = 'CoGes-0.4.0', [hashtable] $Extra = @{},
            [System.IO.Compression.CompressionLevel] $Level = [System.IO.Compression.CompressionLevel]::Optimal)
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Force }
        $zip = [IO.Compression.ZipFile]::Open($Path, [IO.Compression.ZipArchiveMode]::Create)
        try {
            $root = [IO.Path]::GetFullPath($script:Onprem)
            foreach ($file in (Get-ChildItem -LiteralPath $root -Recurse -File | Where-Object { $_.FullName -notmatch '__pycache__' })) {
                $relative = $file.FullName.Substring($root.Length + 1).Replace('\', '/')
                $entry = $zip.CreateEntry(('{0}/deploy/onprem/{1}' -f $Prefix, $relative), $Level)
                $stream = $entry.Open()
                try { $bytes = [IO.File]::ReadAllBytes($file.FullName); $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
            }
            foreach ($name in $Extra.Keys) {
                $entry = $zip.CreateEntry(('{0}/deploy/onprem/{1}' -f $Prefix, $name), $Level)
                $stream = $entry.Open()
                try { $bytes = [Text.Encoding]::UTF8.GetBytes($Extra[$name]); $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
            }
            # Hors de deploy/onprem : ni posé, ni compté.
            [void]$zip.CreateEntry(($Prefix + '/README.md'))
        }
        finally { $zip.Dispose() }
    }

    function New-TestChannel {
        param([string] $Version = 'v0.4.0', [string] $Minimum = 'v0.3.0', [string] $Sha = ('d' * 64), [int] $Count = 20, [string] $Canal = 'stable')
        return [ordered]@{
            format = 'COGES-CANAL-1'; canal = $Canal; version = $Version; publiee_le = '2026-11-22'; depuis_minimum = $Minimum
            images = $script:Digests; programme = [ordered]@{ sha256 = $Sha; fichiers = $Count }
            docker_desktop_minimum = $null; note = 'Corrige l''impression du ticket.'; signature = $null
        }
    }

    function New-TestInstall {
        <# Une installation factice en v0.3.0 : réglages, programme, clé publique, dossiers. #>
        $paths = Get-CogesPath (Join-Path $TestDrive ('r-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)))
        New-Item -ItemType Directory -Force -Path $paths.Reglages, $paths.Journaux | Out-Null
        $archive = Join-Path $TestDrive ('v030-' + [Guid]::NewGuid().ToString('N').Substring(0, 6) + '.zip')
        New-TestArchive -Path $archive -Prefix 'CoGes-0.3.0'
        [void](Install-Programme -Archive $archive -Racine $paths.Racine -Version 'v0.3.0')
        $values = New-CogesSecretSet
        $values['COGES_IMAGE_TAG'] = 'v0.3.0'
        $values['COGES_HTTP_PORT'] = '80'
        $values['COGES_PUBLIC_URL'] = 'http://localhost'
        Write-CogesEnvFile -Path $paths.EnvFile -Text (ConvertTo-CogesEnvText -Model $script:Model -Values $values)
        [IO.File]::WriteAllText((Get-CogesBackupPath $paths).ClePublique, (New-CogesKeyPair).Public + "`n")
        $script:CogesState.LogPath = Join-Path $paths.Journaux 'essai.log'
        $script:CogesState.Simulation = $false
        $script:CogesState.NonInteractif = $true
        $script:CogesState.Output.Clear()
        [void](Get-CogesSetting $paths)
        return $paths
    }

    function New-ReadyVersion {
        <# v0.4.0 téléchargée et prête : archive, programme déplié, état. #>
        param([Parameter(Mandatory)] $Paths, [string] $Version = 'v0.4.0', [Nullable[datetime]] $ReadySince = $null)
        if ($null -eq $ReadySince) { $ReadySince = Get-Date }
        $folder = Join-Path (Get-CogesUpdatePath $Paths).Dossier $Version
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        New-TestArchive -Path (Join-Path $folder 'programme.zip') -Prefix ('CoGes-' + $Version.TrimStart('v'))
        [void](Expand-CogesProgramme -Archive (Join-Path $folder 'programme.zip') -Destination (Join-Path $folder 'programme'))
        $state = Read-CogesUpdateState $Paths
        Set-CogesVersionState -State $state -Version $Version -Changes @{ etat = 'prete'; prete_le = $ReadySince.ToString('o'); digests = $script:Digests }
        Write-CogesUpdateState -Paths $Paths -State $state
        return $state
    }

    # Le faux docker : bases nommées (coges, copies), ventes comptées, migrate qui réussit ou non.
    function Install-FakeDocker {
        param([hashtable] $Behaviour = @{})
        $script:Fake = @{ Bases = New-Object System.Collections.Generic.List[string]; Ventes = 7; Societes = 1; Calls = New-Object System.Collections.Generic.List[string] }
        $script:Fake.Bases.Add('coges')
        $script:FakeBehaviour = $Behaviour
        Mock Get-CogesDockerEngineProblem { $null }
        Mock New-CogesBackup { [pscustomobject]@{ Path = 'C:\CoGes\sauvegardes\x-avant-maj.coges'; Name = 'x-avant-maj.coges'; Size = 10; Offsite = @() } }
        Mock Wait-CogesHealthy { }
        Mock Test-CogesSite { }
        Mock Get-CogesLicenseStatus { New-DockerResult 0 @('Accès : actif', 'Fin de période : sans fin') }
        Mock Show-CogesToast { $true }
        Mock Get-CogesFreeSpace { 50GB }
        Mock Invoke-Docker {
            $joined = $Arguments -join ' '
            $script:Fake.Calls.Add($joined)
            $b = $script:FakeBehaviour
            if ($joined -match 'image inspect --format \{\{json \.RepoDigests\}\} (\S+)/(\w+):(\S+)$') {
                return New-DockerResult 0 @(('["{0}/{1}@{2}"]' -f $Matches[1], $Matches[2], $script:Digests[$Matches[2]]))
            }
            if ($joined -match 'base\.py compter') {
                # Date fixe, avant tous les -Now figés des tests (2026-11-22 21:35) et avant l'heure réelle :
                # « il y a 3 heures » relu à l'horloge du runner tombait après ces -Now dès le 23/11.
                $last = '2026-11-22T08:00:00.0000000Z'
                if ($b.ContainsKey('LastActivity')) { $last = $b.LastActivity }
                $since = 'null'
                if ($joined -match '--depuis') { $since = '2' }
                return New-DockerResult 0 @(('{{"existe": true, "societes": {0}, "ventes": {1}, "boutiques": ["boutique-diallo"], "derniere_activite": "{2}", "ventes_depuis": {3}}}' -f $script:Fake.Societes, $script:Fake.Ventes, $last, $since))
            }
            if ($joined -match 'base\.py copies') {
                $copies = @($script:Fake.Bases | Where-Object { $_ -like 'coges_avant_maj_*' } | ForEach-Object { '{{"nom": "{0}", "octets": 1}}' -f $_ })
                return New-DockerResult 0 @('[' + ($copies -join ', ') + ']')
            }
            if ($joined -match 'base\.py copier (\S+)') { $script:Fake.Bases.Add('coges_avant_maj_' + $Matches[1]); return New-DockerResult 0 @('{"copie": "x"}') }
            if ($joined -match 'base\.py remettre (\S+) --ecarter (\w+)') {
                [void]$script:Fake.Bases.Remove('coges_avant_maj_' + $Matches[1])
                $script:Fake.Bases.Add(('coges_{0}_maj_{1}' -f $Matches[2], $Matches[1]))
                $script:Fake.Ventes = 7
                return New-DockerResult 0 @('{"remise": "x"}')
            }
            if ($joined -match 'base\.py supprimer (\S+)') { [void]$script:Fake.Bases.Remove($Matches[1]); return New-DockerResult 0 @('supprimée') }
            if ($joined -match 'run --rm -T migrate') {
                if ($b.ContainsKey('MigrateFails') -and $b.MigrateFails) { return New-DockerResult 1 @('RuntimeError: migration cassée exprès') }
                return New-DockerResult 0 @('Running upgrade 0042 -> 0043')
            }
            if ($joined -match 'check_onprem_env\.py --env-file /dev/stdin') {
                $script:Fake.CheckInput = $InputText
                return New-DockerResult 0 @('OK — réglages acceptés')
            }
            return New-DockerResult 0 @()
        }
    }
}

AfterAll { $script:CogesState.LogPath = $null }

Describe 'Le canal : lecture et refus' {
    It 'un canal complet est accepté' {
        $parsed = ConvertFrom-CogesChannel ((New-TestChannel) | ConvertTo-Json -Depth 4)
        $parsed.Problems | Should -BeNullOrEmpty
        $parsed.Data['version'] | Should -BeExactly 'v0.4.0'
    }

    It 'refusé : <cas>' -ForEach @(
        @{ Cas = 'pas du JSON'; Edit = { 'pas du json' }; Expected = '*pas un objet JSON*' }
        @{ Cas = 'champ absent'; Edit = { param($c) $c.Remove('programme'); $c | ConvertTo-Json -Depth 4 }; Expected = '*champs absents : programme*' }
        @{ Cas = 'digest faux'; Edit = { param($c) $c.images = @{ front = 'sha256:court'; api = $script:Digests.api; worker = $script:Digests.worker }; $c | ConvertTo-Json -Depth 4 }; Expected = '*images.front*' }
        @{ Cas = 'version latest'; Edit = { param($c) $c.version = 'latest'; $c | ConvertTo-Json -Depth 4 }; Expected = '*version : vX.Y.Z*' }
        @{ Cas = 'minimum plus récent'; Edit = { param($c) $c.depuis_minimum = 'v0.5.0'; $c | ConvertTo-Json -Depth 4 }; Expected = '*depuis_minimum est plus récent*' }
        @{ Cas = 'signature non réservée'; Edit = { param($c) $c.signature = 'abc'; $c | ConvertTo-Json -Depth 4 }; Expected = '*signature : réservée*' }
        @{ Cas = 'canal inconnu'; Edit = { param($c) $c.canal = 'beta'; $c | ConvertTo-Json -Depth 4 }; Expected = '*canal beta inconnu*' }
    ) {
        $text = & $Edit (New-TestChannel)
        ((ConvertFrom-CogesChannel $text).Problems -join ' ; ') | Should -BeLike $Expected
    }

    It 'décision : <cas>' -ForEach @(
        @{ Cas = 'à jour'; Installed = 'v0.4.0'; Minimum = 'v0.3.0'; Docker = $null; Decision = 'a-jour' }
        @{ Cas = 'nouvelle'; Installed = 'v0.3.0'; Minimum = 'v0.3.0'; Docker = $null; Decision = 'nouvelle' }
        @{ Cas = 'plus ancienne que l''installée'; Installed = 'v0.5.0'; Minimum = 'v0.3.0'; Docker = $null; Decision = 'plus-ancienne' }
        @{ Cas = 'saut trop grand'; Installed = 'v0.2.0'; Minimum = 'v0.3.0'; Docker = $null; Decision = 'saut' }
        @{ Cas = 'version installée illisible'; Installed = 'ci'; Minimum = 'v0.3.0'; Docker = $null; Decision = 'installee' }
        @{ Cas = 'Docker Desktop trop ancien'; Installed = 'v0.3.0'; Minimum = 'v0.3.0'; Docker = '4.20.0'; Decision = 'docker' }
        @{ Cas = 'Docker Desktop assez récent'; Installed = 'v0.3.0'; Minimum = 'v0.3.0'; Docker = '4.40.0'; Decision = 'nouvelle' }
    ) {
        $channel = ConvertTo-CogesHashtable ((New-TestChannel -Minimum $Minimum) | ConvertTo-Json -Depth 4 | ConvertFrom-Json)
        $channel['docker_desktop_minimum'] = '4.30.0'
        $engine = $null
        if ($Docker) { $engine = [version]$Docker }
        (Get-CogesChannelDecision -Channel $channel -Installed $Installed -DockerDesktop $engine).Decision | Should -BeExactly $Decision
    }

    It 'le saut trop grand dit quelle version installer d''abord' {
        $channel = ConvertTo-CogesHashtable ((New-TestChannel -Version 'v0.6.0' -Minimum 'v0.5.0') | ConvertTo-Json -Depth 4 | ConvertFrom-Json)
        (Get-CogesChannelDecision -Channel $channel -Installed 'v0.3.0').Texte | Should -Match 'installez d''abord v0\.5\.0'
    }

    It 'la version de Docker Desktop se lit dans « docker version »' {
        Get-CogesDockerDesktopVersion @('Docker Desktop 4.37.1 (178610)') | Should -Be ([version]'4.37.1')
        Get-CogesDockerDesktopVersion @('Docker Engine - Community') | Should -BeNullOrEmpty
    }

    It 'la source : raw.githubusercontent.com par défaut, COGES_CANAL_ESSAI pour les essais' {
        $previous = $env:COGES_CANAL_ESSAI
        try {
            $env:COGES_CANAL_ESSAI = $null
            Get-CogesChannelSource 'test' | Should -BeExactly 'https://raw.githubusercontent.com/papa-bothie/CoGes/main/deploy/onprem/canal/test.json'
            $env:COGES_CANAL_ESSAI = $TestDrive
            Get-CogesChannelSource 'stable' | Should -BeExactly (Join-Path $TestDrive 'stable.json')
        }
        finally { $env:COGES_CANAL_ESSAI = $previous }
    }
}

Describe 'L''empreinte du programme' {
    It 'ne dépend pas de la compression du .zip, change avec le contenu' {
        $a = Join-Path $TestDrive 'a.zip'
        $b = Join-Path $TestDrive 'b.zip'
        $c = Join-Path $TestDrive 'c.zip'
        New-TestArchive -Path $a -Level Optimal
        New-TestArchive -Path $b -Level NoCompression -Prefix 'CoGes-autre-nom'
        New-TestArchive -Path $c -Extra @{ 'canal/test.json' = '{}' }
        (Get-FileHash $a).Hash | Should -Not -Be (Get-FileHash $b).Hash
        (Get-CogesProgrammeDigest $a).Sha256 | Should -BeExactly (Get-CogesProgrammeDigest $b).Sha256
        (Get-CogesProgrammeDigest $a).Sha256 | Should -Not -Be (Get-CogesProgrammeDigest $c).Sha256
        (Get-CogesProgrammeDigest $c).Count | Should -Be ((Get-CogesProgrammeDigest $a).Count + 1)
    }

    It 'le même calcul que publier.py (Python)' -Skip:(-not (Get-Command python3 -ErrorAction SilentlyContinue) -and -not (Get-Command python -ErrorAction SilentlyContinue)) {
        $archive = Join-Path $TestDrive 'parite.zip'
        New-TestArchive -Path $archive
        $python = 'python3'
        if (-not (Get-Command python3 -ErrorAction SilentlyContinue)) { $python = 'python' }
        $tool = Join-Path (Join-Path $script:Onprem 'canal') 'publier.py'
        $code = "import importlib.util, sys; s = importlib.util.spec_from_file_location('p', sys.argv[1]); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); d, n = m.programme_digest(sys.argv[2]); print(d, n)"
        $out = (& $python -c $code $tool $archive).Trim().Split(' ')
        $mine = Get-CogesProgrammeDigest $archive
        $out[0] | Should -BeExactly $mine.Sha256
        [int]$out[1] | Should -Be $mine.Count
    }
}

Describe 'Quand appliquer : 21 h 30, 30 minutes sans vente, jamais au démarrage' {
    It '<cas>' -ForEach @(
        @{ Cas = 'à l''heure, calme : oui'; Now = '2026-11-22 21:35'; Heure = '21:30'; Boot = '2026-11-22 08:00'; Last = '2026-11-22 20:00'; Auto = $true; Due = $true; Motif = '' }
        @{ Cas = 'avant l''heure : non'; Now = '2026-11-22 21:00'; Heure = '21:30'; Boot = '2026-11-22 08:00'; Last = $null; Auto = $true; Due = $false; Motif = 'hors-heure' }
        @{ Cas = 'plus de deux heures après : non'; Now = '2026-11-22 23:45'; Heure = '21:30'; Boot = '2026-11-22 08:00'; Last = $null; Auto = $true; Due = $false; Motif = 'hors-heure' }
        @{ Cas = 'une vente il y a 10 minutes : non'; Now = '2026-11-22 21:40'; Heure = '21:30'; Boot = '2026-11-22 08:00'; Last = '2026-11-22 21:30'; Auto = $true; Due = $false; Motif = 'vente' }
        @{ Cas = 'une vente il y a 30 minutes : oui'; Now = '2026-11-22 22:00'; Heure = '21:30'; Boot = '2026-11-22 08:00'; Last = '2026-11-22 21:30'; Auto = $true; Due = $true; Motif = '' }
        @{ Cas = 'PC allumé à l''instant : non'; Now = '2026-11-22 21:35'; Heure = '21:30'; Boot = '2026-11-22 21:30'; Last = $null; Auto = $true; Due = $false; Motif = 'demarrage' }
        @{ Cas = 'automatique coupé : non'; Now = '2026-11-22 21:35'; Heure = '21:30'; Boot = $null; Last = $null; Auto = $false; Due = $false; Motif = 'manuel' }
        @{ Cas = 'heure tard, après minuit : oui'; Now = '2026-11-23 00:15'; Heure = '23:30'; Boot = '2026-11-22 08:00'; Last = $null; Auto = $true; Due = $true; Motif = '' }
        @{ Cas = 'heure réglée à 13:00'; Now = '2026-11-22 13:05'; Heure = '13:00'; Boot = '2026-11-22 08:00'; Last = '2026-11-22 12:00'; Auto = $true; Due = $true; Motif = '' }
    ) {
        # PowerShell ne distingue pas $Boot et $boot : d'autres noms.
        $bootAt = $null
        if ($Boot) { $bootAt = [datetime]$Boot }
        $saleAt = $null
        if ($Last) { $saleAt = [datetime]$Last }
        $result = Test-CogesApplyDue -Now ([datetime]$Now) -Heure $Heure -BootTime $bootAt -LastActivity $saleAt -Automatique $Auto
        $result.Due | Should -Be $Due
        $result.Motif | Should -BeExactly $Motif
    }

    It 'la vente récente se dit en minutes' {
        (Test-CogesQuiet -Now ([datetime]'2026-11-22 21:40') -LastActivity ([datetime]'2026-11-22 21:28')).Texte | Should -Match 'il y a 12 minute'
    }
}

Describe 'Trois jours d''attente : raccourci et rappel' {
    It 'le calcul des jours et du motif : <cas>' -ForEach @(
        @{ Cas = 'PC éteint à l''heure prévue'; Ready = '2026-11-19 12:00'; Tried = $null; Motif = $null; Days = 3; Manual = $true; Reason = '*PC éteint ou en veille à 21:30*' }
        @{ Cas = 'des ventes à l''heure prévue'; Ready = '2026-11-19 12:00'; Tried = '2026-11-21 21:31'; Motif = 'une vente il y a 4 minute(s)'; Days = 3; Manual = $true; Reason = '*une vente il y a 4 minute*' }
        @{ Cas = 'prête depuis deux jours'; Ready = '2026-11-20 12:00'; Tried = $null; Motif = $null; Days = 2; Manual = $false; Reason = '*PC éteint*' }
        @{ Cas = 'prête ce matin'; Ready = '2026-11-22 11:00'; Tried = $null; Motif = $null; Days = 0; Manual = $false; Reason = '*prête depuis peu*' }
    ) {
        $entry = @{ prete_le = ([datetime]$Ready).ToString('o') }
        if ($Tried) { $entry['dernier_essai'] = ([datetime]$Tried).ToString('o'); $entry['dernier_motif_texte'] = $Motif }
        $wait = Get-CogesUpdateWait -Entry $entry -Now ([datetime]'2026-11-22 12:00') -Heure '21:30'
        $wait.Days | Should -Be $Days
        $wait.Manual | Should -Be $Manual
        $wait.Reason | Should -BeLike $Reason
    }

    It 'le raccourci est posé au bout de 3 jours, le rappel une fois par jour, puis tout est retiré' {
        $paths = New-TestInstall
        $desktop = Join-Path $TestDrive 'bureau'
        $previous = $env:COGES_BUREAU_ESSAI
        $env:COGES_BUREAU_ESSAI = $desktop
        Mock Show-CogesToast { $true }
        try {
            $state = New-ReadyVersion -Paths $paths -ReadySince ([datetime]'2026-11-18 12:00')
            Invoke-CogesManualReminder -Paths $paths -State $state -Now ([datetime]'2026-11-22 12:00') -Heure '21:30' | Should -BeTrue
            $shortcut = Join-Path $desktop 'Mettre CoGes à jour.cmd'
            Test-Path -LiteralPath $shortcut | Should -BeTrue
            $text = [IO.File]::ReadAllText($shortcut)
            $text | Should -Match '-Action MettreAJour -Maintenant -Bureau'
            $text | Should -Match ([regex]::Escape((Join-Path $paths.Programme 'windows\installer.ps1')))
            # Le même jour : pas de second rappel.
            Invoke-CogesManualReminder -Paths $paths -State (Read-CogesUpdateState $paths) -Now ([datetime]'2026-11-22 18:00') -Heure '21:30' | Should -BeFalse
            # Le lendemain : un rappel.
            Invoke-CogesManualReminder -Paths $paths -State (Read-CogesUpdateState $paths) -Now ([datetime]'2026-11-23 12:00') -Heure '21:30' | Should -BeTrue
            Should -Invoke Show-CogesToast -Times 2 -Exactly -ParameterFilter { $Text -like 'Une mise à jour de CoGes est prête. Quand vous avez 5 minutes sans client, double-cliquez sur « Mettre CoGes à jour » sur le Bureau.' }
            # Appliquée : plus de version prête, le raccourci part.
            $state = Read-CogesUpdateState $paths
            Set-CogesVersionState -State $state -Version 'v0.4.0' -Changes @{ etat = 'appliquee' }
            Write-CogesUpdateState -Paths $paths -State $state
            Invoke-CogesManualReminder -Paths $paths -State $state -Now ([datetime]'2026-11-24 12:00') -Heure '21:30' | Should -BeFalse
            Test-Path -LiteralPath $shortcut | Should -BeFalse
        }
        finally { $env:COGES_BUREAU_ESSAI = $previous }
    }

    It 'avant 3 jours : ni raccourci ni rappel' {
        $paths = New-TestInstall
        $desktop = Join-Path $TestDrive 'bureau-2'
        $previous = $env:COGES_BUREAU_ESSAI
        $env:COGES_BUREAU_ESSAI = $desktop
        Mock Show-CogesToast { $true }
        try {
            $state = New-ReadyVersion -Paths $paths -ReadySince ([datetime]'2026-11-21 12:00')
            Invoke-CogesManualReminder -Paths $paths -State $state -Now ([datetime]'2026-11-22 12:00') -Heure '21:30' | Should -BeFalse
            Test-Path -LiteralPath (Join-Path $desktop 'Mettre CoGes à jour.cmd') | Should -BeFalse
            Should -Invoke Show-CogesToast -Times 0 -Exactly
        }
        finally { $env:COGES_BUREAU_ESSAI = $previous }
    }
}

Describe 'Réglages et images' {
    It 'mise-a-jour.json : valeurs par défaut, valeurs fausses ignorées' {
        $paths = New-TestInstall
        $setting = Read-CogesUpdateSetting $paths
        $setting.canal | Should -BeExactly 'stable'
        $setting.automatique | Should -BeTrue
        $setting.heure | Should -BeExactly '21:30'
        [IO.File]::WriteAllText((Get-CogesUpdatePath $paths).Reglage, '{"canal": "beta", "automatique": false, "heure": "25:00"}')
        $setting = Read-CogesUpdateSetting $paths
        $setting.canal | Should -BeExactly 'stable'
        $setting.automatique | Should -BeFalse
        $setting.heure | Should -BeExactly '21:30'
    }

    It 'Reparer -HeureMiseAJour 13:00 -CanalMiseAJour test : écrit le réglage ; une heure fausse est refusée' {
        $paths = New-TestInstall
        Set-CogesUpdateOption -Paths $paths -Options @{ HeureMiseAJour = '13:00'; CanalMiseAJour = 'test' } 6>$null
        $setting = Read-CogesUpdateSetting $paths
        $setting.heure | Should -BeExactly '13:00'
        $setting.canal | Should -BeExactly 'test'
        { Set-CogesUpdateOption -Paths $paths -Options @{ HeureMiseAJour = '9h'; CanalMiseAJour = '' } } | Should -Throw '*HH:MM*'
    }

    It 'images retirées : plus de deux versions en arrière seulement' {
        $removed = Select-CogesImageToRemove -Tags @('v0.1.0', 'v0.2.0', 'v0.3.0', 'v0.4.0', 'v0.5.0', 'ci', '<none>') -Current 'v0.4.0'
        @($removed | Sort-Object) | Should -Be @('v0.1.0', 'v0.2.0')
        @(Select-CogesImageToRemove -Tags @('v0.3.0', 'v0.4.0') -Current 'v0.4.0') | Should -BeNullOrEmpty
    }

    It 'une ligne nouvelle du modèle est ajoutée avec sa valeur par défaut ; un secret manquant est un refus' {
        $values = @{ COGES_IMAGE_TAG = 'v0.3.0'; COGES_HTTP_PORT = '80' }
        $missing = Get-CogesMissingSetting -ModelText "COGES_IMAGE_TAG=`nCOGES_HTTP_PORT=80`nCOGES_NOUVEAU_REGLAGE=oui`nCOGES_APP_PASSWORD=`n" -Values $values
        $missing.Additions['COGES_NOUVEAU_REGLAGE'] | Should -BeExactly 'oui'
        $missing.Secrets | Should -Be @('COGES_APP_PASSWORD')
    }

    It 'coges.env : seule la version change, les lignes ajoutées vont à la fin, fins de ligne gardées' {
        $text = "# entête`r`nCOGES_IMAGE_TAG=v0.3.0`r`nCOGES_APP_PASSWORD=abc`r`n"
        $new = ConvertTo-CogesEditedEnvText -Text $text -Values ([ordered]@{ COGES_IMAGE_TAG = 'v0.4.0' }) -Additions ([ordered]@{ COGES_NOUVEAU = '1' })
        $new | Should -BeExactly "# entête`r`nCOGES_IMAGE_TAG=v0.4.0`r`nCOGES_APP_PASSWORD=abc`r`n# Ajouté par la mise à jour (valeur par défaut du modèle).`r`nCOGES_NOUVEAU=1`r`n"
        { ConvertTo-CogesEditedEnvText -Text $text -Values @{ COGES_APP_PASSWORD = 'x' } } | Should -Throw '*ne change jamais*'
    }
}

Describe 'Télécharger : jamais une étiquette, toujours un digest' {
    It 'une étiquette qui ne pointe plus vers le digest du canal : refusée, rien n''est tiré' {
        $paths = New-TestInstall
        Install-FakeDocker
        Mock Test-CogesImageDigest { $false }
        Mock Get-CogesRemoteDigest { 'sha256:' + ('e' * 64) }
        $archive = Join-Path $TestDrive 'telechargement.zip'
        New-TestArchive -Path $archive
        $digest = Get-CogesProgrammeDigest $archive
        $channel = ConvertTo-CogesHashtable ((New-TestChannel -Sha $digest.Sha256 -Count $digest.Count) | ConvertTo-Json -Depth 4 | ConvertFrom-Json)
        $folder = Join-Path $TestDrive 'archives'
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        Copy-Item $archive (Join-Path $folder 'v0.4.0.zip')
        $previous = $env:COGES_ARCHIVE_ESSAI
        $env:COGES_ARCHIVE_ESSAI = $folder
        try { { Save-CogesUpdate -Paths $paths -Settings (Get-CogesSetting $paths) -Channel $channel -State (Read-CogesUpdateState $paths) 6>$null } | Should -Throw '*ne pointe plus vers le digest du canal*' }
        finally { $env:COGES_ARCHIVE_ESSAI = $previous }
        @($script:Fake.Calls | Where-Object { $_ -match '^pull ' }).Count | Should -Be 0
        (Get-CogesVersionState -State (Read-CogesUpdateState $paths) -Version 'v0.4.0')['etat'] | Should -BeExactly 'telechargement'
    }

    It 'une archive dont le contenu ne correspond pas au canal : refusée, effacée' {
        $paths = New-TestInstall
        Install-FakeDocker
        $folder = Join-Path $TestDrive 'archives-2'
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        New-TestArchive -Path (Join-Path $folder 'v0.4.0.zip')
        $channel = ConvertTo-CogesHashtable ((New-TestChannel) | ConvertTo-Json -Depth 4 | ConvertFrom-Json)
        $previous = $env:COGES_ARCHIVE_ESSAI
        $env:COGES_ARCHIVE_ESSAI = $folder
        try { { Save-CogesUpdate -Paths $paths -Settings (Get-CogesSetting $paths) -Channel $channel -State (Read-CogesUpdateState $paths) 6>$null } | Should -Throw '*empreinte du programme*' }
        finally { $env:COGES_ARCHIVE_ESSAI = $previous }
        Test-Path -LiteralPath (Join-Path (Join-Path (Get-CogesUpdatePath $paths).Dossier 'v0.4.0') 'programme.zip') | Should -BeFalse
    }

    It 'une version en échec n''est jamais retéléchargée ni reprise seule' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = Read-CogesUpdateState $paths
        Set-CogesVersionState -State $state -Version 'v0.4.0' -Changes @{ etat = 'echec' }
        Mock Read-CogesChannel { [pscustomobject]@{ Data = (ConvertTo-CogesHashtable ((New-TestChannel) | ConvertTo-Json -Depth 4 | ConvertFrom-Json)); Decision = 'nouvelle'; Texte = 'Nouvelle version disponible : v0.4.0'; Source = 'x' } }
        Mock Save-CogesUpdate { throw 'ne doit pas être appelé' }
        [void](Invoke-CogesUpdateCheck -Paths $paths -State $state 6>$null)
        Should -Invoke Save-CogesUpdate -Times 0 -Exactly
        ($script:CogesState.Output -join "`n") | Should -Match 'ne s''applique plus seule'
    }
}

Describe 'Appliquer (docker remplacé)' {
    It 'réussite : sauvegarde, copie, programme et version changés, mêmes données, copie gardée 7 jours' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = New-ReadyVersion -Paths $paths
        $result = Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' -Now ([datetime]'2026-11-22 21:35') 6>$null
        $result | Should -BeExactly 'appliquee'
        (Get-CogesSetting $paths)['COGES_IMAGE_TAG'] | Should -BeExactly 'v0.4.0'
        Get-CogesInstalledVersion $paths | Should -BeExactly 'v0.4.0'
        ([IO.File]::ReadAllText((Join-Path (Get-CogesUpdatePath $paths).Precedent '.version'))).Trim() | Should -BeExactly 'v0.3.0'
        $script:Fake.Bases | Should -Contain 'coges_avant_maj_20261122_213500'
        Should -Invoke New-CogesBackup -Times 1 -Exactly -ParameterFilter { $Raison -eq 'avant-maj' }
        $saved = Read-CogesUpdateState $paths
        $saved['versions']['v0.4.0']['etat'] | Should -BeExactly 'appliquee'
        $saved['derniere_maj']['resultat'] | Should -BeExactly 'reussie'
        (ConvertTo-CogesStateDate $saved['derniere_maj']['copie_fin']) | Should -Be ([datetime]'2026-11-29 21:35')
        # L'ordre : sauvegarde, contrôle à blanc, arrêt, copie, migrate, up.
        $order = @($script:Fake.Calls | ForEach-Object {
                if ($_ -match 'check_onprem_env') { 'controle' } elseif ($_ -match ' stop front') { 'arret' } elseif ($_ -match 'base\.py copier') { 'copie' }
                elseif ($_ -match 'migrate') { 'migrate' } elseif ($_ -match ' up -d') { 'up' } })
        ($order -join ',') | Should -BeExactly 'controle,arret,copie,migrate,up'
        # Le contrôle à blanc reçoit les réglages par l'entrée standard, avec la nouvelle version.
        $script:Fake.CheckInput | Should -Match 'COGES_IMAGE_TAG=v0\.4\.0'
        @($script:Fake.Calls | Where-Object { $_ -match 'check_onprem_env' })[0] | Should -Not -Match 'reglages'
    }

    It 'une vente il y a 5 minutes : rien ne change, sauf avec -Force' {
        $paths = New-TestInstall
        Install-FakeDocker -Behaviour @{ LastActivity = (Get-Date).AddMinutes(-5).ToUniversalTime().ToString('o') }
        $state = New-ReadyVersion -Paths $paths
        { Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' 6>$null } | Should -Throw '*Pas maintenant*vente*'
        @($script:Fake.Calls | Where-Object { $_ -match ' stop |copier|migrate' }).Count | Should -Be 0
        Should -Invoke New-CogesBackup -Times 0 -Exactly
        (Get-CogesSetting $paths)['COGES_IMAGE_TAG'] | Should -BeExactly 'v0.3.0'
        Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' -Force 6>$null | Should -BeExactly 'appliquee'
    }

    It 'migration ratée : retour automatique, coges.env à l''octet, ancien programme, copie remise, toast' {
        $paths = New-TestInstall
        Install-FakeDocker -Behaviour @{ MigrateFails = $true }
        $state = New-ReadyVersion -Paths $paths
        $envBefore = [IO.File]::ReadAllBytes($paths.EnvFile)
        { Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' -Now ([datetime]'2026-11-22 21:35') 6>$null } |
            Should -Throw '*La mise à jour vers v0.4.0 a échoué ; CoGes est revenu à v0.3.0. Rien n''est perdu.*'
        [Convert]::ToBase64String([IO.File]::ReadAllBytes($paths.EnvFile)) | Should -BeExactly ([Convert]::ToBase64String($envBefore))
        Get-CogesInstalledVersion $paths | Should -BeExactly 'v0.3.0'
        $script:Fake.Bases | Should -Contain 'coges'
        $script:Fake.Bases | Should -Contain 'coges_echec_maj_20261122_213500'
        $script:Fake.Bases | Should -Not -Contain 'coges_avant_maj_20261122_213500'
        Should -Invoke Show-CogesToast -Times 1 -ParameterFilter { $Text -like 'La mise à jour vers v0.4.0 a échoué ; CoGes est revenu à v0.3.0*' }
        $saved = Read-CogesUpdateState $paths
        $saved['versions']['v0.4.0']['etat'] | Should -BeExactly 'echec'
        $saved['derniere_maj']['resultat'] | Should -BeExactly 'revenue'
        Get-CogesReadyVersion $saved | Should -BeNullOrEmpty
    }

    It 'données différentes après la mise à jour : retour automatique' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = New-ReadyVersion -Paths $paths
        # Après la nouvelle version seulement (le retour remet la copie, donc les 7 ventes).
        $script:Healthy = 0
        Mock Wait-CogesHealthy { $script:Healthy++; if ($script:Healthy -eq 1) { $script:Fake.Ventes = 3 } }
        { Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' -Now ([datetime]'2026-11-22 21:35') 6>$null } | Should -Throw '*revenu à v0.3.0*'
        ($script:CogesState.Output -join "`n") | Should -Match 'données différentes'
        Get-CogesInstalledVersion $paths | Should -BeExactly 'v0.3.0'
    }

    It 'un secret demandé par la nouvelle version et absent : refusé avant tout arrêt' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = New-ReadyVersion -Paths $paths
        $example = Join-Path (Join-Path (Join-Path (Get-CogesUpdatePath $paths).Dossier 'v0.4.0') 'programme') 'coges.env.example'
        [IO.File]::AppendAllText($example, "COGES_NOUVEAU_SECRET=`n")
        { Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' 6>$null } | Should -Throw '*COGES_NOUVEAU_SECRET*'
        @($script:Fake.Calls | Where-Object { $_ -match ' stop ' }).Count | Should -Be 0
    }
}

Describe 'Après la mise à jour : 7 jours, puis rien' {
    It 'avant 7 jours rien n''est supprimé ; après, la copie et l''ancien programme partent' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = New-ReadyVersion -Paths $paths
        [void](Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' -Now ([datetime]'2026-11-22 21:35') 6>$null)
        $state = Read-CogesUpdateState $paths
        Invoke-CogesUpdateCleanup -Paths $paths -State $state -Now ([datetime]'2026-11-29 21:00')
        $script:Fake.Bases | Should -Contain 'coges_avant_maj_20261122_213500'
        Test-Path -LiteralPath (Get-CogesUpdatePath $paths).Precedent | Should -BeTrue
        Invoke-CogesUpdateCleanup -Paths $paths -State $state -Now ([datetime]'2026-11-29 21:36')
        $script:Fake.Bases | Should -Not -Contain 'coges_avant_maj_20261122_213500'
        Test-Path -LiteralPath (Get-CogesUpdatePath $paths).Precedent | Should -BeFalse
        (Read-CogesUpdateState $paths)['derniere_maj']['copie'] | Should -BeNullOrEmpty
    }

    It 'RevenirVersionPrecedente : ventes perdues annoncées, sauvegarde d''abord, REVENIR exigé' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = New-ReadyVersion -Paths $paths
        [void](Invoke-CogesUpdateLocked -Paths $paths -State $state -Version 'v0.4.0' -Now (Get-Date) 6>$null)
        $script:CogesState.Output.Clear()
        Invoke-CogesMain -Action RevenirVersionPrecedente -Racine $paths.Racine -NonInteractif -CodeBoutique 'boutique-diallo' -SansNotification 6>$null | Should -Be 1
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match '2 VENTE\(S\) FAITE\(S\) DEPUIS SERAIENT PERDUES'
        $text | Should -Match 'REVENIR'
        Should -Invoke New-CogesBackup -Times 1 -Exactly -ParameterFilter { $Raison -eq 'avant-retour' }
        (Get-CogesSetting $paths)['COGES_IMAGE_TAG'] | Should -BeExactly 'v0.4.0'
        Invoke-CogesMain -Action RevenirVersionPrecedente -Racine $paths.Racine -NonInteractif -ConfirmerRetour -CodeBoutique 'boutique-diallo' -SansNotification 6>$null | Should -Be 0
        (Get-CogesSetting $paths)['COGES_IMAGE_TAG'] | Should -BeExactly 'v0.3.0'
        Get-CogesInstalledVersion $paths | Should -BeExactly 'v0.3.0'
        @($script:Fake.Bases | Where-Object { $_ -like 'coges_apres_maj_*' }).Count | Should -Be 1
        (Read-CogesUpdateState $paths)['versions']['v0.4.0']['etat'] | Should -BeExactly 'annulee'
    }

    It 'RevenirVersionPrecedente après 7 jours : refusé, renvoie vers Restaurer' {
        $paths = New-TestInstall
        Install-FakeDocker
        $state = Read-CogesUpdateState $paths
        $state['derniere_maj'] = @{ de = 'v0.3.0'; vers = 'v0.4.0'; le = (Get-Date).AddDays(-8).ToString('o'); resultat = 'reussie'; copie = '20261114_213500'; copie_fin = (Get-Date).AddDays(-1).ToString('o'); sauvegarde = 'x.coges' }
        Write-CogesUpdateState -Paths $paths -State $state
        Invoke-CogesMain -Action RevenirVersionPrecedente -Racine $paths.Racine -NonInteractif -ConfirmerRetour -CodeBoutique 'boutique-diallo' -SansNotification 6>$null | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match '(?s)plus de 7 jours.*Restaurer'
    }
}

Describe 'Simulation et état' {
    It '<action> en simulation : tout annoncé, docker jamais appelé, rien d''écrit' -ForEach @(@{ Action = 'VerifierMiseAJour' }, @{ Action = 'MettreAJour' }, @{ Action = 'RevenirVersionPrecedente' }) {
        $racine = Join-Path $TestDrive ('sim-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
        Mock Invoke-Docker { throw 'docker ne doit pas être appelé' }
        Invoke-CogesMain -Action $Action -Racine $racine -Simulation -NonInteractif -SansNotification 6>$null | Should -Be 0
        Test-Path -LiteralPath $racine | Should -BeFalse
        Should -Invoke Invoke-Docker -Times 0 -Exactly
        @($script:CogesState.Output | Where-Object { $_ -like '`[simulation`]*' }).Count | Should -BeGreaterThan 2
    }

    It 'Etat : canal, version prête et depuis combien de jours, dernière mise à jour, copie gardée' {
        $paths = New-TestInstall
        $state = New-ReadyVersion -Paths $paths -Version 'v0.5.0' -ReadySince ((Get-Date).AddDays(-4))
        $state['derniere_maj'] = @{ de = 'v0.2.0'; vers = 'v0.3.0'; le = (Get-Date).AddDays(-2).ToString('o'); resultat = 'reussie'; copie = '20261120_213500'; copie_fin = (Get-Date).AddDays(5).ToString('o') }
        Write-CogesUpdateState -Paths $paths -State $state
        Show-CogesUpdateState -Paths $paths 6>$null
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match 'canal stable, automatique, à 21:30'
        $text | Should -Match 'v0\.5\.0, prête ; attend depuis 4 jour\(s\) : PC éteint ou en veille à 21:30'
        $text | Should -Match 'Raccourci « Mettre CoGes à jour » posé'
        $text | Should -Match 'v0\.2\.0 → v0\.3\.0.*réussie'
        $text | Should -Match 'Copie gardée      : coges_avant_maj_20261120_213500'
    }
}
