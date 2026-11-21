# Tests Pester 5 de la sauvegarde sur site (lot 4, ADR 0127).
#
# Joués comme ceux du lot 3 : sous Linux (pwsh) et sous Windows (5.1 et pwsh). Docker n'est
# jamais appelé : Invoke-Docker est remplacé par un faux qui joue les conteneurs dans des
# dossiers du TestDrive (le volume de travail, le dossier des sauvegardes).
#
#   Invoke-Pester -Path deploy/onprem/windows/tests

BeforeAll {
    $windows = Split-Path -Parent $PSScriptRoot
    . (Join-Path $windows 'CoGes.Install.ps1')
    $script:Model = [IO.File]::ReadAllText((Join-Path (Split-Path -Parent $windows) 'coges.env.example'))

    function New-TestInstall {
        <# Une installation factice : réglages, clé publique, dossiers. #>
        param([string] $Name = ('r-' + [Guid]::NewGuid().ToString('N').Substring(0, 6)))
        $paths = Get-CogesPath (Join-Path $TestDrive $Name)
        New-Item -ItemType Directory -Force -Path $paths.Reglages, $paths.Programme, $paths.Journaux | Out-Null
        $values = New-CogesSecretSet
        $values['COGES_IMAGE_TAG'] = 'v1.4.0'
        $values['COGES_HTTP_PORT'] = '80'
        $values['COGES_PUBLIC_URL'] = 'http://localhost'
        Write-CogesEnvFile -Path $paths.EnvFile -Text (ConvertTo-CogesEnvText -Model $script:Model -Values $values)
        $pair = New-CogesKeyPair
        [IO.File]::WriteAllText((Get-CogesBackupPath $paths).ClePublique, $pair.Public + "`n")
        $script:CogesState.LogPath = Join-Path $paths.Journaux 'essai.log'
        $script:CogesState.Simulation = $false
        $script:CogesState.NonInteractif = $true
        $script:CogesState.Output.Clear()
        return $paths
    }

    function New-DockerResult {
        param([int] $Code, [string[]] $Lines)
        [pscustomobject]@{ ExitCode = $Code; Output = $Lines; Stdout = $Lines }
    }

    function New-FakeBackup {
        <# Une « bonne » sauvegarde dans un dossier : fichier, .sha256, .manifest.json. #>
        param([string] $Folder, [string] $Name, [int] $Size = 100, [string] $BaseId = 'base-1', [int] $Sales = 12)
        New-Item -ItemType Directory -Force -Path $Folder | Out-Null
        $path = Join-Path $Folder $Name
        [IO.File]::WriteAllBytes($path, [byte[]](1..$Size | ForEach-Object { 7 }))
        $sha = Get-CogesFileSha256 $path
        [IO.File]::WriteAllText($path + '.sha256', ('{0}  {1}' -f $sha, $Name) + "`n")
        $manifest = @{ base_id = $BaseId; sha256 = $sha; alembic_revision = '0042'; coges_version = 'v1.4.0'; boutiques = @('boutique-diallo')
            cree_le = '2026-11-20T13:00:00+00:00'; tables = @{ sales = $Sales } }
        [IO.File]::WriteAllText($path + '.manifest.json', ($manifest | ConvertTo-Json -Depth 4))
        return $path
    }

    # Le faux docker : les montages « -v hôte:/sortie » sont suivis, /travail est un dossier du TestDrive.
    function Install-FakeDocker {
        param([string] $Work, [hashtable] $Behaviour = @{})
        New-Item -ItemType Directory -Force -Path $Work | Out-Null
        $script:FakeWork = $Work
        $script:FakeBehaviour = $Behaviour
        $script:DockerCalls = New-Object System.Collections.Generic.List[object]
        # Le moteur répond (le contrôle du bloc 0 du lot 5 a ses propres tests).
        Mock Get-CogesDockerEngineProblem { $null }
        Mock Invoke-Docker {
            $script:DockerCalls.Add([pscustomobject]@{ Arguments = @($Arguments); InputText = $InputText })
            $mounts = @{}
            for ($i = 0; $i -lt $Arguments.Count - 1; $i++) {
                if ($Arguments[$i] -eq '-v') {
                    $spec = $Arguments[$i + 1] -replace ':ro$', ''
                    $cut = $spec.LastIndexOf(':/')
                    $mounts[$spec.Substring($cut + 1)] = $spec.Substring(0, $cut)
                }
            }
            $map = {
                param($p)
                if ($p.StartsWith('/travail/')) { return Join-Path $script:FakeWork $p.Substring(9) }
                foreach ($k in $mounts.Keys) { if ($p.StartsWith($k + '/')) { return Join-Path $mounts[$k] $p.Substring($k.Length + 1) } }
                return $p
            }
            $joined = $Arguments -join ' '
            $b = $script:FakeBehaviour
            if ($joined -match 'sauvegarde-pg vider') {
                Get-ChildItem -LiteralPath $script:FakeWork | Remove-Item -Recurse -Force
                return New-DockerResult 0 @('vide')
            }
            if ($joined -match 'base\.py manifeste --sortie (\S+)') {
                $target = & $map $Matches[1]
                $boutiques = @('boutique-diallo')
                if ($b.ContainsKey('Boutiques')) { $boutiques = $b.Boutiques }
                $baseId = 'base-1'
                if ($b.ContainsKey('BaseId')) { $baseId = $b.BaseId }
                $manifest = [ordered]@{ format = 'COGES-SAUV-1'; coges_version = 'v1.4.0'; alembic_revision = '0042'; server_version = '18.7'
                    boutiques = $boutiques; base_octets = 1000; base_id = $baseId; tables = @{ sales = 12 }; companies = 1 }
                [IO.File]::WriteAllText($target, ($manifest | ConvertTo-Json -Depth 4))
                $base = 1000
                if ($b.ContainsKey('BaseOctets')) { $base = $b.BaseOctets }
                return New-DockerResult 0 @(('{{"boutiques": ["{0}"], "base_octets": {1}, "base_id": "{2}"}}' -f ($boutiques -join '","'), $base, $baseId))
            }
            if ($joined -match 'sauvegarde-pg dump (\S+)') {
                if ($b.ContainsKey('DumpFails') -and $b.DumpFails) { return New-DockerResult 1 @('pg_dump: error: could not write to output file: No space left on device') }
                [IO.File]::WriteAllText((Join-Path $script:FakeWork ($Matches[1] + '.dump')), 'PGDMP en clair')
                return New-DockerResult 0 @('dump 14 18.7')
            }
            if ($joined -match 'coffre\.py chiffrer --publique \S+ (\S+) (\S+)') {
                $target = & $map $Matches[2]
                $size = 400
                if ($b.ContainsKey('SealedSize')) { $size = $b.SealedSize }
                [IO.File]::WriteAllBytes($target, [byte[]](1..$size | ForEach-Object { 3 }))
                $sha = Get-CogesFileSha256 $target
                return New-DockerResult 0 @(('chiffre {0} {1} {2}' -f $size, $sha, ('ab' * 32)))
            }
            if ($joined -match 'base\.py revisions') { return New-DockerResult 0 @('{"tete": "0042", "connues": ["0041", "0042"]}') }
            if ($joined -match 'base\.py etat') {
                $ventes = 0
                if ($b.ContainsKey('Ventes')) { $ventes = $b.Ventes }
                return New-DockerResult 0 @(('{{"existe": true, "societes": 0, "ventes": {0}}}' -f $ventes))
            }
            if ($joined -match 'base\.py (preparer|supprimer|verifier)') { return New-DockerResult 0 @('OK') }
            if ($joined -match 'sauvegarde-pg restaurer') { return New-DockerResult 0 @('restauree') }
            if ($joined -match 'coffre\.py dechiffrer') { return New-DockerResult 0 @('dechiffre 14 abc') }
            return New-DockerResult 0 @()
        }
    }
}

AfterAll { $script:CogesState.LogPath = $null }

Describe 'Noms des sauvegardes' {
    It 'coges-CODE-AAAAMMJJ-HHMM-VERSION.coges, relu à l''identique' {
        $name = Get-CogesBackupName -Slug 'boutique-diallo' -Date ([datetime]'2026-11-20 13:00:00') -Version 'v1.4.0'
        $name | Should -BeExactly 'coges-boutique-diallo-20261120-1300-v1.4.0.coges'
        $parsed = ConvertFrom-CogesBackupName $name
        $parsed.Slug | Should -BeExactly 'boutique-diallo'
        $parsed.Version | Should -BeExactly 'v1.4.0'
        $parsed.Date | Should -Be ([datetime]'2026-11-20 13:00:00')
    }

    It 'avec les secondes quand le nom est déjà pris' {
        $name = Get-CogesBackupName -Slug 'b' -Date ([datetime]'2026-11-20 13:00:42') -Version 'v1.4.0' -WithSeconds
        (ConvertFrom-CogesBackupName $name).Date.Second | Should -Be 42
    }

    It 'tout autre nom est ignoré (<name>)' -ForEach @(
        @{ Name = 'coges-boutique-20261120-1300-v1.4.0.coges.echec' }, @{ Name = 'photo.jpg' },
        @{ Name = 'coges-Boutique-20261120-1300-v1.4.0.coges' }, @{ Name = 'coges-b-2026112-1300-v1.coges' }, @{ Name = '' }) {
        ConvertFrom-CogesBackupName $Name | Should -BeNullOrEmpty
    }
}

Describe 'Rétention sur le PC (14 dernières, 8 semaines, 12 mois)' {
    BeforeAll {
        $script:Now = [datetime]'2026-11-20 21:00:00'
        # Deux sauvegardes par jour pendant 400 jours.
        $script:Items = foreach ($day in 0..399) {
            foreach ($hour in @(13, 20)) {
                $date = $script:Now.Date.AddDays(-$day).AddHours($hour)
                [pscustomobject]@{ Name = (Get-CogesBackupName -Slug 'b' -Date $date -Version 'v1.4.0'); Date = $date }
            }
        }
    }

    It 'garde les 14 dernières, 1 par semaine sur 8 semaines, 1 par mois sur 12 mois' {
        $doomed = @(Select-CogesBackupToDelete -Items $script:Items -Now $script:Now)
        $kept = @($script:Items | Where-Object { $doomed -notcontains $_.Name })
        $newest = @($script:Items | Sort-Object Date -Descending | Select-Object -First 14)
        foreach ($item in $newest) { $kept.Name | Should -Contain $item.Name }
        $kept.Count | Should -BeLessOrEqual 34
        $kept.Count | Should -BeGreaterOrEqual 25
        # Une par mois sur les 12 derniers mois.
        foreach ($age in 0..11) {
            $month = $script:Now.AddMonths(-$age)
            @($kept | Where-Object { $_.Date.Year -eq $month.Year -and $_.Date.Month -eq $month.Month }).Count | Should -BeGreaterOrEqual 1
        }
        # Rien de plus vieux que 12 mois.
        @($kept | Where-Object { $_.Date -lt $script:Now.AddMonths(-12).AddDays(-1) }).Count | Should -Be 0
    }

    It 'ne supprime jamais la plus récente, même seule ou très ancienne' {
        $old = [pscustomobject]@{ Name = 'coges-b-20200101-1300-v1.0.0.coges'; Date = [datetime]'2020-01-01 13:00' }
        @(Select-CogesBackupToDelete -Items @($old) -Now $script:Now).Count | Should -Be 0
        @(Select-CogesBackupToDelete -Items @() -Now $script:Now).Count | Should -Be 0
    }

    It 'sur le disque : ne compte ni les .echec ni les fichiers sans .sha256 ni les noms inconnus' {
        $folder = Join-Path $TestDrive 'retention'
        $good = New-FakeBackup -Folder $folder -Name 'coges-b-20261120-1300-v1.4.0.coges'
        [IO.File]::WriteAllText((Join-Path $folder 'coges-b-20261119-1300-v1.4.0.coges.echec'), 'x')
        [IO.File]::WriteAllText((Join-Path $folder 'coges-b-20261118-1300-v1.4.0.coges'), 'sans compagnons')
        [IO.File]::WriteAllText((Join-Path $folder 'notes.txt'), 'à garder')
        $found = @(Get-CogesGoodBackup $folder)
        $found.Count | Should -Be 1
        $found[0].Path | Should -Be $good
        [void](Invoke-CogesRetention -Folder $folder -Now $script:Now)
        @(Get-ChildItem -LiteralPath $folder).Count | Should -Be 6
    }
}

Describe 'Quand sauvegarder, quand essayer' {
    It 'rattrapage : <case>' -ForEach @(
        @{ Case = 'jamais sauvegardé'; Now = '2026-11-20 09:00'; Last = $null; Due = $true }
        @{ Case = 'PC rallumé le matin, dernière d''hier 20 h 30'; Now = '2026-11-20 08:00'; Last = '2026-11-19 20:31'; Due = $false }
        @{ Case = 'PC éteint deux jours'; Now = '2026-11-20 08:00'; Last = '2026-11-18 20:31'; Due = $true }
        @{ Case = '13 h 00 manquée (PC rallumé à 15 h)'; Now = '2026-11-20 15:00'; Last = '2026-11-20 08:00'; Due = $true }
        @{ Case = '13 h 00 déjà faite'; Now = '2026-11-20 15:00'; Last = '2026-11-20 13:01'; Due = $false }
        @{ Case = '20 h 30 passée'; Now = '2026-11-20 20:31'; Last = '2026-11-20 13:01'; Due = $true }
        @{ Case = 'plus de 20 h sans heure prévue manquée'; Now = '2026-11-21 10:00'; Last = '2026-11-20 13:59'; Due = $true }
    ) {
        $previous = $null
        if ($Last) { $previous = [datetime]$Last }
        Test-CogesBackupDue -Now ([datetime]$Now) -LastGood $previous | Should -Be $Due
    }

    It 'essai : le dimanche, ou au premier passage après' {
        # 22/11/2026 est un dimanche.
        Test-CogesTrialDue -Now ([datetime]'2026-11-22 13:00') -LastSuccess ([datetime]'2026-11-15 13:00') | Should -BeTrue
        Test-CogesTrialDue -Now ([datetime]'2026-11-22 20:30') -LastSuccess ([datetime]'2026-11-22 13:00') | Should -BeFalse
        Test-CogesTrialDue -Now ([datetime]'2026-11-24 09:00') -LastSuccess ([datetime]'2026-11-15 13:00') | Should -BeTrue
        Test-CogesTrialDue -Now ([datetime]'2026-11-25 09:00') -LastSuccess ([datetime]'2026-11-23 09:00') | Should -BeFalse
        Test-CogesTrialDue -Now ([datetime]'2026-11-25 09:00') -LastSuccess $null | Should -BeTrue
    }
}

Describe 'Contrôles de taille et de place' {
    It 'taille : <case>' -ForEach @(
        @{ Case = 'vide'; Size = 0; Previous = 0; Ok = $false }
        @{ Case = 'première'; Size = 10; Previous = 0; Ok = $true }
        @{ Case = 'moitié pile'; Size = 50; Previous = 100; Ok = $true }
        @{ Case = 'moins de la moitié'; Size = 49; Previous = 100; Ok = $false }
        @{ Case = 'plus grande'; Size = 500; Previous = 100; Ok = $true }
    ) {
        Test-CogesSizePlausible -Size $Size -Previous $Previous | Should -Be $Ok
    }

    It '2 Go doivent rester libres après la sauvegarde prévue' {
        Test-CogesEnoughSpace -Free (3GB) -Planned (1GB) | Should -BeTrue
        Test-CogesEnoughSpace -Free (3GB) -Planned (1GB + 1) | Should -BeFalse
    }
}

Describe 'Repère d''un disque de sauvegarde' {
    It '<case>' -ForEach @(
        @{ Case = 'absent'; Text = $null; Want = 'absent' }
        @{ Case = 'autre boutique'; Text = "boutique-ndiaye`n"; Want = 'autre' }
        @{ Case = 'vide'; Text = ''; Want = 'autre' }
        @{ Case = 'présent, avec BOM et fin de ligne Windows'; Text = 'BOM:boutique-diallo'; Want = 'ok' }
    ) {
        if ($null -ne $Text -and $Text.StartsWith('BOM:')) { $Text = [string][char]0xFEFF + $Text.Substring(4) + "`r`n" }
        Get-CogesDiskMarkerState -MarkerText $Text -Slugs @('boutique-diallo') | Should -Be $Want
    }

    It 'copie hors du PC : seulement sur le disque de CETTE boutique, puis relue ; 10 gardées' {
        $paths = New-TestInstall
        $sans = Join-Path $TestDrive 'cle-sans-repere'
        $autre = Join-Path $TestDrive 'cle-autre'
        $bonne = Join-Path $TestDrive 'cle-bonne'
        New-Item -ItemType Directory -Force -Path $sans, $autre, $bonne | Out-Null
        [IO.File]::WriteAllText((Join-Path $autre $script:CogesDiskMarker), 'boutique-ndiaye')
        [IO.File]::WriteAllText((Join-Path $bonne $script:CogesDiskMarker), 'boutique-diallo')
        foreach ($day in 1..11) {
            [void](New-FakeBackup -Folder (Join-Path $bonne 'CoGes') -Name ('coges-boutique-diallo-202611{0:00}-1300-v1.4.0.coges' -f $day))
        }
        $source = New-FakeBackup -Folder (Join-Path $paths.Racine 'sauvegardes') -Name 'coges-boutique-diallo-20261120-1300-v1.4.0.coges' -Size 300
        $env:COGES_DISQUES_ESSAI = @($sans, $autre, $bonne) -join [IO.Path]::PathSeparator
        try {
            $copies = @(Copy-CogesOffsite -Paths $paths -Backup ([pscustomobject]@{ Path = $source; Name = (Split-Path -Leaf $source); Size = 300; Slugs = @('boutique-diallo') }) -Now (Get-Date))
        }
        finally { Remove-Item Env:\COGES_DISQUES_ESSAI }
        $copies.Count | Should -Be 1
        @(Get-ChildItem -LiteralPath $sans -Recurse).Count | Should -Be 0
        @(Get-ChildItem -LiteralPath $autre -Recurse).Count | Should -Be 1
        $kept = @(Get-CogesGoodBackup (Join-Path $bonne 'CoGes'))
        $kept.Count | Should -Be 10
        $kept[0].Name | Should -Be 'coges-boutique-diallo-20261120-1300-v1.4.0.coges'
        (Get-CogesFileSha256 $kept[0].Path) | Should -Be (Get-CogesFileSha256 $source)
        @(Get-ChildItem -LiteralPath (Join-Path $bonne 'CoGes') -Filter '*.partiel').Count | Should -Be 0
        (Read-CogesBackupState $paths)['derniere_copie_hors_pc'] | Should -Not -BeNullOrEmpty
    }
}

Describe 'Alertes et notifications' {
    It 'rien à dire quand tout va bien' {
        $now = [datetime]'2026-11-20 21:00'
        @(Get-CogesBackupAlert -Now $now -LastGood $now.AddHours(-1) -LastOffsite $now.AddDays(-1) -FreeBytes 50GB -TrialOk $true).Count | Should -Be 0
    }

    It 'chaque alerte en mots simples' {
        $now = [datetime]'2026-11-20 21:00'
        $alerts = @(Get-CogesBackupAlert -Now $now -LastGood $now.AddHours(-49) -LastOffsite $now.AddDays(-8) -FreeBytes 1GB -TrialOk $false)
        $alerts.Code | Should -Be @('sauvegarde', 'cle', 'disque', 'essai')
        ($alerts | Where-Object Code -EQ 'cle').Texte | Should -BeLike 'Branchez la clé CoGes*'
        ($alerts | Where-Object Code -EQ 'essai').Texte | Should -Be 'La dernière sauvegarde ne se relit pas : appelez CoGes.'
        foreach ($alert in $alerts) { $alert.Texte | Should -Not -Match 'pg_|sha256|Docker|SQL|manifest' }
    }

    It 'notification désactivable ; un échec n''en est jamais un pour la sauvegarde' {
        $script:CogesState.LogPath = $null
        $script:CogesToastEnabled = $false
        try { Show-CogesToast 'essai' | Should -BeFalse }
        finally { $script:CogesToastEnabled = $true }
        { Show-CogesToast 'essai' } | Should -Not -Throw
    }
}

Describe 'Clés de sauvegarde' {
    It 'X25519 : vecteurs du RFC 7748 (§ 6.1), comme coffre.py' -ForEach @(
        @{ Private = '77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a'; Public = '8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a' }
        @{ Private = '5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb'; Public = 'de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f' }
    ) {
        $bytes = [byte[]]($Private -split '(..)' | Where-Object { $_ } | ForEach-Object { [Convert]::ToByte($_, 16) })
        -join ((Get-CogesX25519Public $bytes) | ForEach-Object { $_.ToString('x2') }) | Should -Be $Public
    }

    It 'une paire : deux lignes au bon format, jamais deux fois la même' {
        $a = New-CogesKeyPair
        $b = New-CogesKeyPair
        Test-CogesKeyText -Text $a.Private -Kind Privee | Should -BeTrue
        Test-CogesKeyText -Text $a.Public -Kind Publique | Should -BeTrue
        Test-CogesKeyText -Text $a.Private -Kind Publique | Should -BeFalse
        $a.Public | Should -Not -Be $b.Public
    }

    It 'sans -ClePublique : la clé privée va dans un fichier du disque amovible, jamais à l''écran ni au journal' {
        $paths = New-TestInstall
        Remove-Item -LiteralPath (Get-CogesBackupPath $paths).ClePublique
        $usb = Join-Path $TestDrive 'usb-technicien'
        New-Item -ItemType Directory -Force -Path $usb | Out-Null
        # Sous Windows, le TestDrive est sur C: : le dossier est déclaré « disque » d'essai.
        $env:COGES_DISQUES_ESSAI = $usb
        try { Set-CogesBackupKey -Paths $paths -Options @{ ClePublique = ''; LecteurCle = $usb; CleCopiee = $true } -Slug 'boutique-diallo' 6>$null }
        finally { Remove-Item Env:\COGES_DISQUES_ESSAI }
        $files = @(Get-ChildItem -LiteralPath $usb -Filter 'CoGes-cle-privee-boutique-diallo-*.txt')
        $files.Count | Should -Be 1
        $private = [IO.File]::ReadAllText($files[0].FullName).Trim()
        Test-CogesKeyText -Text $private -Kind Privee | Should -BeTrue
        $secret = $private.Substring($script:CogesPrivatePrefix.Length)
        ($script:CogesState.Output -join "`n").Contains($secret) | Should -BeFalse
        [IO.File]::ReadAllText($script:CogesState.LogPath).Contains($secret) | Should -BeFalse
        # Aucune trace de la clé privée sous le dossier de CoGes.
        foreach ($file in (Get-ChildItem -LiteralPath $paths.Racine -Recurse -File)) {
            [IO.File]::ReadAllText($file.FullName).Contains($secret) | Should -BeFalse
        }
        # La publique posée est bien celle de la privée.
        $raw = ConvertFrom-CogesBase64Url $secret
        $public = $script:CogesPublicPrefix + (ConvertTo-CogesBase64Url (Get-CogesX25519Public $raw))
        [IO.File]::ReadAllText((Get-CogesBackupPath $paths).ClePublique).Trim() | Should -BeExactly $public
    }

    It 'refuse d''écrire la clé privée sous C:\CoGes' {
        $paths = New-TestInstall
        Remove-Item -LiteralPath (Get-CogesBackupPath $paths).ClePublique
        { Set-CogesBackupKey -Paths $paths -Options @{ ClePublique = ''; LecteurCle = $paths.Reglages; CleCopiee = $true } -Slug 'b' 6>$null } |
            Should -Throw '*disque amovible*'
        Test-Path -LiteralPath (Get-CogesBackupPath $paths).ClePublique | Should -BeFalse
    }

    It 'avec -ClePublique : seule la publique est posée ; un fichier de clé privée est refusé' {
        $paths = New-TestInstall
        $pair = New-CogesKeyPair
        $file = Join-Path $TestDrive 'cle.pub'
        [IO.File]::WriteAllText($file, $pair.Public + "`r`n")
        Set-CogesBackupKey -Paths $paths -Options @{ ClePublique = $file } -Slug 'b' 6>$null
        [IO.File]::ReadAllText((Get-CogesBackupPath $paths).ClePublique).Trim() | Should -BeExactly $pair.Public
        $wrong = Join-Path $TestDrive 'cle.prive'
        [IO.File]::WriteAllText($wrong, $pair.Private)
        { Set-CogesBackupKey -Paths $paths -Options @{ ClePublique = $wrong } -Slug 'b' 6>$null } | Should -Throw '*clé publique*'
    }
}

Describe 'Verrou commun' {
    It 'pris : l''action s''arrête avec un message clair qui nomme l''autre opération' {
        $paths = New-TestInstall
        $held = Enter-CogesLock -Paths $paths -Action 'Restaurer'
        try {
            { Enter-CogesLock -Paths $paths -Action 'Sauvegarder' } | Should -Throw '*Restaurer*'
            $code = Invoke-CogesMain -Action Sauvegarder -Racine $paths.Racine -NonInteractif -SansNotification 6>$null
            $code | Should -Be 1
            ($script:CogesState.Output -join "`n") | Should -Match 'Une autre opération de CoGes est en cours'
        }
        finally { Exit-CogesLock $held }
    }

    It 'pris : attend, puis prend la main dès qu''il est rendu' {
        $paths = New-TestInstall
        $held = Enter-CogesLock -Paths $paths -Action 'Essai'
        try {
            { Enter-CogesLock -Paths $paths -Action 'Attente' -WaitSeconds 1 -IntervalSeconds 1 } | Should -Throw '*en cours*'
        }
        finally { Exit-CogesLock $held }
        $lock = Enter-CogesLock -Paths $paths -Action 'Après' -WaitSeconds 5 -IntervalSeconds 1
        $lock | Should -Not -BeNullOrEmpty
        Exit-CogesLock $lock
    }

    It 'laissé par un processus mort : repris' {
        $paths = New-TestInstall
        $backup = Get-CogesBackupPath $paths
        # Ce qui reste d'un processus tué : le fichier et son info, aucun fichier ouvert.
        [IO.File]::WriteAllText($backup.Verrou, '')
        [IO.File]::WriteAllText($backup.Verrou + '.info', 'Sauvegarde planifiée (processus 999999) depuis le 01/01/2026 à 13:00')
        $lock = Enter-CogesLock -Paths $paths -Action 'Sauvegarder'
        $lock | Should -Not -BeNullOrEmpty
        Exit-CogesLock $lock
    }

    It 'la tâche de démarrage n''appelle pas « up -d » pendant une restauration' {
        $paths = New-TestInstall
        Mock Invoke-Docker { New-DockerResult 0 @('linux') }
        $held = Enter-CogesLock -Paths $paths -Action 'Restaurer'
        try { Start-CogesAtLogon -Racine $paths.Racine -LockWaitSeconds 1 | Should -Be 1 }
        finally { Exit-CogesLock $held }
        Should -Invoke Invoke-Docker -ParameterFilter { $Arguments -contains 'up' } -Times 0 -Exactly
    }

    It 'Reparer s''arrête aussi devant le verrou' {
        $paths = New-TestInstall
        Mock Invoke-Docker { throw 'docker ne doit pas être appelé' }
        $held = Enter-CogesLock -Paths $paths -Action 'Sauvegarde planifiée'
        try {
            Invoke-CogesMain -Action Reparer -Racine $paths.Racine -NonInteractif -CodeBoutique 'boutique-diallo' 6>$null | Should -Be 1
            ($script:CogesState.Output -join "`n") | Should -Match 'Sauvegarde planifiée'
        }
        finally { Exit-CogesLock $held }
    }
}

Describe 'Faire une sauvegarde (docker remplacé)' {
    It 'chiffrée, empreinte écrite et relue, manifeste complet, volume vidé' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-1')
        $made = New-CogesBackup -Paths $paths -Now ([datetime]'2026-11-20 13:00') 6>$null
        $made.Name | Should -BeExactly 'coges-boutique-diallo-20261120-1300-v1.4.0.coges'
        Test-Path -LiteralPath ($made.Path + '.sha256') | Should -BeTrue
        $manifest = [IO.File]::ReadAllText($made.Path + '.manifest.json') | ConvertFrom-Json
        $manifest.sha256 | Should -Be (Get-CogesFileSha256 $made.Path)
        $manifest.pg_dump_version | Should -Be '18.7'
        $manifest.alembic_revision | Should -Be '0042'
        @(Get-ChildItem -LiteralPath (Join-Path $TestDrive 'travail-1')).Count | Should -Be 0
        @(Get-ChildItem -LiteralPath (Get-CogesBackupPath $paths).Dossier -Filter '*.partiel').Count | Should -Be 0
        @(Get-ChildItem -LiteralPath (Get-CogesBackupPath $paths).Dossier -Filter '*.dump').Count | Should -Be 0
        @($script:DockerCalls | Where-Object { $_.Arguments -contains 'vider' }).Count | Should -Be 1
    }

    It 'disque plein pendant le dump : échec clair, volume vidé quand même, aucun fichier compté' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-2') -Behaviour @{ DumpFails = $true }
        { New-CogesBackup -Paths $paths -Now ([datetime]'2026-11-20 13:00') 6>$null } | Should -Throw '*No space left on device*'
        @($script:DockerCalls | Where-Object { $_.Arguments -contains 'vider' }).Count | Should -Be 1
        @(Get-CogesGoodBackup (Get-CogesBackupPath $paths).Dossier).Count | Should -Be 0
    }

    It 'moins de la moitié de la précédente (même base) : marquée .echec, jamais comptée' {
        $paths = New-TestInstall
        $folder = (Get-CogesBackupPath $paths).Dossier
        [void](New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261119-1300-v1.4.0.coges' -Size 1000 -BaseId 'base-1')
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-3') -Behaviour @{ SealedSize = 400; BaseId = 'base-1' }
        { New-CogesBackup -Paths $paths -Now ([datetime]'2026-11-20 13:00') 6>$null } | Should -Throw '*moins de la moitié*'
        Test-Path -LiteralPath (Join-Path $folder 'coges-boutique-diallo-20261120-1300-v1.4.0.coges.echec') | Should -BeTrue
        @(Get-CogesGoodBackup $folder).Count | Should -Be 1
        @($script:DockerCalls | Where-Object { $_.Arguments -contains 'vider' }).Count | Should -Be 1
    }

    It 'base neuve (installation ou restauration) : la comparaison repart de zéro' {
        $paths = New-TestInstall
        $folder = (Get-CogesBackupPath $paths).Dossier
        [void](New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261119-1300-v1.4.0.coges' -Size 1000 -BaseId 'ancienne')
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-4') -Behaviour @{ SealedSize = 400; BaseId = 'neuve' }
        (New-CogesBackup -Paths $paths -Now ([datetime]'2026-11-20 13:00') 6>$null).Size | Should -Be 400
    }

    It 'refusée sans 2 Go libres après la sauvegarde prévue' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-5') -Behaviour @{ BaseOctets = [long](1000 * 1TB) }
        { New-CogesBackup -Paths $paths -Now ([datetime]'2026-11-20 13:00') 6>$null } | Should -Throw '*Pas assez de place*'
        @($script:DockerCalls | Where-Object { $_.Arguments -contains 'dump' }).Count | Should -Be 0
    }

    It 'sans clé publique : rien n''est lancé' {
        $paths = New-TestInstall
        Remove-Item -LiteralPath (Get-CogesBackupPath $paths).ClePublique
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-6')
        { New-CogesBackup -Paths $paths 6>$null } | Should -Throw '*clé publique*'
        $script:DockerCalls.Count | Should -Be 0
    }

    It 'aucun secret de coges.env dans le journal ni dans un argument' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-7')
        [void](New-CogesBackup -Paths $paths -Trial 6>$null)
        $values = Read-CogesEnvFile $paths.EnvFile
        $log = [IO.File]::ReadAllText($script:CogesState.LogPath)
        foreach ($key in @($script:CogesSecretKeys) + 'COGES_MFA_ENCRYPTION_KEY') {
            $log.Contains($values[$key]) | Should -BeFalse
            foreach ($call in $script:DockerCalls) { ($call.Arguments -join ' ').Contains($values[$key]) | Should -BeFalse }
        }
        foreach ($call in $script:DockerCalls) { $call.Arguments | Should -Not -Contain '-e' }
    }
}

Describe 'Restaurer (docker remplacé)' {
    BeforeAll {
        function New-TestRestoreInput {
            param([string] $Revision = '0042')
            $folder = Join-Path $TestDrive ('usb-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
            $file = New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261120-1300-v1.4.0.coges'
            $manifest = [IO.File]::ReadAllText($file + '.manifest.json') | ConvertFrom-Json
            $manifest.alembic_revision = $Revision
            $manifest.coges_version = 'v9.9.9'
            [IO.File]::WriteAllText($file + '.manifest.json', ($manifest | ConvertTo-Json -Depth 4))
            $key = Join-Path $folder 'cle.txt'
            [IO.File]::WriteAllText($key, (New-CogesKeyPair).Private + "`n")
            return [pscustomobject]@{ File = $file; Key = $key; Secret = ([IO.File]::ReadAllText($key).Trim()) }
        }
    }

    It 'un octet changé : refusé à l''étape 1, rien n''est lancé' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-r1')
        $given = New-TestRestoreInput
        $bytes = [IO.File]::ReadAllBytes($given.File)
        $bytes[10] = $bytes[10] -bxor 1
        [IO.File]::WriteAllBytes($given.File, $bytes)
        $code = Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $given.File -Cle $given.Key -NonInteractif -ConfirmerRestauration -SansNotification 6>$null
        $code | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match 'sha256'
        $script:DockerCalls.Count | Should -Be 0
    }

    It 'sauvegarde plus récente que le programme : refusée, « installez d''abord la version »' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-r2')
        $given = New-TestRestoreInput -Revision '0099'
        $code = Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $given.File -Cle $given.Key -NonInteractif -ConfirmerRestauration -SansNotification 6>$null
        $code | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match 'Installez d''abord la version v9\.9\.9'
        @($script:DockerCalls | Where-Object { ($_.Arguments -join ' ') -match 'dechiffrer|bascule|preparer' }).Count | Should -Be 0
    }

    It 'sans RESTAURER confirmé : rien n''est changé' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-r3')
        $given = New-TestRestoreInput
        Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $given.File -Cle $given.Key -NonInteractif -SansNotification 6>$null | Should -Be 1
        # Seule la lecture de la base actuelle (nombre de ventes) a eu lieu.
        @($script:DockerCalls | Where-Object { ($_.Arguments -join ' ') -notmatch 'base\.py etat' }).Count | Should -Be 0
    }

    It 'la clé privée ne passe que par l''entrée standard : ni argument, ni -e, ni journal, ni écran' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-r4')
        $given = New-TestRestoreInput
        Mock Invoke-CogesCompose { New-DockerResult 0 @() }
        Mock Wait-CogesHealthy { }
        Mock Get-CogesLicenseStatus { New-DockerResult 0 @('Accès : actif', 'Fin de période : sans fin') }
        Mock Test-CogesSite { }
        [void](Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $given.File -Cle $given.Key -NonInteractif -ConfirmerRestauration -SansNotification 6>$null)
        $secret = $given.Secret.Substring($script:CogesPrivatePrefix.Length)
        $decrypt = @($script:DockerCalls | Where-Object { ($_.Arguments -join ' ') -match 'dechiffrer' })
        $decrypt.Count | Should -Be 1
        $decrypt[0].InputText | Should -BeExactly $given.Secret
        foreach ($call in $script:DockerCalls) {
            ($call.Arguments -join ' ').Contains($secret) | Should -BeFalse
            $call.Arguments | Should -Not -Contain '-e'
        }
        [IO.File]::ReadAllText($script:CogesState.LogPath).Contains($secret) | Should -BeFalse
        ($script:CogesState.Output -join "`n").Contains($secret) | Should -BeFalse
        # La clé n'est copiée nulle part sous le dossier de CoGes.
        foreach ($file in (Get-ChildItem -LiteralPath $paths.Racine -Recurse -File)) {
            [IO.File]::ReadAllText($file.FullName).Contains($secret) | Should -BeFalse
        }
    }

    It 'échec après la bascule : retour automatique à l''ancienne base' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-r5')
        $given = New-TestRestoreInput
        Mock Invoke-CogesCompose { New-DockerResult 0 @() }
        Mock Wait-CogesHealthy { }
        Mock Get-CogesLicenseStatus { New-DockerResult 0 @('Accès : suspendu') }
        Mock Test-CogesSite { }
        Mock Invoke-CogesTool -ParameterFilter { $Arguments -contains 'bascule' } { New-DockerResult 0 @('{"ancienne": "coges_avant_20261120_1300"}') }
        Mock Invoke-CogesTool -ParameterFilter { $Arguments -contains 'retour' } { New-DockerResult 0 @('{"remise": "coges_avant_20261120_1300"}') }
        $code = Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $given.File -Cle $given.Key -NonInteractif -ConfirmerRestauration -SansNotification 6>$null
        $code | Should -Be 1
        Should -Invoke Invoke-CogesTool -ParameterFilter { $Arguments -contains 'retour' } -Times 1 -Exactly
        ($script:CogesState.Output -join "`n") | Should -Match 'ancienne base est remise en place'
    }
}

Describe 'Simulation : rien d''écrit, docker jamais appelé' {
    It '<action>' -ForEach @(@{ Action = 'Sauvegarder' }, @{ Action = 'Restaurer' }, @{ Action = 'PreparerDisque' }, @{ Action = 'NettoyerAncienneBase' }) {
        $racine = Join-Path $TestDrive ('sim-' + [Guid]::NewGuid().ToString('N').Substring(0, 6))
        Mock Invoke-Docker { throw 'docker ne doit pas être appelé' }
        $code = Invoke-CogesMain -Action $Action -Racine $racine -Simulation -NonInteractif -CodeBoutique 'boutique-diallo' `
            -Fichier 'E:\coges-b-20261120-1300-v1.4.0.coges' -Cle 'E:\cle.txt' -Lecteur 'E:' -SansNotification 6>$null
        $code | Should -Be 0
        Test-Path -LiteralPath $racine | Should -BeFalse
        Should -Invoke Invoke-Docker -Times 0 -Exactly
    }
}

Describe 'La tâche planifiée « CoGes - sauvegarde »' {
    It 'Docker éteint : journal seulement, aucune exception, aucun fichier de sauvegarde' {
        $paths = New-TestInstall
        Mock Invoke-Docker { New-DockerResult 1 @('error during connect: is the docker daemon running?') }
        Mock Show-CogesToast { $true }
        $script:CogesToastEnabled = $false
        try { Invoke-CogesScheduledBackup -Racine $paths.Racine -Now ([datetime]'2026-11-20 13:00') | Should -Be 0 }
        finally { $script:CogesToastEnabled = $true }
        $log = Get-ChildItem -LiteralPath $paths.Journaux -Filter 'sauvegarde-*.log'
        [IO.File]::ReadAllText($log[0].FullName) | Should -Match 'Docker ne répond pas'
        Test-Path -LiteralPath (Get-CogesBackupPath $paths).Dossier | Should -BeFalse
        Should -Invoke Show-CogesToast -ParameterFilter { $Text -like 'CoGes n''a pas pu sauvegarder*' } -Times 1
    }
}

Describe 'Bloc 0 du lot 5 : la bonne sauvegarde, et Docker arrêté' {
    It 'une sauvegarde faite avant une action porte sa raison, et se relit comme les autres' {
        $name = Get-CogesBackupName -Slug 'boutique-diallo' -Date ([datetime]'2026-11-21 21:30') -Version 'v0.3.0' -Raison 'avant-maj'
        $name | Should -BeExactly 'coges-boutique-diallo-20261121-2130-v0.3.0-avant-maj.coges'
        $parsed = ConvertFrom-CogesBackupName $name
        $parsed.Version | Should -BeExactly 'v0.3.0'
        $parsed.Raison | Should -BeExactly 'avant-maj'
        $parsed.Slug | Should -BeExactly 'boutique-diallo'
        (ConvertFrom-CogesBackupName 'coges-b-20261121-2130-v0.3.0.coges').Raison | Should -BeExactly ''
        { Get-CogesBackupName -Slug 'b' -Date (Get-Date) -Version 'v0.3.0' -Raison 'n-importe-quoi' } | Should -Throw '*inconnue*'
    }

    It '<raison> : reconnue' -ForEach @(@{ Raison = 'avant-effacement' }, @{ Raison = 'avant-restauration' }, @{ Raison = 'avant-maj' }, @{ Raison = 'avant-retour' }, @{ Raison = 'installation' }) {
        $name = Get-CogesBackupName -Slug 'b' -Date ([datetime]'2026-11-21 10:00') -Version 'v1.4.0' -Raison $Raison
        (ConvertFrom-CogesBackupName $name).Raison | Should -BeExactly $Raison
    }

    It 'New-CogesBackup -Raison : le nom l''annonce, la rétention et Get-CogesGoodBackup la comptent' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-b0')
        $made = New-CogesBackup -Paths $paths -Now ([datetime]'2026-11-21 21:30') -Raison 'avant-maj' 6>$null
        $made.Name | Should -BeExactly 'coges-boutique-diallo-20261121-2130-v1.4.0-avant-maj.coges'
        @(Get-CogesGoodBackup (Get-CogesBackupPath $paths).Dossier).Name | Should -Contain $made.Name
    }

    It 'avertissement renforcé : <cas>' -ForEach @(
        @{ Cas = 'aucune vente'; Backup = 0; Current = 5; Expected = '*AUCUNE vente*5 vente(s)*perdues*' }
        @{ Cas = 'moins que la base'; Backup = 3; Current = 10; Expected = '*3 vente(s)*10*7 vente(s) seraient perdues*' }
        @{ Cas = 'nombre inconnu'; Backup = $null; Current = 4; Expected = '*ne dit pas*' }
    ) {
        Get-CogesRestoreLoss -BackupSales $Backup -CurrentSales $Current | Should -BeLike $Expected
    }

    It 'pas d''avertissement quand la sauvegarde a autant de ventes ou plus' {
        Get-CogesRestoreLoss -BackupSales 12 -CurrentSales 12 | Should -BeNullOrEmpty
        Get-CogesRestoreLoss -BackupSales 12 -CurrentSales 0 | Should -BeNullOrEmpty
    }

    It 'Restaurer sans -Fichier en -NonInteractif : refusé, rien n''est lancé' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-b1')
        $key = Join-Path $TestDrive 'cle-b1.txt'
        [IO.File]::WriteAllText($key, (New-CogesKeyPair).Private + "`n")
        Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Cle $key -NonInteractif -ConfirmerRestauration -SansNotification 6>$null | Should -Be 1
        ($script:CogesState.Output -join "`n") | Should -Match 'passez -Fichier'
        $script:DockerCalls.Count | Should -Be 0
    }

    It 'la liste : PC et clé CoGes, la plus récente en haut, avec version, ventes, sociétés, origine et raison' {
        $paths = New-TestInstall
        $usb = Join-Path $TestDrive 'usb-liste'
        New-Item -ItemType Directory -Force -Path (Join-Path $usb 'CoGes') | Out-Null
        [IO.File]::WriteAllText((Join-Path $usb $script:CogesDiskMarker), "boutique-diallo`n")
        $folder = (Get-CogesBackupPath $paths).Dossier
        [void](New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261120-1300-v1.4.0.coges' -Sales 40)
        [void](New-FakeBackup -Folder (Join-Path $usb 'CoGes') -Name 'coges-boutique-diallo-20261121-0900-v1.4.0-installation.coges' -Sales 0)
        # Vue sur le PC ET sur la clé : une seule ligne, celle du PC.
        [void](New-FakeBackup -Folder (Join-Path $usb 'CoGes') -Name 'coges-boutique-diallo-20261120-1300-v1.4.0.coges' -Sales 40)
        $previous = $env:COGES_DISQUES_ESSAI
        $env:COGES_DISQUES_ESSAI = $usb
        try { $list = @(Get-CogesRestoreCandidate $paths) }
        finally { $env:COGES_DISQUES_ESSAI = $previous }
        $list.Count | Should -Be 2
        $list[0].Name | Should -BeLike '*20261121-0900*'
        $list[0].Ventes | Should -Be 0
        $list[0].Origine | Should -BeLike 'clé *'
        $list[1].Origine | Should -BeExactly 'PC'
        $list[1].Ventes | Should -Be 40
        $line = Format-CogesRestoreCandidate -Candidate $list[0] -Number 1
        $line | Should -Match '^\s+1\. 21/11/2026 09:00\s+v1\.4\.0\s+0 vente\(s\), 1 société\(s\)\s+clé '
        $line | Should -Match 'installation : base neuve'
    }

    It 'la liste, puis le numéro tapé : c''est cette sauvegarde qui est lue' {
        $paths = New-TestInstall
        $folder = (Get-CogesBackupPath $paths).Dossier
        $older = New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261120-1300-v1.4.0.coges'
        [void](New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261121-1300-v1.4.0.coges')
        $script:CogesState.NonInteractif = $false
        Mock Read-Host { '2' }
        try { $chosen = Select-CogesRestoreFile $paths 6>$null }
        finally { $script:CogesState.NonInteractif = $true }
        $chosen | Should -BeExactly $older
        ($script:CogesState.Output -join "`n") | Should -Match '1\. 21/11/2026 13:00'
    }

    It 'sauvegarde à 0 vente, base actuelle à 5 : RESTAURER ne suffit pas, il faut RESTAURER-QUAND-MEME' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-b2') -Behaviour @{ Ventes = 5 }
        $folder = Join-Path $TestDrive 'usb-b2'
        $file = New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261121-0900-v1.4.0-installation.coges' -Sales 0
        $key = Join-Path $folder 'cle.txt'
        [IO.File]::WriteAllText($key, (New-CogesKeyPair).Private + "`n")
        $code = Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $file -Cle $key -NonInteractif -ConfirmerRestauration -SansNotification 6>$null
        $code | Should -Be 1
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match 'AUCUNE vente'
        $text | Should -Match 'Les 5 vente\(s\) de ce PC seraient perdues'
        $text | Should -Match 'RESTAURER-QUAND-MEME'
        @($script:DockerCalls | Where-Object { ($_.Arguments -join ' ') -match 'dechiffrer|bascule|preparer|dump' }).Count | Should -Be 0
    }

    It 'avec -RestaurerQuandMeme : la restauration continue' {
        $paths = New-TestInstall
        Install-FakeDocker -Work (Join-Path $TestDrive 'travail-b3') -Behaviour @{ Ventes = 5 }
        $folder = Join-Path $TestDrive 'usb-b3'
        $file = New-FakeBackup -Folder $folder -Name 'coges-boutique-diallo-20261121-0900-v1.4.0.coges' -Sales 0
        $key = Join-Path $folder 'cle.txt'
        [IO.File]::WriteAllText($key, (New-CogesKeyPair).Private + "`n")
        Mock Invoke-CogesCompose { New-DockerResult 0 @() }
        Mock Wait-CogesHealthy { }
        Mock Get-CogesLicenseStatus { New-DockerResult 0 @('Accès : actif', 'Fin de période : sans fin') }
        Mock Test-CogesSite { }
        Mock Invoke-CogesTool -ParameterFilter { $Arguments -contains 'bascule' } { New-DockerResult 0 @('{"ancienne": "coges_avant_20261121_0900"}') }
        $code = Invoke-CogesMain -Action Restaurer -Racine $paths.Racine -Fichier $file -Cle $key -NonInteractif -RestaurerQuandMeme -SansNotification 6>$null
        ($script:CogesState.Output -join "`n") | Should -Not -Match 'ÉCHEC'
        $code | Should -Be 0
        @($script:DockerCalls | Where-Object { ($_.Arguments -join ' ') -match 'dechiffrer' }).Count | Should -Be 1
    }

    It 'Docker Desktop arrêté : <action> le dit en clair, avant de rien changer' -ForEach @(
        @{ Action = 'Sauvegarder' }, @{ Action = 'Restaurer' }, @{ Action = 'NettoyerAncienneBase' }, @{ Action = 'PreparerDisque' }, @{ Action = 'Desinstaller' }) {
        $paths = New-TestInstall
        Mock Get-Command -ParameterFilter { $Name -eq 'docker' } { [pscustomobject]@{ Name = 'docker' } }
        Mock Invoke-Docker { New-DockerResult 1 @('error during connect: Get "http://%2F%2F.%2Fpipe%2FdockerDesktopLinuxEngine/v1.47/version": open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.') }
        $code = Invoke-CogesMain -Action $Action -Racine $paths.Racine -NonInteractif -Fichier 'x.coges' -Cle 'x.txt' -Lecteur 'E:' -CodeBoutique 'boutique-diallo' -SansNotification 6>$null
        $code | Should -Be 1
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match ([regex]::Escape('Docker Desktop ne tourne pas : ouvrez-le et attendez « Engine running », puis relancez. Rien n''a changé.'))
        $text | Should -Not -Match 'code 1'
        Should -Invoke Invoke-Docker -Times 1 -Exactly
        Test-Path -LiteralPath (Get-CogesBackupPath $paths).Dossier | Should -BeFalse
    }

    It 'Etat avec Docker arrêté : le message, puis ce que disent les fichiers' {
        $paths = New-TestInstall
        Mock Get-Command -ParameterFilter { $Name -eq 'docker' } { [pscustomobject]@{ Name = 'docker' } }
        Mock Invoke-Docker { New-DockerResult 1 @('error during connect: is the docker daemon running?') }
        Invoke-CogesMain -Action Etat -Racine $paths.Racine -NonInteractif -SansNotification 6>$null | Should -Be 0
        $text = $script:CogesState.Output -join "`n"
        $text | Should -Match 'Docker Desktop ne tourne pas'
        $text | Should -Match 'Dernière sauvegarde'
        Should -Invoke Invoke-Docker -Times 1 -Exactly
    }
}
