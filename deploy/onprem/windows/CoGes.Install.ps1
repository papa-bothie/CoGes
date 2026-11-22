# CoGes sur site — fonctions de l'installation Windows (ADR 0126).
#
# Dot-sourcé par installer.ps1 (le point d'entrée), par demarrage.ps1 (la tâche planifiée)
# et par les tests Pester (tests/CoGes.Install.Tests.ps1). Ce fichier ne fait rien seul.
#
# Compatible Windows PowerShell 5.1 (celui de Windows 11) ET PowerShell 7 : ni « ?? », ni
# ternaire, ni « && ». Enregistré en UTF-8 AVEC BOM (sans lui, 5.1 lit les accents de
# travers), fins de ligne LF (deploy/onprem/.gitattributes).
#
# Règles tenues ici :
#   - tout appel à docker passe par Invoke-Docker (une seule fonction, remplacée en test) ;
#   - aucun secret n'est affiché ni écrit dans le journal (Mask-Secrets sur chaque ligne) ;
#   - coges.env n'est jamais réécrit : créé une fois (CreateNew), puis seules les lignes de
#     la liste blanche (port, adresse, version) peuvent changer, par Reparer ;
#   - le mot de passe du gérant n'est jamais lu par ce script : la commande create-company
#     le demande elle-même, sans écho, dans la console (getpass).

Set-StrictMode -Version Latest

# ---------------------------------------------------------------------------- constantes

$script:CogesRegistry = 'ghcr.io/papa-bothie/coges'
$script:CogesRepository = 'papa-bothie/CoGes'
$script:CogesProject = 'coges-onprem'
$script:CogesTaskName = 'CoGes - démarrage'
$script:CogesDockerDownload = 'https://docs.docker.com/desktop/setup/install/windows-install/'

#: Les huit mots de passe du modèle (check_onprem_env.py, SECRETS) et la clé de chiffrement.
$script:CogesSecretKeys = @(
    'COGES_POSTGRES_PASSWORD',
    'COGES_OWNER_PASSWORD',
    'COGES_APP_PASSWORD',
    'COGES_RELAY_PASSWORD',
    'COGES_ANALYTICS_PASSWORD',
    'COGES_PLATFORM_PASSWORD',
    'COGES_REDIS_PASSWORD',
    'COGES_JWT_SECRET'
)
$script:CogesMfaKey = 'COGES_MFA_ENCRYPTION_KEY'

#: Les seules lignes de coges.env que le script peut changer dans un fichier existant.
$script:CogesEditableKeys = @('COGES_HTTP_PORT', 'COGES_PUBLIC_URL', 'COGES_IMAGE_TAG')

#: Les neuf services continus du compose (docker-compose.yml, hors profil tools).
$script:CogesServices = @('caddy', 'autoheal', 'postgres', 'redis', 'front', 'api', 'worker', 'beat', 'relay')

#: Ce que le dossier du programme doit contenir après la pose.
$script:CogesProgrammeFiles = @(
    'docker-compose.yml',
    'Caddyfile',
    'maintenance.html',
    'coges.env.example',
    'check_onprem_env.py',
    'postgres-init/01-roles.sql',
    'sauvegarde/pg.sh',
    'sauvegarde/coffre.py',
    'sauvegarde/base.py',
    'sauvegarde/verify_restore.py',
    'windows/sauvegarde.ps1',
    'windows/mise-a-jour.ps1'
)
#: Lus par un conteneur Linux : un « \r » les casserait.
$script:CogesLfFiles = @('Caddyfile', 'postgres-init/01-roles.sql', 'sauvegarde/pg.sh')

#: Les actions qui appellent Docker et contrôlent d'abord son moteur (lot 5, bloc 0).
#: Desinstaller le contrôle lui-même, après ses refus qui ne demandent pas Docker.
$script:CogesDockerActions = @('Sauvegarder', 'Restaurer', 'PreparerDisque', 'NettoyerAncienneBase', 'VerifierMiseAJour', 'MettreAJour', 'RevenirVersionPrecedente')

#: Offres et nombre de comptes actifs (révision 0028, ADR 0091).
$script:CogesPlans = [ordered]@{ starter = 3; business = 7; premium = 10 }

#: État de la session : rempli par Initialize-CogesSession.
$script:CogesState = @{
    Simulation    = $false
    NonInteractif = $false
    LogPath       = $null
    MaskValues    = @()
    Output        = New-Object System.Collections.Generic.List[string]
}

# ---------------------------------------------------------------------------- messages

function Stop-CogesStep {
    <# Arrête avec « ce qui ne va pas » et « quoi faire ». Jamais de trace technique. #>
    param(
        [Parameter(Mandatory)] [string] $Probleme,
        [Parameter(Mandatory)] [string] $QuoiFaire
    )
    $exception = New-Object System.InvalidOperationException ($Probleme + "`n" + 'Quoi faire : ' + $QuoiFaire)
    $exception.Data['CogesMessage'] = $true
    throw $exception
}

function Test-CogesMessage {
    <# Vrai si l'erreur vient de Stop-CogesStep (message prévu), faux pour une erreur imprévue. #>
    param([Parameter(Mandatory)] [System.Exception] $Exception)
    return [bool]$Exception.Data.Contains('CogesMessage')
}

function Mask-Secrets {
    <# Retire d'une ligne toute valeur lue dans coges.env (mots de passe, clé). #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseApprovedVerbs', '',
        Justification = 'Nom imposé par le prompt du lot 3 (bloc F) ; aucune commande exportée.')]
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSUseSingularNouns', '',
        Justification = 'Nom imposé par le prompt du lot 3 (bloc F).')]
    param(
        [AllowEmptyString()] [AllowNull()] [string] $Line,
        [string[]] $Values = $script:CogesState.MaskValues
    )
    if ($null -eq $Line) { return '' }
    $masked = $Line
    foreach ($value in @($Values)) {
        # Une valeur trop courte masquerait des mots ordinaires : les secrets en ont 43 ou 64.
        if ($value -and $value.Length -ge 8) {
            $masked = $masked.Replace($value, '********')
        }
    }
    return $masked
}

function Write-Log {
    <# Ajoute une ligne au journal de la session (jamais en simulation), secrets masqués. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSAvoidOverwritingBuiltInCmdlets', '',
        Justification = 'Nom imposé par le prompt du lot 3 (bloc F) ; aucun Write-Log dans Windows PowerShell 5.1.')]
    param(
        [AllowEmptyString()] [string] $Message,
        [ValidateSet('INFO', 'OK', 'ATTENTION', 'ECHEC', 'DOCKER')] [string] $Level = 'INFO'
    )
    $path = $script:CogesState.LogPath
    if ($script:CogesState.Simulation -or -not $path) { return }
    $stamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    $line = '{0} [{1}] {2}' -f $stamp, $Level, (Mask-Secrets $Message)
    [IO.File]::AppendAllText($path, $line + "`n", (New-Object Text.UTF8Encoding $false))
}

function Write-CogesLine {
    <# Une ligne pour le technicien : à l'écran, gardée pour les tests, et au journal. #>
    param(
        [AllowEmptyString()] [string] $Message,
        [ValidateSet('Info', 'Ok', 'Attention', 'Echec', 'Titre')] [string] $Kind = 'Info'
    )
    $text = Mask-Secrets $Message
    $script:CogesState.Output.Add($text)
    $colors = @{ Info = 'Gray'; Ok = 'Green'; Attention = 'Yellow'; Echec = 'Red'; Titre = 'Cyan' }
    Write-Host $text -ForegroundColor $colors[$Kind]
    $levels = @{ Info = 'INFO'; Ok = 'OK'; Attention = 'ATTENTION'; Echec = 'ECHEC'; Titre = 'INFO' }
    Write-Log -Message $text -Level $levels[$Kind]
}

function Invoke-CogesStep {
    <# Une étape : annoncée seulement en simulation ; sinon jouée, chronométrée, journalisée. #>
    param(
        [Parameter(Mandatory)] [string] $Title,
        [Parameter(Mandatory)] [scriptblock] $Action
    )
    if ($script:CogesState.Simulation) {
        Write-CogesLine ('[simulation] ' + $Title)
        return
    }
    Write-CogesLine ('» ' + $Title) -Kind Titre
    $watch = [Diagnostics.Stopwatch]::StartNew()
    # Une étape ne rend rien : une valeur oubliée ne doit pas devenir le code de sortie.
    & $Action | Out-Null
    Write-Log -Message ('fin : {0} ({1:N1} s)' -f $Title, $watch.Elapsed.TotalSeconds)
}

# ---------------------------------------------------------------------------- validations

function Test-CogesVersion {
    <# Une étiquette vX.Y.Z, jamais vide ni « latest ». #>
    param([AllowEmptyString()] [AllowNull()] [string] $Version)
    if (-not $Version) { return $false }
    return [bool]($Version -cmatch '^v[0-9]+\.[0-9]+\.[0-9]+$')
}

function Assert-CogesVersion {
    param([AllowEmptyString()] [AllowNull()] [string] $Version)
    if (-not (Test-CogesVersion $Version)) {
        $lu = $Version
        if (-not $lu) { $lu = '(vide)' }
        Stop-CogesStep -Probleme ('La version « {0} » n''est pas une version de CoGes.' -f $lu) `
            -QuoiFaire 'Relancez avec -Version suivie de la version donnée par CoGes, au format vX.Y.Z (par exemple -Version v1.4.0). Jamais « latest ».'
    }
}

function Test-CogesSlug {
    <# Le code de la boutique : minuscules, chiffres, tirets entre deux mots. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Slug)
    if (-not $Slug) { return $false }
    return [bool]($Slug -cmatch '^[a-z0-9]+(-[a-z0-9]+)*$')
}

function ConvertTo-CogesSlug {
    <# Propose un code de boutique à partir de son nom : « Boutique Diallo & Fils » → boutique-diallo-fils. #>
    param([AllowEmptyString()] [string] $Name)
    $decomposed = $Name.Normalize([Text.NormalizationForm]::FormD)
    $builder = New-Object Text.StringBuilder
    foreach ($character in $decomposed.ToCharArray()) {
        if ([Globalization.CharUnicodeInfo]::GetUnicodeCategory($character) -ne [Globalization.UnicodeCategory]::NonSpacingMark) {
            [void]$builder.Append($character)
        }
    }
    $slug = $builder.ToString().ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    return $slug.Trim('-')
}

function Test-CogesText {
    <# Un texte passé en argument à docker : ni guillemet double (Windows PowerShell 5.1 le
       transmettrait mal), ni retour à la ligne. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Text, [int] $Max = 120)
    if (-not $Text) { return $false }
    $trimmed = $Text.Trim()
    return ($trimmed.Length -ge 2 -and $trimmed.Length -le $Max -and $trimmed -notmatch '["\r\n]')
}

function Test-CogesPhone {
    param([AllowEmptyString()] [AllowNull()] [string] $Phone)
    if (-not $Phone) { return $false }
    return [bool]($Phone -match '^\+?[0-9][0-9 .\-]{5,19}$')
}

function Test-CogesEmail {
    param([AllowEmptyString()] [AllowNull()] [string] $Email)
    if (-not $Email) { return $false }
    return [bool]($Email -match '^[^@\s"]+@[^@\s"]+\.[^@\s"]+$')
}

function Test-CogesPlan {
    param([AllowEmptyString()] [AllowNull()] [string] $Plan)
    if (-not $Plan) { return $false }
    return (@($script:CogesPlans.Keys) -ccontains $Plan)
}

# ---------------------------------------------------------------------------- secrets et réglages

function New-CogesRandomByte {
    <# Octets tirés de RandomNumberGenerator, le générateur cryptographique de .NET. #>
    param([int] $Count = 32)
    $bytes = New-Object byte[] $Count
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $generator.GetBytes($bytes) } finally { $generator.Dispose() }
    return , $bytes
}

function New-CogesHexSecret {
    <# 32 octets en hexadécimal : 64 caractères 0-9a-f. #>
    $bytes = New-CogesRandomByte 32
    return -join ($bytes | ForEach-Object { $_.ToString('x2') })
}

function New-CogesMfaKey {
    <# 32 octets en base64 url-safe sans « = » : 43 caractères. #>
    $bytes = New-CogesRandomByte 32
    return [Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function New-CogesSecretSet {
    <# Les huit mots de passe (tous différents) et la clé de chiffrement. #>
    $values = [ordered]@{}
    $seen = @{}
    foreach ($key in $script:CogesSecretKeys) {
        do { $secret = New-CogesHexSecret } while ($seen.ContainsKey($secret))
        $seen[$secret] = $true
        $values[$key] = $secret
    }
    $values[$script:CogesMfaKey] = New-CogesMfaKey
    return $values
}

function Get-CogesPublicUrl {
    <# L'adresse qui va avec le port : http://localhost, ou http://localhost:PORT. #>
    param([Parameter(Mandatory)] [int] $Port)
    if ($Port -eq 80) { return 'http://localhost' }
    return 'http://localhost:' + $Port
}

function ConvertTo-CogesEnvText {
    <# Le modèle coges.env.example rempli : les lignes NOM= des clés données prennent leur
       valeur, le reste (commentaires compris) est gardé. Fins de ligne LF. #>
    param(
        [Parameter(Mandatory)] [string] $Model,
        [Parameter(Mandatory)] [System.Collections.IDictionary] $Values
    )
    $missing = New-Object System.Collections.Generic.List[string]
    foreach ($key in $Values.Keys) { $missing.Add([string]$key) }
    $lines = foreach ($raw in ($Model -split "`n")) {
        $line = $raw.TrimEnd("`r")
        if ($line -match '^([A-Z0-9_]+)=(.*)$' -and $Values.Contains($Matches[1])) {
            [void]$missing.Remove($Matches[1])
            $Matches[1] + '=' + $Values[$Matches[1]]
        }
        else { $line }
    }
    if ($missing.Count -gt 0) {
        throw ('Le modèle de réglages n''a pas de ligne pour : ' + ($missing -join ', '))
    }
    $text = ($lines -join "`n").TrimEnd("`n") + "`n"
    return $text
}

function Write-CogesEnvFile {
    <# Crée coges.env en UTF-8 SANS BOM, LF. Refuse s'il existe : jamais d'écrasement. #>
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [string] $Text
    )
    $bytes = (New-Object Text.UTF8Encoding $false).GetBytes($Text.Replace("`r`n", "`n"))
    # CreateNew : échoue si le fichier existe, même s'il apparaît entre-temps.
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
}

function Read-CogesEnvFile {
    <# Couples NOM=valeur, comme check_onprem_env.py (BOM et CRLF du Bloc-notes acceptés). #>
    param([Parameter(Mandatory)] [string] $Path)
    $values = @{}
    foreach ($raw in [IO.File]::ReadAllLines($Path)) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
        $index = $line.IndexOf('=')
        $key = $line.Substring(0, $index).Trim()
        $value = $line.Substring($index + 1).Trim()
        if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and ($value[0] -eq '"' -or $value[0] -eq "'")) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        $values[$key] = $value
    }
    return $values
}

function Set-CogesEnvValue {
    <# Change des lignes d'un coges.env existant, sans toucher aux autres : seulement le port,
       l'adresse et la version (liste blanche). Garde les fins de ligne du fichier. #>
    param(
        [Parameter(Mandatory)] [string] $Path,
        [Parameter(Mandatory)] [System.Collections.IDictionary] $Values
    )
    foreach ($key in $Values.Keys) {
        if ($script:CogesEditableKeys -notcontains $key) {
            throw ('Le script ne change jamais ' + $key + ' dans coges.env.')
        }
    }
    # Écriture d'un coup (lot 5) : un coges.env jamais à moitié écrit, droits gardés.
    Write-CogesEnvAtomic -Path $Path -Text (ConvertTo-CogesEditedEnvText -Text ([IO.File]::ReadAllText($Path)) -Values $Values)
}

function Get-CogesMaskValue {
    <# Les valeurs à masquer : les secrets d'un coges.env. #>
    param([Parameter(Mandatory)] [System.Collections.IDictionary] $Values)
    $keys = @($script:CogesSecretKeys) + $script:CogesMfaKey
    return @($keys | Where-Object { $Values.Contains($_) -and $Values[$_] } | ForEach-Object { [string]$Values[$_] })
}

# ---------------------------------------------------------------------------- port

function Select-CogesPort {
    <# 80 s'il est libre ; sinon 8080 ou le premier libre au-dessus. -Port l'emporte. #>
    param(
        [int] $Requested = 0,
        [int[]] $Listening = @()
    )
    if ($Requested -gt 0) { return $Requested }
    if ($Listening -notcontains 80) { return 80 }
    $port = 8080
    while ($Listening -contains $port) { $port++ }
    return $port
}

function Get-CogesListeningPort {
    <# Les ports en écoute sur ce PC (Windows seulement). #>
    $connections = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
    return @($connections | ForEach-Object { [int]$_.LocalPort } | Sort-Object -Unique)
}

function Get-CogesPortOwner {
    <# Le nom du programme qui écoute sur un port, en mots. #>
    param([Parameter(Mandatory)] [int] $Port)
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $connection) { return 'un programme inconnu' }
    if ($connection.OwningProcess -eq 4) { return 'Windows lui-même (IIS ou un service web du système, processus 4)' }
    $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    if (-not $process) { return 'le processus ' + $connection.OwningProcess }
    return '{0} (processus {1})' -f $process.ProcessName, $connection.OwningProcess
}

# ---------------------------------------------------------------------------- PATH, raccourci

function Add-CogesPathEntry {
    <# Ajoute un dossier à une valeur de PATH, une seule fois (casse et « \ » final ignorés). #>
    param(
        [AllowEmptyString()] [AllowNull()] [string] $PathValue,
        [Parameter(Mandatory)] [string] $Directory
    )
    $wanted = $Directory.TrimEnd('\')
    $entries = @(([string]$PathValue).Split(';') | Where-Object { $_ })
    foreach ($entry in $entries) {
        if ($entry.TrimEnd('\') -ieq $wanted) { return ($entries -join ';') }
    }
    return (@($entries) + $wanted) -join ';'
}

function Remove-CogesPathEntry {
    param(
        [AllowEmptyString()] [AllowNull()] [string] $PathValue,
        [Parameter(Mandatory)] [string] $Directory
    )
    $wanted = $Directory.TrimEnd('\')
    return (@(([string]$PathValue).Split(';') | Where-Object { $_ -and $_.TrimEnd('\') -ine $wanted }) -join ';')
}

function New-CogesCmdText {
    <# bin\coges.cmd : la fonction « coges » du guide, pour toute nouvelle fenêtre. ASCII,
       CRLF (fichier de cmd.exe, écrit sur le PC du client, jamais versionné). #>
    param(
        [Parameter(Mandatory)] [string] $EnvFile,
        [Parameter(Mandatory)] [string] $Compose
    )
    $lines = @(
        '@echo off',
        'rem CoGes sur site (ADR 0126) : coges ps, coges logs api, coges up -d ...',
        ('docker compose --env-file "{0}" -f "{1}" %*' -f $EnvFile, $Compose)
    )
    return ($lines -join "`r`n") + "`r`n"
}

function New-CogesShortcutText {
    <# Raccourci Internet (.url) vers l'adresse de CoGes. #>
    param([Parameter(Mandatory)] [string] $Url)
    return "[InternetShortcut]`r`nURL=" + $Url + "/`r`n"
}

# ---------------------------------------------------------------------------- lectures

function Get-CogesDockerAutoStart {
    <# « Start Docker Desktop when you sign in » d'après le texte des réglages de Docker
       Desktop (clé AutoStart). $null si la clé n'y est pas : on n'invente rien. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Json)
    if (-not $Json) { return $null }
    try { $settings = $Json | ConvertFrom-Json } catch { return $null }
    if ($null -eq $settings) { return $null }
    $property = $settings.PSObject.Properties | Where-Object { $_.Name -ieq 'AutoStart' } | Select-Object -First 1
    if (-not $property -or $property.Value -isnot [bool]) { return $null }
    return [bool]$property.Value
}

function ConvertFrom-CogesComposeStatus {
    <# `docker compose ps --format json` : un tableau JSON (anciennes versions) ou une ligne
       JSON par conteneur (récentes). Rend Service, State, Health. #>
    param([AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    $text = (@($Lines) -join "`n").Trim()
    if (-not $text) { return @() }
    $items = New-Object System.Collections.Generic.List[object]
    if ($text.StartsWith('[')) {
        foreach ($item in ($text | ConvertFrom-Json)) { $items.Add($item) }
    }
    else {
        foreach ($line in ($text -split "`n")) {
            if ($line.Trim().StartsWith('{')) { $items.Add(($line | ConvertFrom-Json)) }
        }
    }
    return @($items | ForEach-Object {
            $health = ''
            if ($_.PSObject.Properties['Health']) { $health = [string]$_.Health }
            [pscustomobject]@{ Service = [string]$_.Service; State = [string]$_.State; Health = $health }
        })
}

function Get-CogesWaitingService {
    <# Les services pas encore prêts : absents, arrêtés, ou dont la sonde n'est pas « healthy ». #>
    param([AllowEmptyCollection()] [object[]] $Containers = @())
    $waiting = foreach ($service in $script:CogesServices) {
        $container = @($Containers | Where-Object { $_.Service -eq $service }) | Select-Object -First 1
        if (-not $container -or $container.State -ne 'running' -or ($container.Health -and $container.Health -ne 'healthy')) {
            $service
        }
    }
    return @($waiting)
}

function Test-CogesLicenseActive {
    <# La sortie de license-status dit-elle « Accès : actif » et « Fin de période : sans fin » ? #>
    param([AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    $text = @($Lines) -join "`n"
    $access = $text -match '(?m)^Acc\S*s\s*:\s*actif\s*$'
    $end = $text -match '(?m)^Fin de p\S*riode\s*:\s*sans fin\s*$'
    return ($access -and $end)
}

function Test-CogesCompanyMissing {
    <# license-status d'une société inconnue : code 3, « Entreprise introuvable » (ADR 0125). #>
    param([int] $ExitCode, [AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    return ($ExitCode -eq 3 -or ((@($Lines) -join "`n") -match 'Entreprise introuvable'))
}

function Get-CogesDockerProblem {
    <# Lit l'erreur de « docker version » : acces (hors du groupe docker-users), eteint
       (moteur arrêté), windows (moteur Windows au lieu de Linux) ou autre. #>
    param([AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    $text = @($Lines) -join "`n"
    if ($text -match '(?i)access is denied|permission denied|acc\S*s refus') { return 'acces' }
    if ($text -match '(?i)cannot find the file specified|is the docker daemon running|error during connect|cannot connect to the docker|fichier sp\S*cifi\S* est introuvable|pipe.*docker_engine') { return 'eteint' }
    return 'autre'
}

#: Le message quand le moteur de Docker Desktop est arrêté (lot 5, bloc 0 : « échec (code 1) » avant).
$script:CogesDockerStoppedText = 'Docker Desktop ne tourne pas : ouvrez-le et attendez « Engine running », puis relancez. Rien n''a changé.'

function Get-CogesDockerEngineProblem {
    <# $null si le moteur Linux de Docker répond ; sinon absent, acces, eteint ou windows. #>
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return 'absent' }
    $result = Invoke-Docker -Arguments @('version', '--format', '{{.Server.Os}}')
    if ($result.ExitCode -ne 0) {
        $problem = Get-CogesDockerProblem $result.Output
        if ($problem -eq 'acces') { return 'acces' }
        return 'eteint'
    }
    if ((@($result.Stdout) | Select-Object -Last 1) -ne 'linux') { return 'windows' }
    return $null
}

function Assert-CogesDockerRunning {
    <# En tête de toute action qui appelle Docker : un message clair, avant de rien changer. #>
    $problem = Get-CogesDockerEngineProblem
    if ($null -eq $problem) { return }
    switch ($problem) {
        'absent' {
            Stop-CogesStep -Probleme 'Docker Desktop n''est pas installé sur ce PC. Rien n''a changé.' `
                -QuoiFaire ('Installez-le depuis ' + $script:CogesDockerDownload + ', puis relancez.')
        }
        'acces' {
            Stop-CogesStep -Probleme 'Docker refuse l''accès à ce compte Windows. Rien n''a changé.' `
                -QuoiFaire 'Ajoutez ce compte au groupe « docker-users », fermez la session Windows, rouvrez-la, puis relancez.'
        }
        'windows' {
            Stop-CogesStep -Probleme 'Docker Desktop tourne avec des conteneurs Windows. Rien n''a changé.' `
                -QuoiFaire 'Clic droit sur l''icône de Docker (près de l''horloge) > « Switch to Linux containers… », puis relancez.'
        }
        default {
            Stop-CogesStep -Probleme $script:CogesDockerStoppedText `
                -QuoiFaire 'Si « Engine running » ne vient pas, suivez « Docker Desktop ne démarre plus » dans le guide (jamais « Clean / Purge data » ni « Reset to factory defaults »).'
        }
    }
}

function Test-CogesPortInUseError {
    param([AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    return ((@($Lines) -join "`n") -match '(?i)port is already allocated|ports are not available|address already in use|only one usage of each socket address')
}

function Test-CogesHasNoCarriageReturn {
    param([Parameter(Mandatory)] [string] $Path)
    $bytes = [IO.File]::ReadAllBytes($Path)
    return ([Array]::IndexOf($bytes, [byte]13) -lt 0)
}

# ---------------------------------------------------------------------------- docker

function ConvertTo-CogesCommandLine {
    <# Une ligne de commande Windows où chaque argument reste entier (règles de
       CommandLineToArgvW : guillemets, et barres obliques inverses devant eux doublées). #>
    param([AllowEmptyCollection()] [string[]] $Arguments = @())
    $parts = foreach ($argument in $Arguments) {
        if ($argument -eq '') { '""'; continue }
        # L'apostrophe aussi : .NET la prend pour un guillemet hors de Windows.
        if ($argument -notmatch '[\s"'']') { $argument; continue }
        $builder = New-Object Text.StringBuilder
        [void]$builder.Append('"')
        $slashes = 0
        foreach ($character in $argument.ToCharArray()) {
            if ($character -eq '\') { $slashes++; continue }
            if ($character -eq '"') {
                [void]$builder.Append('\' * (2 * $slashes + 1)).Append('"')
            }
            else {
                [void]$builder.Append('\' * $slashes).Append($character)
            }
            $slashes = 0
        }
        [void]$builder.Append('\' * (2 * $slashes)).Append('"')
        $builder.ToString()
    }
    return (@($parts) -join ' ')
}

function Invoke-Docker {
    <# Le SEUL appel à docker. -Interactive : la console du technicien est passée telle
       quelle (progression du pull, mot de passe sans écho) ; sinon la sortie est lue. #>
    param(
        [Parameter(Mandatory)] [string[]] $Arguments,
        [switch] $Interactive,
        # Texte donné à l'entrée standard (clé privée de la restauration) : jamais un argument
        # ni une variable d'environnement, donc absent de « docker inspect » et du journal.
        [AllowNull()] [string] $InputText = $null
    )
    if ($script:CogesState.Simulation) {
        throw 'Invoke-Docker appelé en simulation : rien ne doit être lancé.'
    }
    Write-Log -Message ('docker ' + ($Arguments -join ' ')) -Level DOCKER
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $output = @()
    $stdout = @()
    $code = $null
    # Sous 5.1, une ligne sur la sortie d'erreur d'un programme devient une erreur
    # PowerShell : « Stop » arrêterait au premier message de progression de docker.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Interactive) {
            # Start-Process : docker reçoit la console elle-même. Avec « & docker », PowerShell
            # lirait sa sortie ligne par ligne et l'invite du mot de passe resterait cachée.
            $process = Start-Process -FilePath 'docker' -ArgumentList (ConvertTo-CogesCommandLine $Arguments) -NoNewWindow -PassThru
            $null = $process.Handle
            $process.WaitForExit()
            $code = $process.ExitCode
        }
        else {
            # Sortie standard (réponse de la commande) et sortie d'erreur (progression de
            # compose, alembic…) gardées ensemble dans Output, la première seule dans Stdout.
            if ($null -ne $InputText) { $lines = @($InputText | & docker @Arguments 2>&1) }
            else { $lines = @(& docker @Arguments 2>&1) }
            $code = $LASTEXITCODE
            foreach ($item in $lines) {
                if ($item -is [Management.Automation.ErrorRecord]) {
                    # Le texte de la ligne (une ligne vide donnerait sinon le nom de l'exception).
                    $output += [string]$item.Exception.Message
                }
                else {
                    $output += [string]$item
                    $stdout += [string]$item
                }
            }
        }
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($null -eq $code) { $code = 1 }
    Write-Log -Message ('code de sortie {0} ({1:N1} s)' -f $code, $watch.Elapsed.TotalSeconds) -Level DOCKER
    if ($code -ne 0) {
        foreach ($line in ($output | Select-Object -Last 20)) { Write-Log -Message $line -Level DOCKER }
    }
    return [pscustomobject]@{ ExitCode = [int]$code; Output = [string[]]$output; Stdout = [string[]]$stdout }
}

function Get-CogesPath {
    <# Les trois endroits (guide) et ce qui s'y range. #>
    param([Parameter(Mandatory)] [string] $Racine)
    $programme = Join-Path $Racine 'programme'
    $reglages = Join-Path $Racine 'reglages'
    return [pscustomobject]@{
        Racine    = $Racine
        Programme = $programme
        Reglages  = $reglages
        EnvFile   = Join-Path $reglages 'coges.env'
        Compose   = Join-Path $programme 'docker-compose.yml'
        Version   = Join-Path $programme '.version'
        Bin       = Join-Path $Racine 'bin'
        Journaux  = Join-Path $Racine 'journaux'
    }
}

function Get-CogesComposeArgument {
    <# docker compose --env-file <réglages>\coges.env -f <programme>\docker-compose.yml … #>
    param(
        [Parameter(Mandatory)] $Paths,
        [string[]] $Arguments = @()
    )
    return @('compose', '--env-file', $Paths.EnvFile, '-f', $Paths.Compose) + $Arguments
}

function Invoke-CogesCompose {
    <# La fonction « coges » du guide. #>
    param(
        [Parameter(Mandatory)] $Paths,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [switch] $Interactive
    )
    return Invoke-Docker -Arguments (Get-CogesComposeArgument -Paths $Paths -Arguments $Arguments) -Interactive:$Interactive
}

# ---------------------------------------------------------------------------- questions

function Read-CogesAnswer {
    <# Une réponse : donnée par paramètre, sinon demandée (Read-Host) jusqu'à ce qu'elle
       soit valide. En -NonInteractif, une réponse manquante est un échec clair. #>
    param(
        [Parameter(Mandatory)] [string] $Question,
        [Parameter(Mandatory)] [string] $Parameter,
        [Parameter(Mandatory)] [scriptblock] $Validate,
        [Parameter(Mandatory)] [string] $Rule,
        [AllowEmptyString()] [AllowNull()] [string] $Value,
        [AllowEmptyString()] [string] $Default = '',
        [switch] $Optional
    )
    if ($Value) {
        if (-not (& $Validate $Value)) {
            Stop-CogesStep -Probleme ('La valeur de -{0} ne convient pas : {1}' -f $Parameter, $Rule) `
                -QuoiFaire ('Corrigez -{0} et relancez.' -f $Parameter)
        }
        return $Value.Trim()
    }
    if ($script:CogesState.NonInteractif) {
        if ($Optional) { return '' }
        Stop-CogesStep -Probleme ('Réponse manquante : {0}' -f $Question) `
            -QuoiFaire ('En mode -NonInteractif, passez -{0} (ou relancez sans -NonInteractif).' -f $Parameter)
    }
    while ($true) {
        $label = $Question
        if ($Default) { $label = '{0} [{1}]' -f $Question, $Default }
        $answer = Read-Host $label
        if (-not $answer) { $answer = $Default }
        if (-not $answer -and $Optional) { return '' }
        if ($answer -and (& $Validate $answer)) { return $answer.Trim() }
        Write-CogesLine ('  ' + $Rule) -Kind Attention
    }
}

function Confirm-CogesWord {
    <# Fait taper un mot exact (OUI, COPIE-FAITE…) ; tout autre réponse arrête. #>
    param(
        [Parameter(Mandatory)] [string] $Word,
        [Parameter(Mandatory)] [string] $Prompt,
        [bool] $Given = $false,
        [string] $Parameter = ''
    )
    if ($Given) { return }
    if ($script:CogesState.NonInteractif) {
        $what = 'relancez sans -NonInteractif.'
        if ($Parameter) { $what = 'passez -{0} explicitement, ou relancez sans -NonInteractif.' -f $Parameter }
        Stop-CogesStep -Probleme ('Confirmation « {0} » impossible en mode -NonInteractif.' -f $Word) -QuoiFaire $what
    }
    $answer = Read-Host ('{0} Tapez {1}' -f $Prompt, $Word)
    if ($answer -cne $Word) {
        Stop-CogesStep -Probleme ('Vous n''avez pas tapé {0} : rien de plus n''est fait.' -f $Word) `
            -QuoiFaire 'Relancez la même commande quand vous serez prêt : ce qui est déjà fait est gardé.'
    }
}

function Read-CogesInstallAnswer {
    <# Les questions de l'installation, une seule fois, puis le récapitulatif. #>
    param([Parameter(Mandatory)] [hashtable] $Given)
    $name = Read-CogesAnswer -Question 'Nom de la boutique' -Parameter 'NomBoutique' -Value $Given.NomBoutique `
        -Validate { param($v) Test-CogesText $v } -Rule '2 à 120 caractères, sans guillemet double.'
    $slug = Read-CogesAnswer -Question 'Code de la boutique (tapé à la connexion)' -Parameter 'CodeBoutique' `
        -Value $Given.CodeBoutique -Default (ConvertTo-CogesSlug $name) `
        -Validate { param($v) Test-CogesSlug $v } -Rule 'minuscules, chiffres et tirets entre deux mots (exemple : boutique-diallo).'
    $manager = Read-CogesAnswer -Question 'Nom du gérant' -Parameter 'NomGerant' -Value $Given.NomGerant `
        -Validate { param($v) Test-CogesText $v } -Rule '2 à 120 caractères, sans guillemet double.'
    $phone = ''
    $email = ''
    if ($Given.EmailGerant -and -not $Given.TelephoneGerant) {
        $email = Read-CogesAnswer -Question 'E-mail du gérant' -Parameter 'EmailGerant' -Value $Given.EmailGerant `
            -Validate { param($v) Test-CogesEmail $v } -Rule 'une adresse du type nom@domaine.sn.'
    }
    else {
        $phone = Read-CogesAnswer -Question 'Téléphone du gérant (laissez vide pour donner un e-mail)' -Parameter 'TelephoneGerant' `
            -Value $Given.TelephoneGerant -Optional -Validate { param($v) Test-CogesPhone $v } -Rule 'chiffres et espaces, par exemple 77 123 45 67.'
        if (-not $phone) {
            $email = Read-CogesAnswer -Question 'E-mail du gérant' -Parameter 'EmailGerant' -Value $Given.EmailGerant `
                -Validate { param($v) Test-CogesEmail $v } -Rule 'une adresse du type nom@domaine.sn.'
        }
    }
    $plan = Read-CogesAnswer -Question 'Offre achetée : starter (3 comptes), business (7) ou premium (10)' -Parameter 'Offre' `
        -Value $Given.Offre -Validate { param($v) Test-CogesPlan $v } -Rule 'starter, business ou premium, en minuscules.'
    $note = Read-CogesAnswer -Question 'Note du contrat (date du contrat et fin de maintenance)' -Parameter 'NoteContrat' `
        -Value $Given.NoteContrat -Validate { param($v) Test-CogesText $v -Max 500 } `
        -Rule 'obligatoire, 500 caractères au plus, sans guillemet double (exemple : Contrat du 17/11/2026, maintenance jusqu''au 17/11/2027).'
    $answers = [pscustomobject]@{
        NomBoutique = $name; CodeBoutique = $slug; NomGerant = $manager
        TelephoneGerant = $phone; EmailGerant = $email; Offre = $plan; NoteContrat = $note
    }
    $contact = $phone
    if (-not $contact) { $contact = $email }
    Write-CogesLine ''
    Write-CogesLine 'Récapitulatif' -Kind Titre
    Write-CogesLine ('  Boutique : {0} (code : {1})' -f $name, $slug)
    Write-CogesLine ('  Gérant   : {0}, {1}' -f $manager, $contact)
    Write-CogesLine ('  Offre    : {0} ({1} comptes au plus)' -f $plan, $script:CogesPlans[$plan])
    Write-CogesLine ('  Contrat  : {0}' -f $note)
    Write-CogesLine '  Le mot de passe du gérant sera demandé plus tard, sans s''afficher.'
    Confirm-CogesWord -Word 'OUI' -Prompt 'Tout est juste ?' -Given $script:CogesState.NonInteractif
    return $answers
}

# ---------------------------------------------------------------------------- bloc B : le PC

function Test-CogesWindows {
    return ([Environment]::OSVersion.Platform -eq [PlatformID]::Win32NT)
}

function Test-CogesMemory {
    <# 8 Go installés au moins (une barrette de 8 Go se lit 8 Gio). #>
    param([long] $Bytes)
    return ($Bytes -ge 8GB)
}

function Get-CogesDockerSettingsText {
    $folder = Join-Path $env:APPDATA 'Docker'
    foreach ($name in @('settings-store.json', 'settings.json')) {
        $path = Join-Path $folder $name
        if (Test-Path -LiteralPath $path) { return [IO.File]::ReadAllText($path) }
    }
    return $null
}

function Get-CogesHttpStatus {
    <# Le code HTTP d'une adresse ; 0 si rien ne répond. Un 401 ou un 404 est une réponse. #>
    param([Parameter(Mandatory)] [string] $Url)
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 15 -MaximumRedirection 0 -ErrorAction Stop
        return [int]$response.StatusCode
    }
    catch {
        $exception = $_.Exception
        if ($exception.PSObject.Properties['Response'] -and $exception.Response) {
            return [int]$exception.Response.StatusCode
        }
        return 0
    }
}

function Test-CogesPrerequisite {
    <# Bloc B : chaque contrôle s'arrête au premier échec, avec quoi faire. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans les blocs des étapes (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param(
        [Parameter(Mandatory)] [string] $Version,
        [Parameter(Mandatory)] [string] $Racine,
        [switch] $AlreadyInstalled
    )
    Invoke-CogesStep -Title 'Contrôle du PC : Windows 11 64 bits, mémoire, disque, virtualisation' -Action {
        if (-not (Test-CogesWindows)) {
            Stop-CogesStep -Probleme 'Ce script s''utilise sur Windows 11.' -QuoiFaire 'Lancez-le sur le PC du client, sous Windows 11.'
        }
        $build = [Environment]::OSVersion.Version.Build
        if ($build -lt 22000 -or -not [Environment]::Is64BitOperatingSystem) {
            Stop-CogesStep -Probleme ('Ce PC n''est pas sous Windows 11 64 bits (version {0}).' -f [Environment]::OSVersion.Version) `
                -QuoiFaire 'CoGes sur site demande Windows 11, 64 bits. Mettez Windows à jour ou choisissez un autre PC.'
        }
        $installed = (Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Capacity -Sum).Sum
        if (-not $installed) { $installed = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory }
        if (-not (Test-CogesMemory ([long]$installed))) {
            Stop-CogesStep -Probleme ('Ce PC a {0:N1} Go de mémoire ; il en faut 8 au moins.' -f ($installed / 1GB)) `
                -QuoiFaire 'Ajoutez de la mémoire ou choisissez un PC de 8 Go au moins.'
        }
        $needed = 20GB
        if ($AlreadyInstalled) { $needed = 5GB }
        $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($Racine))
        if ($drive.AvailableFreeSpace -lt $needed) {
            Stop-CogesStep -Probleme ('Il reste {0:N1} Go libres sur {1} ; il en faut {2} au moins.' -f ($drive.AvailableFreeSpace / 1GB), $drive.Name, ($needed / 1GB)) `
                -QuoiFaire 'Libérez de la place (Paramètres > Système > Stockage), puis relancez.'
        }
        # Quand l'hyperviseur tourne déjà (WSL 2), Windows dit « firmware : non » : on
        # accepte alors HypervisorPresent.
        $hypervisor = [bool](Get-CimInstance Win32_ComputerSystem).HypervisorPresent
        $firmware = [bool](@(Get-CimInstance Win32_Processor) | Where-Object { $_.VirtualizationFirmwareEnabled } | Select-Object -First 1)
        if (-not ($hypervisor -or $firmware)) {
            Stop-CogesStep -Probleme 'La virtualisation est désactivée sur ce PC.' `
                -QuoiFaire 'Activez Intel VT-x / AMD-V (parfois « SVM ») dans le BIOS du PC, puis relancez. Le Gestionnaire des tâches, onglet Performance, Processeur, doit dire « Virtualisation : Activé ».'
        }
        Write-CogesLine '  Windows, mémoire, disque et virtualisation : bons.' -Kind Ok
    }

    Invoke-CogesStep -Title 'Contrôle de Docker Desktop (moteur Linux, docker compose)' -Action {
        if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
            Stop-CogesStep -Probleme 'Docker Desktop n''est pas installé.' `
                -QuoiFaire ('Installez-le depuis ' + $script:CogesDockerDownload + ' (moteur WSL 2, proposé par défaut). Vérifiez avant ses conditions de licence pour ce client. Puis relancez ce script. Ce script ne l''installe pas.')
        }
        $result = Invoke-Docker -Arguments @('version', '--format', '{{.Server.Os}}')
        if ($result.ExitCode -ne 0) {
            $problem = Get-CogesDockerProblem $result.Output
            if ($problem -eq 'acces') {
                Stop-CogesStep -Probleme 'Docker refuse l''accès à ce compte Windows.' `
                    -QuoiFaire 'Ajoutez ce compte au groupe « docker-users » (Gestion de l''ordinateur > Utilisateurs et groupes locaux > Groupes), fermez la session Windows, rouvrez-la, puis relancez.'
            }
            $desktop = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
            if (Test-Path -LiteralPath $desktop) {
                Stop-CogesStep -Probleme 'Docker Desktop est installé mais son moteur ne tourne pas.' `
                    -QuoiFaire 'Ouvrez Docker Desktop (menu Démarrer), attendez « Engine running » en bas à gauche, puis relancez.'
            }
            Stop-CogesStep -Probleme 'Docker ne répond pas.' -QuoiFaire 'Redémarrez Docker Desktop (ou le PC), puis relancez.'
        }
        $os = (@($result.Stdout) | Select-Object -Last 1)
        if ($os -ne 'linux') {
            Stop-CogesStep -Probleme 'Docker Desktop tourne avec des conteneurs Windows.' `
                -QuoiFaire 'Clic droit sur l''icône de Docker (près de l''horloge) > « Switch to Linux containers… », puis relancez.'
        }
        $compose = Invoke-Docker -Arguments @('compose', 'version')
        if ($compose.ExitCode -ne 0) {
            Stop-CogesStep -Probleme '« docker compose » ne répond pas.' -QuoiFaire 'Mettez Docker Desktop à jour (Paramètres > Software updates), puis relancez.'
        }
        $autoStart = Get-CogesDockerAutoStart (Get-CogesDockerSettingsText)
        if ($autoStart -ne $true) {
            Write-CogesLine '  ATTENTION : dans Docker Desktop, Paramètres > General, cochez « Start Docker Desktop when you sign in to your computer ». C''est ce qui relance CoGes avec le PC.' -Kind Attention
        }
        Write-CogesLine '  Docker Desktop : bon.' -Kind Ok
    }

    Invoke-CogesStep -Title 'Contrôle d''Internet (github.com et ghcr.io)' -Action {
        foreach ($url in @('https://github.com', 'https://ghcr.io/v2/')) {
            if ((Get-CogesHttpStatus $url) -eq 0) {
                Stop-CogesStep -Probleme ('{0} ne répond pas depuis ce PC.' -f $url) `
                    -QuoiFaire 'Vérifiez la connexion Internet. Si un proxy ou un pare-feu filtre les sites, faites autoriser github.com, ghcr.io et pkg-containers.githubusercontent.com pour aujourd''hui, puis relancez.'
            }
        }
        Write-CogesLine '  Internet : bon.' -Kind Ok
    }

    Invoke-CogesStep -Title ('Contrôle de la version {0} (images front, api et worker)' -f $Version) -Action {
        foreach ($image in @('front', 'api', 'worker')) {
            $result = Invoke-Docker -Arguments @('manifest', 'inspect', ('{0}/{1}:{2}' -f $script:CogesRegistry, $image, $Version))
            if ($result.ExitCode -ne 0) {
                Stop-CogesStep -Probleme ('La version {0} n''existe pas pour l''image {1}.' -f $Version, $image) `
                    -QuoiFaire 'Vérifiez la version donnée par CoGes (format vX.Y.Z) et relancez avec la bonne.'
            }
        }
        Write-CogesLine '  Version : publiée.' -Kind Ok
    }

    Invoke-CogesStep -Title 'Contrôle de la licence sur site dans cette version' -Action {
        $image = '{0}/api:{1}' -f $script:CogesRegistry, $Version
        $pull = Invoke-Docker -Arguments @('pull', $image) -Interactive
        if ($pull.ExitCode -ne 0) {
            Stop-CogesStep -Probleme ('Le téléchargement de {0} a échoué.' -f $image) -QuoiFaire 'Vérifiez Internet, puis relancez : ce qui est téléchargé est gardé.'
        }
        $help = Invoke-Docker -Arguments @('run', '--rm', '--network', 'none', '--entrypoint', 'python', $image, '-m', 'app.cli', '--help')
        $text = @($help.Stdout) -join "`n"
        if ($help.ExitCode -ne 0 -or $text -notmatch 'activate-license' -or $text -notmatch 'license-status') {
            Stop-CogesStep -Probleme ('La version {0} est antérieure à la licence sur site.' -f $Version) `
                -QuoiFaire 'Prenez une version plus récente (demandez-la à CoGes) et relancez avec -Version.'
        }
        Write-CogesLine '  activate-license et license-status : présents.' -Kind Ok
    }
}

# ---------------------------------------------------------------------------- bloc C : programme et réglages

function Save-CogesArchive {
    <# L'archive du dépôt à l'étiquette (dépôt public, aucun jeton). #>
    param(
        [Parameter(Mandatory)] [string] $Version,
        [Parameter(Mandatory)] [string] $Destination
    )
    $url = 'https://github.com/{0}/archive/refs/tags/{1}.zip' -f $script:CogesRepository, $Version
    $previous = $ProgressPreference
    # La barre de progression de 5.1 rend le téléchargement des dizaines de fois plus lent.
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $url -OutFile $Destination -UseBasicParsing -TimeoutSec 600 -ErrorAction Stop
    }
    catch {
        Stop-CogesStep -Probleme ('Le programme de la version {0} ne se télécharge pas ({1}).' -f $Version, $url) `
            -QuoiFaire 'Vérifiez la version et la connexion Internet, puis relancez.'
    }
    finally { $ProgressPreference = $previous }
}

function Expand-CogesProgramme {
    <# deploy/onprem/ de l'archive dans un dossier neuf : fichiers attendus présents, fichiers
       lus par Linux en LF. Rend le nombre de fichiers. Utilisé par Install-Programme et par le
       téléchargement d'une mise à jour (lot 5), qui vérifie le nouveau programme avant de le poser. #>
    param([Parameter(Mandatory)] [string] $Archive, [Parameter(Mandatory)] [string] $Destination)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $staging = $Destination
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    try {
        $count = 0
        foreach ($entry in $zip.Entries) {
            # « CoGes-1.4.0/deploy/onprem/… » : seul ce dossier est posé.
            if ($entry.FullName -notmatch '^[^/]+/deploy/onprem/(.+)$') { continue }
            $relative = $Matches[1]
            if ($relative.EndsWith('/') -or $relative -match '(^|/)__pycache__(/|$)') { continue }
            if ($relative.Split('/') -contains '..') { throw ('Chemin refusé dans l''archive : ' + $entry.FullName) }
            $target = Join-Path $staging ($relative.Replace('/', [IO.Path]::DirectorySeparatorChar))
            New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entry, $target, $true)
            $count++
        }
    }
    finally { $zip.Dispose() }
    foreach ($file in $script:CogesProgrammeFiles) {
        $path = Join-Path $staging ($file.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-Path -LiteralPath $path)) {
            throw ('Fichier absent du programme : ' + $file)
        }
    }
    foreach ($file in $script:CogesLfFiles) {
        $path = Join-Path $staging ($file.Replace('/', [IO.Path]::DirectorySeparatorChar))
        if (-not (Test-CogesHasNoCarriageReturn $path)) {
            throw ('Fins de ligne Windows (CRLF) dans ' + $file + ' : le conteneur qui le lit échouerait.')
        }
    }
    return $count
}

function Install-Programme {
    <# Pose deploy/onprem/ de l'archive dans <Racine>\programme, en REMPLAÇANT le dossier en
       entier. Ne touche jamais à reglages\ ni aux données. -GarderPrecedent (mise à jour, lot
       5) : l'ancien programme reste dans programme.precedent, pour le retour arrière. #>
    param(
        [Parameter(Mandatory)] [string] $Archive,
        [Parameter(Mandatory)] [string] $Racine,
        [Parameter(Mandatory)] [string] $Version,
        [switch] $GarderPrecedent
    )
    $paths = Get-CogesPath $Racine
    $staging = Join-Path $Racine ('programme.nouveau-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    $previous = $paths.Programme + '.ancien'
    if ($GarderPrecedent) { $previous = $paths.Programme + '.precedent' }
    try {
        $count = Expand-CogesProgramme -Archive $Archive -Destination $staging
        [IO.File]::WriteAllText((Join-Path $staging '.version'), $Version + "`n", (New-Object Text.UTF8Encoding $false))
        if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
        if (Test-Path -LiteralPath $paths.Programme) { Rename-Item -LiteralPath $paths.Programme -NewName (Split-Path -Leaf $previous) }
        Rename-Item -LiteralPath $staging -NewName 'programme'
        if (-not $GarderPrecedent -and (Test-Path -LiteralPath $previous)) { Remove-Item -LiteralPath $previous -Recurse -Force }
        return $count
    }
    catch {
        if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force }
        if ((Test-Path -LiteralPath $previous) -and -not (Test-Path -LiteralPath $paths.Programme)) {
            Rename-Item -LiteralPath $previous -NewName 'programme'
        }
        throw
    }
}

function Get-CogesInstalledVersion {
    <# La version du dossier du programme (.version, posé avec lui), ou $null. #>
    param([Parameter(Mandatory)] $Paths)
    if (-not (Test-Path -LiteralPath $Paths.Version)) { return $null }
    return ([IO.File]::ReadAllText($Paths.Version)).Trim()
}

function Test-CogesProgramme {
    <# Le programme est-il complet, en LF, et de cette version ? #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [string] $Version)
    if ((Get-CogesInstalledVersion $Paths) -ne $Version) { return $false }
    foreach ($file in $script:CogesProgrammeFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $Paths.Programme $file))) { return $false }
    }
    foreach ($file in $script:CogesLfFiles) {
        if (-not (Test-CogesHasNoCarriageReturn (Join-Path $Paths.Programme $file))) { return $false }
    }
    return $true
}

function Set-CogesPrivateAcl {
    <# coges.env lisible par ce compte, SYSTEM et Administrateurs seulement (SID : les noms
       des groupes changent avec la langue de Windows). #>
    param([Parameter(Mandatory)] [string] $Path)
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = @(& icacls.exe $Path '/inheritance:r' '/grant:r' ('*{0}:F' -f $user) '*S-1-5-18:F' '*S-1-5-32-544:F' 2>&1 | ForEach-Object { [string]$_ })
        $code = $LASTEXITCODE
    }
    finally { $ErrorActionPreference = $previous }
    if ($code -ne 0) {
        Write-Log -Message ('icacls : ' + (@($output) -join ' ')) -Level ECHEC
        Stop-CogesStep -Probleme 'Les droits de coges.env n''ont pas pu être restreints.' `
            -QuoiFaire 'Vérifiez que C:\CoGes est sur un disque local (NTFS), puis relancez -Action Reparer.'
    }
}

function New-CogesSetting {
    <# Crée coges.env depuis le modèle : version, 9 secrets, port et adresse. Rien n'est affiché. #>
    param(
        [Parameter(Mandatory)] $Paths,
        [Parameter(Mandatory)] [string] $Version,
        [Parameter(Mandatory)] [int] $Port
    )
    $model = [IO.File]::ReadAllText((Join-Path $Paths.Programme 'coges.env.example'))
    $values = New-CogesSecretSet
    $values['COGES_IMAGE_TAG'] = $Version
    $values['COGES_HTTP_PORT'] = [string]$Port
    $values['COGES_PUBLIC_URL'] = Get-CogesPublicUrl $Port
    $script:CogesState.MaskValues = Get-CogesMaskValue $values
    New-Item -ItemType Directory -Force -Path $Paths.Reglages | Out-Null
    Write-CogesEnvFile -Path $Paths.EnvFile -Text (ConvertTo-CogesEnvText -Model $model -Values $values)
    if (Test-CogesWindows) { Set-CogesPrivateAcl $Paths.EnvFile }
}

function Get-CogesSetting {
    <# Les réglages lus, et leurs secrets ajoutés au masque du journal. #>
    param([Parameter(Mandatory)] $Paths)
    $values = Read-CogesEnvFile $Paths.EnvFile
    # Les adresses de ping du support (lot 6) sont des secrets elles aussi.
    $script:CogesState.MaskValues = @(Get-CogesMaskValue $values) + @(Get-CogesSupportMaskValue $Paths)
    return $values
}

function Get-CogesRegistryOf {
    param([Parameter(Mandatory)] [hashtable] $Settings)
    if ($Settings.ContainsKey('COGES_IMAGE_REGISTRY') -and $Settings['COGES_IMAGE_REGISTRY']) {
        return $Settings['COGES_IMAGE_REGISTRY']
    }
    return $script:CogesRegistry
}

function Invoke-CogesSettingCheck {
    <# check_onprem_env.py comme l'étape 5 du guide : image worker, sans réseau, deux
       dossiers en lecture seule. Les refus sont affichés mot pour mot. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Settings)
    $image = '{0}/worker:{1}' -f (Get-CogesRegistryOf $Settings), $Settings['COGES_IMAGE_TAG']
    $result = Invoke-Docker -Arguments @(
        'run', '--rm', '--network', 'none',
        '-v', ($Paths.Programme + ':/onprem:ro'),
        '-v', ($Paths.Reglages + ':/reglages:ro'),
        '--entrypoint', 'python', $image,
        '/onprem/check_onprem_env.py', '--env-file', '/reglages/coges.env')
    foreach ($line in $result.Output) {
        if ($line -match '^(REFUS|OK)') {
            $kind = 'Attention'
            if ($line.StartsWith('OK')) { $kind = 'Ok' }
            Write-CogesLine ('  ' + $line) -Kind $kind
        }
    }
    if ($result.ExitCode -ne 0) {
        Stop-CogesStep -Probleme 'Le contrôle des réglages refuse coges.env (lignes REFUS ci-dessus).' `
            -QuoiFaire ('Corrigez chaque ligne dans ' + $Paths.EnvFile + ' (Bloc-notes), puis relancez -Action Reparer.')
    }
}

# ---------------------------------------------------------------------------- bloc D : démarrage

function Wait-CogesHealthy {
    <# Les neuf services « running » (et « healthy » s'ils ont une sonde), 5 minutes au plus. #>
    param([Parameter(Mandatory)] $Paths, [int] $TimeoutSeconds = 300, [int] $IntervalSeconds = 5)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $last = ''
    $waiting = @($script:CogesServices)
    while ((Get-Date) -lt $deadline) {
        $result = Invoke-CogesCompose -Paths $Paths -Arguments @('ps', '-a', '--format', 'json')
        $waiting = @(Get-CogesWaitingService (ConvertFrom-CogesComposeStatus $result.Stdout))
        if ($waiting.Count -eq 0) {
            Write-CogesLine '  Les neuf services sont prêts.' -Kind Ok
            return
        }
        $now = $waiting -join ', '
        if ($now -ne $last) { Write-CogesLine ('  En attente : ' + $now) }
        $last = $now
        Start-Sleep -Seconds $IntervalSeconds
    }
    $culprit = $waiting[0]
    Write-CogesLine ('  {0} n''est pas prêt au bout de {1} minutes. Ses 40 dernières lignes :' -f $culprit, [int]($TimeoutSeconds / 60)) -Kind Echec
    $logs = Invoke-CogesCompose -Paths $Paths -Arguments @('logs', '--no-color', '--tail', '40', $culprit)
    foreach ($line in $logs.Output) { Write-CogesLine ('    ' + $line) }
    Stop-CogesStep -Probleme ('Le service {0} ne démarre pas.' -f $culprit) `
        -QuoiFaire 'Lisez les lignes ci-dessus (guide, « Une ligne de coges ps n''est pas healthy »), puis relancez -Action Reparer. Rien n''est perdu.'
}

function Start-CogesStack {
    <# pull → contrôle → migrate → up -d → attente, dans l'ordre du guide, jamais autrement. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans les blocs des étapes (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param(
        [Parameter(Mandatory)] $Paths,
        [switch] $StopApplicationFirst,
        [switch] $PortChosenNow
    )
    Invoke-CogesStep -Title 'Téléchargement des images (environ 2 Go, quelques minutes)' -Action {
        $result = Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'pull') -Interactive
        if ($result.ExitCode -ne 0) {
            Stop-CogesStep -Probleme 'Le téléchargement des images a échoué.' -QuoiFaire 'Vérifiez Internet, puis relancez : ce qui est téléchargé est gardé.'
        }
    }
    Invoke-CogesStep -Title 'Contrôle des réglages (check_onprem_env.py)' -Action {
        Invoke-CogesSettingCheck -Paths $Paths -Settings (Get-CogesSetting $Paths)
    }
    if ($StopApplicationFirst) {
        Invoke-CogesStep -Title 'Arrêt de l''application avant la mise à jour de la base' -Action {
            [void](Invoke-CogesCompose -Paths $Paths -Arguments @('stop', 'api', 'worker', 'beat', 'relay', 'front'))
        }
    }
    Invoke-CogesStep -Title 'Préparation de la base (migrations)' -Action {
        $result = Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'run', '--rm', '-T', 'migrate')
        if ($result.ExitCode -ne 0) {
            foreach ($line in ($result.Output | Select-Object -Last 15)) { Write-CogesLine ('    ' + $line) }
            Stop-CogesStep -Probleme 'La préparation de la base a échoué (lignes ci-dessus).' -QuoiFaire 'Relancez -Action Reparer ; si l''échec revient, envoyez le journal à CoGes.'
        }
        $count = @($result.Output | Where-Object { $_ -match 'Running upgrade' }).Count
        if ($count -eq 0) { Write-CogesLine '  Base déjà à jour.' -Kind Ok }
        else { Write-CogesLine ('  Base préparée : {0} étape(s) jouée(s).' -f $count) -Kind Ok }
    }
    Invoke-CogesStep -Title 'Démarrage de CoGes' -Action {
        $result = Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans')
        if ($result.ExitCode -ne 0 -and (Test-CogesPortInUseError $result.Output) -and $PortChosenNow) {
            # Le port était libre au choix, plus maintenant : on en choisit un autre, une fois.
            $port = Select-CogesPort -Listening (@(Get-CogesListeningPort) + [int](Get-CogesSetting $Paths)['COGES_HTTP_PORT'])
            Write-CogesLine ('  Le port vient d''être pris par un autre programme : CoGes passe sur le port {0}.' -f $port) -Kind Attention
            Set-CogesEnvValue -Path $Paths.EnvFile -Values ([ordered]@{ COGES_HTTP_PORT = [string]$port; COGES_PUBLIC_URL = (Get-CogesPublicUrl $port) })
            Invoke-CogesSettingCheck -Paths $Paths -Settings (Get-CogesSetting $Paths)
            $result = Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans')
        }
        if ($result.ExitCode -ne 0) {
            foreach ($line in ($result.Output | Select-Object -Last 10)) { Write-CogesLine ('    ' + $line) }
            if (Test-CogesPortInUseError $result.Output) {
                Stop-CogesStep -Probleme 'Le port de CoGes est pris par un autre programme.' `
                    -QuoiFaire 'Relancez avec -Action Reparer -Port 8080 (ou un autre port libre).'
            }
            Stop-CogesStep -Probleme 'Le démarrage a échoué (lignes ci-dessus).' -QuoiFaire 'Relancez -Action Reparer.'
        }
        Wait-CogesHealthy -Paths $Paths
    }
}

# ---------------------------------------------------------------------------- bloc E : société et licence

function Get-CogesLicenseStatus {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [string] $Slug)
    return Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'run', '--rm', '-T', 'cli', 'license-status', '--slug', $Slug)
}

function Assert-CogesConsole {
    <# create-company demande le mot de passe sans écho : il lui faut une vraie console. #>
    $redirected = $false
    try { $redirected = [Console]::IsInputRedirected } catch { $redirected = $true }
    if ($redirected -or -not [Environment]::UserInteractive -or $Host.Name -ne 'ConsoleHost') {
        Stop-CogesStep -Probleme 'Le mot de passe du gérant doit se taper dans une vraie fenêtre de console.' `
            -QuoiFaire 'Lancez le script dans une fenêtre PowerShell ou le Terminal Windows, pas dans un éditeur (ISE, VS Code) ni à travers un autre script. Rien n''a été créé.'
    }
}

# Python change l'avertissement GetPassWarning en erreur : si la console ne peut pas cacher
# la frappe, getpass s'arrête AVANT de lire, au lieu de lire en clair. Aucun secret ici.
$script:CogesNoEchoGuard = 'PYTHONWARNINGS=error::getpass.GetPassWarning'

function Test-CogesContainerTerminal {
    <# Le conteneur reçoit-il un vrai terminal (test -t 0) ? Sans lui, getpass ne cache rien. #>
    param([Parameter(Mandatory)] $Paths)
    $result = Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'run', '--rm', '--entrypoint', 'test', 'cli', '-t', '0') -Interactive
    return ($result.ExitCode -eq 0)
}

function Stop-CogesNoEcho {
    <# Saisie sans écho impossible : arrêt net, jamais de repli (le mot de passe ne passe par aucun argument). #>
    Stop-CogesStep -Probleme 'Cette console ne peut pas cacher la frappe du mot de passe (GetPassWarning). Rien n''a été créé.' `
        -QuoiFaire 'Relancez la même commande dans une fenêtre PowerShell ou le Terminal Windows ouverts directement (pas dans ISE, VS Code, une session à distance sans terminal ni à travers un autre script).'
}

function Get-CogesCompanyArgument {
    <# Les arguments de create-company : aucun mot de passe, la commande le demande elle-même par getpass. #>
    param([Parameter(Mandatory)] $Answers)
    $arguments = @('--profile', 'tools', 'run', '--rm', '-e', $script:CogesNoEchoGuard, 'cli', 'create-company',
        '--name', $Answers.NomBoutique, '--slug', $Answers.CodeBoutique, '--manager-name', $Answers.NomGerant)
    if ($Answers.TelephoneGerant) { $arguments += @('--manager-phone', $Answers.TelephoneGerant) }
    if ($Answers.EmailGerant) { $arguments += @('--manager-email', $Answers.EmailGerant) }
    return $arguments
}

function New-CogesCompany {
    <# Bloc E : la société n'est créée que si license-status dit « introuvable ». #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] $Answers)
    $status = Get-CogesLicenseStatus -Paths $Paths -Slug $Answers.CodeBoutique
    if ($status.ExitCode -eq 0) {
        Write-CogesLine ('  La société {0} est déjà créée, on continue.' -f $Answers.CodeBoutique) -Kind Ok
        return
    }
    if (-not (Test-CogesCompanyMissing -ExitCode $status.ExitCode -Lines $status.Output)) {
        Stop-CogesStep -Probleme 'L''état de la société ne se lit pas (license-status).' -QuoiFaire 'Relancez -Action Reparer ; si l''échec revient, envoyez le journal à CoGes.'
    }
    Assert-CogesConsole
    if (-not (Test-CogesContainerTerminal -Paths $Paths)) { Stop-CogesNoEcho }
    Write-CogesLine '  Le mot de passe du gérant va être demandé deux fois (12 caractères au moins). Il ne s''affiche pas pendant la frappe.'
    # Console du technicien passée telle quelle (ni l'entrée ni la sortie redirigées) :
    # docker compose run ouvre un terminal, getpass y lit sans écho. Un seul essai.
    $created = Invoke-CogesCompose -Paths $Paths -Arguments (Get-CogesCompanyArgument $Answers) -Interactive
    Write-Log -Message ('create-company : code {0}' -f $created.ExitCode)
    # Quelle que soit la sortie, on relit.
    $after = Get-CogesLicenseStatus -Paths $Paths -Slug $Answers.CodeBoutique
    if ($after.ExitCode -ne 0) {
        Stop-CogesStep -Probleme 'La société n''a pas été créée.' `
            -QuoiFaire 'Lisez le message ci-dessus : mot de passe trop court, saisies différentes ou code déjà pris, relancez la même commande ; « GetPassWarning », la console ne cache pas la frappe, relancez dans une fenêtre PowerShell ou le Terminal Windows ouverts directement.'
    }
    Write-CogesLine ('  Société {0} créée.' -f $Answers.CodeBoutique) -Kind Ok
}

function Set-CogesLicense {
    <# activate-license, puis license-status : « Accès : actif » et « Fin de période : sans fin ». #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] $Answers)
    $result = Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'run', '--rm', '-T', 'cli', 'activate-license',
        '--slug', $Answers.CodeBoutique, '--plan', $Answers.Offre, '--note', $Answers.NoteContrat)
    foreach ($line in $result.Output) {
        if ($line -and $line -notmatch '^\s*Container ') { Write-CogesLine ('  ' + $line) }
    }
    if ($result.ExitCode -ne 0) {
        $what = 'Lisez le message ci-dessus (guide, étape 9), puis relancez.'
        if ($result.ExitCode -eq 5) { $what = 'Trop de comptes actifs pour cette offre : désactivez-en dans Réglages > Personnes, ou relancez avec une offre plus grande.' }
        Stop-CogesStep -Probleme 'La licence n''a pas été posée.' -QuoiFaire $what
    }
    $status = Get-CogesLicenseStatus -Paths $Paths -Slug $Answers.CodeBoutique
    if ($status.ExitCode -ne 0 -or -not (Test-CogesLicenseActive $status.Output)) {
        foreach ($line in $status.Stdout) { Write-CogesLine ('  ' + $line) }
        Stop-CogesStep -Probleme 'La licence ne se relit pas « actif, sans fin ».' -QuoiFaire 'Relancez la même commande ; si l''échec revient, envoyez le journal à CoGes.'
    }
    Write-CogesLine '  Licence : accès actif, sans fin.' -Kind Ok
}

function Test-CogesSite {
    <# La sonde du workflow « Sur site » : / en 200, /api/v1/platform/ en 404. #>
    param([Parameter(Mandatory)] [string] $Url, [int] $TimeoutSeconds = 60)
    foreach ($probe in @(@{ Path = '/'; Code = 200 }, @{ Path = '/api/v1/platform/'; Code = 404 })) {
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        $code = 0
        while ((Get-Date) -lt $deadline) {
            $code = Get-CogesHttpStatus ($Url + $probe.Path)
            if ($code -eq $probe.Code) { break }
            Start-Sleep -Seconds 3
        }
        if ($code -ne $probe.Code) {
            Stop-CogesStep -Probleme ('{0}{1} répond {2}, {3} attendu.' -f $Url, $probe.Path, $code, $probe.Code) `
                -QuoiFaire 'Attendez une minute et relancez -Action Reparer ; si l''échec revient, envoyez le journal à CoGes.'
        }
    }
    Write-CogesLine ('  {0} répond.' -f $Url) -Kind Ok
}

# ---------------------------------------------------------------------------- bloc F : confort

function Get-CogesUserPath {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
    try { return [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) }
    finally { $key.Dispose() }
}

function Set-CogesUserPath {
    <# PATH de l'utilisateur (jamais celui de la machine), « %…% » gardés, puis prévenir
       Windows pour que les nouvelles fenêtres le voient. #>
    param([AllowEmptyString()] [string] $Value)
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try { $key.SetValue('Path', $Value, [Microsoft.Win32.RegistryValueKind]::ExpandString) }
    finally { $key.Dispose() }
    if (-not ('CogesNative' -as [type])) {
        Add-Type -Namespace '' -Name 'CogesNative' -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll", SetLastError = true, CharSet = System.Runtime.InteropServices.CharSet.Auto)]
public static extern System.IntPtr SendMessageTimeout(System.IntPtr hWnd, uint Msg, System.UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out System.UIntPtr lpdwResult);
'@
    }
    $result = [UIntPtr]::Zero
    [void][CogesNative]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result)
}

function Install-CogesComfort {
    <# bin\coges.cmd et PATH, raccourci du Bureau, tâche à l'ouverture de session. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans les blocs des étapes (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [string] $Url)
    Invoke-CogesStep -Title 'Commande « coges » pour toute nouvelle fenêtre' -Action {
        New-Item -ItemType Directory -Force -Path $Paths.Bin | Out-Null
        [IO.File]::WriteAllText((Join-Path $Paths.Bin 'coges.cmd'), (New-CogesCmdText -EnvFile $Paths.EnvFile -Compose $Paths.Compose), [Text.Encoding]::ASCII)
        $current = Get-CogesUserPath
        $wanted = Add-CogesPathEntry -PathValue $current -Directory $Paths.Bin
        if ($wanted -ne $current) { Set-CogesUserPath $wanted }
        Write-CogesLine '  « coges ps », « coges logs api »… marchent dans toute nouvelle fenêtre.' -Kind Ok
    }
    Invoke-CogesStep -Title 'Raccourci « CoGes » sur le Bureau' -Action {
        $desktop = [Environment]::GetFolderPath('Desktop')
        [IO.File]::WriteAllText((Join-Path $desktop 'CoGes.url'), (New-CogesShortcutText $Url), [Text.Encoding]::ASCII)
    }
    Invoke-CogesStep -Title ('Tâche planifiée « {0} » (filet de sécurité à l''ouverture de session)' -f $script:CogesTaskName) -Action {
        $launcher = Join-Path $Paths.Programme 'windows\demarrage.ps1'
        $argument = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Racine "{1}"' -f $launcher, $Paths.Racine
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
        Register-ScheduledTask -TaskName $script:CogesTaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    }
}

function Start-CogesAtLogon {
    <# La tâche planifiée : attend le moteur Docker (5 minutes au plus), puis up -d. #>
    param([Parameter(Mandatory)] [string] $Racine, [int] $TimeoutSeconds = 300, [int] $LockWaitSeconds = 900)
    $paths = Get-CogesPath $Racine
    $script:CogesState.LogPath = Join-Path $paths.Journaux ('demarrage-{0}.log' -f (Get-Date).ToString('yyyyMMdd'))
    New-Item -ItemType Directory -Force -Path $paths.Journaux | Out-Null
    [void](Get-CogesSetting $paths)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Invoke-Docker -Arguments @('version', '--format', '{{.Server.Os}}')).ExitCode -eq 0) {
            # Une restauration en cours arrête l'application exprès : on l'attend (15 min), sinon rien.
            try { $lock = Enter-CogesLock -Paths $paths -Action 'Démarrage' -WaitSeconds $LockWaitSeconds -IntervalSeconds 15 }
            catch {
                Write-Log -Message ('verrou pris, up -d non lancé : ' + $_.Exception.Message) -Level ATTENTION
                [void](Send-CogesPing -Paths $paths -Signal 'vie' -Failure -Reason 'verrou')
                return 1
            }
            try {
                $up = Invoke-CogesCompose -Paths $paths -Arguments @('up', '-d')
                Write-Log -Message ('up -d : code {0}' -f $up.ExitCode)
            }
            finally { Exit-CogesLock $lock }
            # Lot 6 : « je vais bien » (ou /fail), après le démarrage, verrou rendu.
            if ($up.ExitCode -eq 0) { [void](Send-CogesPing -Paths $paths -Signal 'vie') }
            else { [void](Send-CogesPing -Paths $paths -Signal 'vie' -Failure -Reason 'demarrage') }
            return $up.ExitCode
        }
        Start-Sleep -Seconds 10
    }
    Write-Log -Message 'Le moteur Docker n''a pas répondu en 5 minutes : rien lancé.' -Level ECHEC
    [void](Send-CogesPing -Paths $paths -Signal 'vie' -Failure -Reason 'docker-arrete')
    return 1
}

# ---------------------------------------------------------------------------- lot 4 : sauvegarde (ADR 0127)
#
# Ce qui est binaire (dump, fichier chiffré) ne traverse JAMAIS un tube PowerShell : il reste
# dans les conteneurs (volume sauvegarde-travail) ou passe par des fichiers. Le dump en clair
# ne touche ni le dossier du PC ni la clé USB. Seule la clé privée (une ligne de texte) passe
# par l'entrée standard du conteneur qui déchiffre, à la restauration ; jamais un argument,
# une variable d'environnement, un fichier copié sur le PC, l'écran ou le journal.

#: Heures des sauvegardes automatiques, et rattrapage au démarrage au-delà de 20 h.
$script:CogesBackupSlots = @('13:00', '20:30')
$script:CogesBackupCatchUpHours = 20
$script:CogesBackupTaskName = 'CoGes - sauvegarde'
#: Rétention sur le PC (14 dernières, 1 par semaine sur 8, 1 par mois sur 12) et sur le disque.
$script:CogesKeepLast = 14
$script:CogesKeepWeeks = 8
$script:CogesKeepMonths = 12
$script:CogesKeepOffsite = 10
#: Place minimale laissée libre après une sauvegarde.
$script:CogesMinFreeBytes = 2GB
#: Taille minimale par rapport à la dernière bonne (comme la production, ADR 0088).
$script:CogesMinRatio = 0.5
#: Le repère d'un disque préparé par le technicien, à sa racine : il contient le code de la boutique.
$script:CogesDiskMarker = 'COGES-SAUVEGARDE.txt'
$script:CogesOffsiteFolder = 'CoGes'
$script:CogesPrivatePrefix = 'COGES-CLE-PRIVEE-1:'
$script:CogesPublicPrefix = 'COGES-CLE-PUBLIQUE-1:'
#: Alertes : plus de 48 h sans bonne sauvegarde, 7 jours sans copie hors du PC, moins de 5 Go libres.
$script:CogesAlertBackupHours = 48
$script:CogesAlertOffsiteDays = 7
$script:CogesAlertFreeBytes = 5GB
#: Le verrou commun (sauvegarde, restauration, essai, démarrage, réparation).
$script:CogesLockFile = 'coges.verrou'
#: Notifications Windows : coupées par -SansNotification (tests, technicien).
$script:CogesToastEnabled = $true

#: Les sauvegardes faites AVANT une action portent sa raison à la fin du nom (lot 5, bloc 0) :
#: la plus récente d'une clé USB n'est plus confondue avec celle d'une base neuve et vide.
$script:CogesBackupReasons = @('avant-effacement', 'avant-restauration', 'avant-maj', 'avant-retour', 'installation')
$script:CogesBackupPattern = '^coges-(?<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-(?<date>\d{8})-(?<time>\d{4}(?:\d{2})?)-(?<version>[A-Za-z0-9][A-Za-z0-9.-]*?)(?:-(?<raison>' + ($script:CogesBackupReasons -join '|') + '))?\.coges$'

function Get-CogesBackupPath {
    <# Les endroits de la sauvegarde, à côté des trois du guide. #>
    param([Parameter(Mandatory)] $Paths)
    $folder = Join-Path $Paths.Racine 'sauvegardes'
    return [pscustomobject]@{
        Dossier     = $folder
        Restauration = Join-Path $folder 'restauration'
        Etat        = Join-Path $folder 'etat.json'
        ClePublique = Join-Path $Paths.Reglages 'cle-publique-sauvegarde.txt'
        Verrou      = Join-Path $Paths.Racine $script:CogesLockFile
    }
}

# ---------------------------------------------------------------------------- noms et rétention (fonctions pures)

function Get-CogesBackupName {
    <# coges-<code-boutique>-AAAAMMJJ-HHMM-<version>[-<raison>].coges #>
    param(
        [Parameter(Mandatory)] [string] $Slug,
        [Parameter(Mandatory)] [datetime] $Date,
        [Parameter(Mandatory)] [string] $Version,
        [switch] $WithSeconds,
        [AllowEmptyString()] [string] $Raison = ''
    )
    if ($Raison -and ($script:CogesBackupReasons -cnotcontains $Raison)) { throw ('Raison de sauvegarde inconnue : ' + $Raison) }
    $format = 'yyyyMMdd-HHmm'
    if ($WithSeconds) { $format = 'yyyyMMdd-HHmmss' }
    $suffix = ''
    if ($Raison) { $suffix = '-' + $Raison }
    return ('coges-{0}-{1}-{2}{3}.coges' -f $Slug, $Date.ToString($format, [Globalization.CultureInfo]::InvariantCulture), $Version, $suffix)
}

function ConvertFrom-CogesBackupName {
    <# Le code, la date et la version d'un nom de sauvegarde ; $null pour tout autre nom. #>
    param([AllowEmptyString()] [string] $Name)
    if ($Name -cnotmatch $script:CogesBackupPattern) { return $null }
    $stamp = $Matches['date'] + $Matches['time'].PadRight(6, '0')
    $date = [datetime]::ParseExact($stamp, 'yyyyMMddHHmmss', [Globalization.CultureInfo]::InvariantCulture)
    $reason = ''
    if ($Matches.ContainsKey('raison')) { $reason = $Matches['raison'] }
    return [pscustomobject]@{ Name = $Name; Slug = $Matches['slug']; Date = $date; Version = $Matches['version']; Raison = $reason }
}

function Select-CogesBackupToDelete {
    <# Les noms à effacer : on garde les $Keep dernières, la plus récente de chacune des
       $Weeks dernières semaines et de chacun des $Months derniers mois. La plus récente
       n'est jamais effacée. Les éléments : Name et Date (bonnes sauvegardes seulement). #>
    param(
        [AllowEmptyCollection()] [object[]] $Items = @(),
        [Parameter(Mandatory)] [datetime] $Now,
        [int] $Keep = $script:CogesKeepLast,
        [int] $Weeks = $script:CogesKeepWeeks,
        [int] $Months = $script:CogesKeepMonths
    )
    $sorted = @($Items | Sort-Object -Property @{ Expression = 'Date'; Descending = $true }, @{ Expression = 'Name'; Descending = $true })
    if ($sorted.Count -eq 0) { return @() }
    $kept = @{}
    for ($index = 0; $index -lt [Math]::Min([Math]::Max($Keep, 1), $sorted.Count); $index++) { $kept[$sorted[$index].Name] = $true }
    $weekStart = $Now.Date.AddDays(-(([int]$Now.DayOfWeek + 6) % 7))
    $weeksSeen = @{}
    $monthsSeen = @{}
    foreach ($item in $sorted) {
        $date = [datetime]$item.Date
        $monday = $date.Date.AddDays(-(([int]$date.DayOfWeek + 6) % 7))
        $weekAge = [int](($weekStart - $monday).TotalDays / 7)
        if ($weekAge -ge 0 -and $weekAge -lt $Weeks -and -not $weeksSeen.ContainsKey($weekAge)) {
            $weeksSeen[$weekAge] = $true
            $kept[$item.Name] = $true
        }
        $monthAge = ($Now.Year - $date.Year) * 12 + ($Now.Month - $date.Month)
        if ($monthAge -ge 0 -and $monthAge -lt $Months -and -not $monthsSeen.ContainsKey($monthAge)) {
            $monthsSeen[$monthAge] = $true
            $kept[$item.Name] = $true
        }
    }
    return @($sorted | Where-Object { -not $kept.ContainsKey($_.Name) } | ForEach-Object { $_.Name })
}

function Test-CogesBackupDue {
    <# Faut-il sauvegarder maintenant ? Oui si la dernière bonne a plus de 20 h, ou si une
       heure prévue (13 h 00, 20 h 30) est passée depuis la dernière bonne. #>
    param(
        [Parameter(Mandatory)] [datetime] $Now,
        [AllowNull()] $LastGood,
        [string[]] $Slots = $script:CogesBackupSlots,
        [int] $CatchUpHours = $script:CogesBackupCatchUpHours
    )
    if ($null -eq $LastGood) { return $true }
    $last = [datetime]$LastGood
    if (($Now - $last).TotalHours -ge $CatchUpHours) { return $true }
    $latestSlot = $null
    foreach ($day in @($Now.Date.AddDays(-1), $Now.Date)) {
        foreach ($slot in $Slots) {
            $parts = $slot.Split(':')
            $at = $day.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
            if ($at -le $Now -and ($null -eq $latestSlot -or $at -gt $latestSlot)) { $latestSlot = $at }
        }
    }
    return ($null -ne $latestSlot -and $last -lt $latestSlot)
}

function Test-CogesTrialDue {
    <# La restauration d'essai : une fois par semaine, le dimanche ou au premier passage
       après. Due si aucun essai réussi depuis le dernier dimanche 0 h. #>
    param([Parameter(Mandatory)] [datetime] $Now, [AllowNull()] $LastSuccess)
    $sunday = $Now.Date.AddDays(-([int]$Now.DayOfWeek))
    if ($null -eq $LastSuccess) { return $true }
    return ([datetime]$LastSuccess -lt $sunday)
}

function Test-CogesSizePlausible {
    <# Non vide, et pas moins de la moitié de la dernière bonne (base vidée, dump coupé ?). #>
    param([long] $Size, [long] $Previous = 0, [double] $Ratio = $script:CogesMinRatio)
    if ($Size -le 0) { return $false }
    if ($Previous -le 0) { return $true }
    return ($Size -ge [Math]::Floor($Ratio * $Previous))
}

function Test-CogesEnoughSpace {
    <# Après la sauvegarde prévue, il doit rester 2 Go libres. #>
    param([long] $Free, [long] $Planned, [long] $Minimum = $script:CogesMinFreeBytes)
    return (($Free - $Planned) -ge $Minimum)
}

function Get-CogesDiskMarkerState {
    <# Le repère d'un disque : absent, autre (une autre boutique) ou ok. #>
    # Sans type : un [string] changerait $null (pas de repère) en '' (repère vide).
    param([AllowNull()] $MarkerText, [AllowEmptyCollection()] [string[]] $Slugs = @())
    if ($null -eq $MarkerText) { return 'absent' }
    $slug = ([string]$MarkerText -replace '^\uFEFF', '').Trim()
    if ($slug -and (@($Slugs) -ccontains $slug)) { return 'ok' }
    return 'autre'
}

function Get-CogesBackupAlert {
    <# Ce qu'il faut dire au commerçant (rien si tout va bien). Mots simples, sans jargon. #>
    param(
        [Parameter(Mandatory)] [datetime] $Now,
        [AllowNull()] $LastGood,
        [AllowNull()] $LastOffsite,
        [long] $FreeBytes = [long]::MaxValue,
        [AllowNull()] $TrialOk
    )
    $alerts = New-Object System.Collections.Generic.List[object]
    if ($null -eq $LastGood -or ($Now - [datetime]$LastGood).TotalHours -ge $script:CogesAlertBackupHours) {
        $alerts.Add([pscustomobject]@{ Code = 'sauvegarde'; Texte = 'CoGes n''a pas pu sauvegarder vos données depuis 2 jours. Laissez le PC allumé et appelez CoGes si ce message revient.' })
    }
    if ($null -eq $LastOffsite -or ($Now - [datetime]$LastOffsite).TotalDays -ge $script:CogesAlertOffsiteDays) {
        $alerts.Add([pscustomobject]@{ Code = 'cle'; Texte = 'Branchez la clé CoGes : vos données n''ont pas été copiées hors du PC depuis 7 jours.' })
    }
    if ($FreeBytes -lt $script:CogesAlertFreeBytes) {
        $alerts.Add([pscustomobject]@{ Code = 'disque'; Texte = 'Le disque du PC est presque plein : CoGes ne pourra bientôt plus sauvegarder. Appelez CoGes.' })
    }
    if ($false -eq $TrialOk) {
        $alerts.Add([pscustomobject]@{ Code = 'essai'; Texte = 'La dernière sauvegarde ne se relit pas : appelez CoGes.' })
    }
    return $alerts.ToArray()
}

# ---------------------------------------------------------------------------- clés (X25519, RFC 7748)

function ConvertTo-CogesBase64Url {
    param([Parameter(Mandatory)] [byte[]] $Bytes)
    return [Convert]::ToBase64String($Bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function ConvertFrom-CogesBase64Url {
    param([Parameter(Mandatory)] [string] $Text)
    $padded = $Text.Replace('-', '+').Replace('_', '/')
    $padded += '=' * ((4 - $padded.Length % 4) % 4)
    return , [Convert]::FromBase64String($padded)
}

function Get-CogesX25519Public {
    <# La clé publique X25519 d'une clé privée (RFC 7748, échelle de Montgomery). Windows
       PowerShell 5.1 (.NET Framework) n'a pas X25519 : calcul en BigInteger, une fois par
       installation. Vérifié contre le vecteur du § 6.1 (tests Pester et Python). #>
    param([Parameter(Mandatory)] [byte[]] $Private)
    if ($Private.Length -ne 32) { throw 'clé privée X25519 : 32 octets attendus' }
    try { Add-Type -AssemblyName System.Numerics -ErrorAction Stop } catch { Write-Verbose 'System.Numerics déjà chargé' }
    $k = [byte[]]$Private.Clone()
    $k[0] = $k[0] -band 248
    $k[31] = ($k[31] -band 127) -bor 64
    $p = [Numerics.BigInteger]::Pow(2, 255) - 19
    $a24 = New-Object Numerics.BigInteger 121665
    $x1 = New-Object Numerics.BigInteger 9
    $x2 = [Numerics.BigInteger]::One
    $z2 = [Numerics.BigInteger]::Zero
    $x3 = $x1
    $z3 = [Numerics.BigInteger]::One
    $swap = 0
    for ($t = 254; $t -ge 0; $t--) {
        # Le bit t du scalaire, lu dans les octets (petit-boutiste) : ni -shr ni -band sur un
        # BigInteger, que Windows PowerShell 5.1 convertirait en Int64.
        $bit = ([int]$k[[int][Math]::Floor($t / 8)] -shr ($t % 8)) -band 1
        if ($swap -bxor $bit) { $tmp = $x2; $x2 = $x3; $x3 = $tmp; $tmp = $z2; $z2 = $z3; $z3 = $tmp }
        $swap = $bit
        $a = ($x2 + $z2) % $p
        $aa = ($a * $a) % $p
        $b = (($x2 - $z2) % $p + $p) % $p
        $bb = ($b * $b) % $p
        $e = (($aa - $bb) % $p + $p) % $p
        $c = ($x3 + $z3) % $p
        $d = (($x3 - $z3) % $p + $p) % $p
        $da = ($d * $a) % $p
        $cb = ($c * $b) % $p
        $sum = ($da + $cb) % $p
        $diff = (($da - $cb) % $p + $p) % $p
        $x3 = ($sum * $sum) % $p
        $z3 = ($x1 * (($diff * $diff) % $p)) % $p
        $x2 = ($aa * $bb) % $p
        $z2 = ($e * (($aa + ($a24 * $e) % $p) % $p)) % $p
    }
    if ($swap) { $x2 = $x3; $z2 = $z3 }
    $u = ($x2 * [Numerics.BigInteger]::ModPow($z2, $p - 2, $p)) % $p
    $raw = $u.ToByteArray()
    $out = New-Object byte[] 32
    [Array]::Copy($raw, $out, [Math]::Min(32, $raw.Length))
    return , $out
}

function New-CogesKeyPair {
    <# Une paire de clés de sauvegarde, en texte : COGES-CLE-PRIVEE-1:… et COGES-CLE-PUBLIQUE-1:… #>
    $private = New-CogesRandomByte 32
    $public = Get-CogesX25519Public $private
    return [pscustomobject]@{
        Private = $script:CogesPrivatePrefix + (ConvertTo-CogesBase64Url $private)
        Public  = $script:CogesPublicPrefix + (ConvertTo-CogesBase64Url $public)
    }
}

function Test-CogesKeyText {
    <# Une ligne « COGES-CLE-PUBLIQUE-1:… » (ou PRIVEE) de 32 octets en base64 url-safe. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Text, [ValidateSet('Publique', 'Privee')] [string] $Kind)
    if (-not $Text) { return $false }
    $lines = @(($Text -replace '^\uFEFF', '') -split "`r?`n" | Where-Object { $_.Trim() })
    if ($lines.Count -ne 1) { return $false }
    $prefix = $script:CogesPublicPrefix
    if ($Kind -eq 'Privee') { $prefix = $script:CogesPrivatePrefix }
    $line = $lines[0].Trim()
    if (-not $line.StartsWith($prefix, [StringComparison]::Ordinal)) { return $false }
    $body = $line.Substring($prefix.Length)
    if ($body -cnotmatch '^[A-Za-z0-9_-]{43}$') { return $false }
    return ((ConvertFrom-CogesBase64Url $body).Length -eq 32)
}

function Read-CogesKeyFile {
    <# Lit un fichier de clé (une ligne), refuse tout autre contenu. Jamais affiché. #>
    param([Parameter(Mandatory)] [string] $Path, [ValidateSet('Publique', 'Privee')] [string] $Kind)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Stop-CogesStep -Probleme ('Fichier de clé introuvable : {0}' -f $Path) -QuoiFaire 'Vérifiez le chemin (clé USB branchée ?), puis relancez.'
    }
    $text = [IO.File]::ReadAllText($Path)
    if (-not (Test-CogesKeyText -Text $text -Kind $Kind)) {
        $what = 'clé publique (COGES-CLE-PUBLIQUE-1:…)'
        if ($Kind -eq 'Privee') { $what = 'clé privée (COGES-CLE-PRIVEE-1:…)' }
        Stop-CogesStep -Probleme ('{0} n''est pas une {1}.' -f $Path, $what) -QuoiFaire 'Donnez le bon fichier, tel que tiré par CoGes, sans le modifier.'
    }
    return (($text -replace '^\uFEFF', '').Trim())
}

function Test-CogesExternalTarget {
    <# Un disque ou un dossier HORS du PC pour la clé privée ou les copies : jamais sous C:\CoGes,
       jamais le disque de Windows. #>
    param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Racine)
    $full = [IO.Path]::GetFullPath(($Path.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar))
    $root = [IO.Path]::GetFullPath(($Racine.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar))
    if ($full.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $false }
    # Essais (Pester sous Windows, verifier.sh) : des dossiers nommés tiennent lieu de disques.
    $trial = @(([string]$env:COGES_DISQUES_ESSAI) -split [IO.Path]::PathSeparator | Where-Object { $_ } |
            ForEach-Object { [IO.Path]::GetFullPath(($_.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar)) })
    if ($trial -contains $full) { return (Test-Path -LiteralPath $full -PathType Container) }
    if (Test-CogesWindows) {
        $system = ($env:SystemDrive + '\')
        if ([IO.Path]::GetPathRoot($full) -ieq $system) { return $false }
    }
    return (Test-Path -LiteralPath $full -PathType Container)
}

function ConvertTo-CogesDriveRoot {
    <# « E: », « E », « E:\ » → « E:\ » ; un dossier (essais sous Linux) reste tel quel. #>
    param([Parameter(Mandatory)] [string] $Lecteur)
    if ($Lecteur -match '^[A-Za-z]:?\\?$') { return ($Lecteur.Substring(0, 1).ToUpperInvariant() + ':\') }
    return $Lecteur
}

function Set-CogesBackupKey {
    <# La clé publique de sauvegarde de ce PC. -ClePublique : posée depuis le fichier tiré chez
       le technicien (de préférence). Sinon, tirée ici : la clé PRIVÉE est écrite dans un
       fichier sur le disque amovible -LecteurCle, jamais à l'écran, au journal ni au
       presse-papiers, puis COPIE-FAITE est demandé. Rien à faire si la clé est déjà là. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options, [Parameter(Mandatory)] [string] $Slug)
    $backup = Get-CogesBackupPath $Paths
    if ($Options.ClePublique) {
        $text = Read-CogesKeyFile -Path $Options.ClePublique -Kind Publique
        if ((Test-Path -LiteralPath $backup.ClePublique) -and ([IO.File]::ReadAllText($backup.ClePublique).Trim() -ceq $text)) {
            Write-CogesLine '  Clé publique de sauvegarde déjà posée, rien à faire.' -Kind Ok
            return
        }
        if (Test-Path -LiteralPath $backup.ClePublique) {
            Write-CogesLine '  Clé publique remplacée : les sauvegardes déjà faites gardent l''ancienne clé privée.' -Kind Attention
        }
        New-Item -ItemType Directory -Force -Path $Paths.Reglages | Out-Null
        [IO.File]::WriteAllText($backup.ClePublique, $text + "`n", (New-Object Text.UTF8Encoding $false))
        Write-CogesLine '  Clé publique de sauvegarde posée (ce PC chiffre, il ne peut pas relire).' -Kind Ok
        return
    }
    if (Test-Path -LiteralPath $backup.ClePublique) {
        [void](Read-CogesKeyFile -Path $backup.ClePublique -Kind Publique)
        Write-CogesLine '  Clé publique de sauvegarde présente, rien à faire.' -Kind Ok
        return
    }
    $drive = $Options.LecteurCle
    if (-not $drive) {
        if ($script:CogesState.NonInteractif) {
            Stop-CogesStep -Probleme 'Aucune clé de sauvegarde sur ce PC.' `
                -QuoiFaire 'Donnez -ClePublique <fichier> (tiré chez CoGes), ou -LecteurCle E: (clé USB du technicien) pour la tirer ici.'
        }
        $drive = Read-Host 'Pas de clé de sauvegarde : lettre de la clé USB du technicien où écrire la clé PRIVÉE (ex. E:)'
    }
    $root = ConvertTo-CogesDriveRoot $drive
    if (-not (Test-CogesExternalTarget -Path $root -Racine $Paths.Racine)) {
        Stop-CogesStep -Probleme ('{0} n''est pas un disque amovible branché (ni C:, ni le dossier de CoGes).' -f $drive) `
            -QuoiFaire 'Branchez la clé USB du technicien et donnez sa lettre (-LecteurCle E:), ou donnez -ClePublique <fichier>.'
    }
    $pair = New-CogesKeyPair
    $file = Join-Path $root ('CoGes-cle-privee-{0}-{1}.txt' -f $Slug, (Get-Date).ToString('yyyyMMdd-HHmm'))
    # CreateNew : jamais une clé existante écrasée. Le texte ne passe par aucune ligne affichée.
    $stream = New-Object IO.FileStream ($file, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        $bytes = [Text.Encoding]::ASCII.GetBytes($pair.Private + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
    }
    finally { $stream.Dispose() }
    $pair.Private = $null
    New-Item -ItemType Directory -Force -Path $Paths.Reglages | Out-Null
    [IO.File]::WriteAllText($backup.ClePublique, $pair.Public + "`n", (New-Object Text.UTF8Encoding $false))
    Write-CogesLine ('  Clé PRIVÉE de sauvegarde écrite dans {0} (elle n''est pas sur ce PC).' -f $file) -Kind Attention
    Write-CogesLine '  Rangez ce fichier dans le gestionnaire de mots de passe de CoGes (fiche du client), puis effacez-le de la clé USB. Sans lui, aucune sauvegarde de ce client ne se relit.' -Kind Attention
    Confirm-CogesWord -Word 'COPIE-FAITE' -Prompt 'Clé privée rangée chez CoGes ?' -Given $Options.CleCopiee -Parameter 'CleCopiee'
}

# ---------------------------------------------------------------------------- verrou commun

function Enter-CogesLock {
    <# Le verrou de C:\CoGes : un fichier ouvert sans partage le temps de l'action. Le système
       le libère quand le processus s'arrête, même tué : un verrou laissé par un processus mort
       se reprend donc seul. Pris : attend $WaitSeconds, puis s'arrête avec un message clair. #>
    param(
        [Parameter(Mandatory)] $Paths,
        [Parameter(Mandatory)] [string] $Action,
        [int] $WaitSeconds = 0,
        [int] $IntervalSeconds = 5
    )
    if ($script:CogesState.Simulation) { return $null }
    $backup = Get-CogesBackupPath $Paths
    New-Item -ItemType Directory -Force -Path $Paths.Racine | Out-Null
    $info = $backup.Verrou + '.info'
    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ($true) {
        try {
            $stream = New-Object IO.FileStream ($backup.Verrou, [IO.FileMode]::OpenOrCreate, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
            $text = '{0} (processus {1}) depuis le {2}' -f $Action, $PID, (Get-Date).ToString('dd/MM/yyyy à HH:mm')
            [IO.File]::WriteAllText($info, $text, (New-Object Text.UTF8Encoding $false))
            Write-Log -Message ('verrou pris : ' + $Action)
            return $stream
        }
        catch [IO.IOException] {
            if ((Get-Date) -ge $deadline) {
                $holder = 'une autre opération de CoGes'
                if (Test-Path -LiteralPath $info) { try { $holder = [IO.File]::ReadAllText($info) } catch { Write-Verbose 'info du verrou illisible' } }
                Stop-CogesStep -Probleme ('Une autre opération de CoGes est en cours : {0}.' -f $holder) `
                    -QuoiFaire 'Attendez qu''elle finisse (une sauvegarde dure quelques minutes), puis relancez. Si rien ne tourne, redémarrez le PC : le verrou d''un programme arrêté se libère seul.'
            }
            Start-Sleep -Seconds $IntervalSeconds
        }
    }
}

function Exit-CogesLock {
    param([AllowNull()] $Lock)
    if ($null -ne $Lock) {
        $Lock.Dispose()
        Write-Log -Message 'verrou rendu'
    }
}

# ---------------------------------------------------------------------------- état

function Read-CogesBackupState {
    <# Ce que les fichiers ne disent pas : dernière copie hors du PC, dernier essai, dernière erreur. #>
    param([Parameter(Mandatory)] $Paths)
    $file = (Get-CogesBackupPath $Paths).Etat
    $state = @{}
    if (Test-Path -LiteralPath $file) {
        try {
            $data = [IO.File]::ReadAllText($file) | ConvertFrom-Json
            foreach ($property in $data.PSObject.Properties) { $state[$property.Name] = $property.Value }
        }
        catch { Write-Log -Message 'etat.json illisible : ignoré' -Level ATTENTION }
    }
    return $state
}

function Write-CogesBackupState {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Changes)
    $state = Read-CogesBackupState $Paths
    foreach ($key in $Changes.Keys) { $state[$key] = $Changes[$key] }
    $file = (Get-CogesBackupPath $Paths).Etat
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    $temporary = $file + '.nouveau'
    [IO.File]::WriteAllText($temporary, ([pscustomobject]$state | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $file -Force
}

function ConvertTo-CogesStateDate {
    param([AllowNull()] $Value)
    if ($null -eq $Value -or $Value -eq '') { return $null }
    if ($Value -is [datetime]) { return $Value }
    return [datetime]::Parse([string]$Value, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
}

function Get-CogesGoodBackup {
    <# Les bonnes sauvegardes d'un dossier : un nom attendu, et le .sha256 et le .manifest.json
       à côté. Jamais un .echec, jamais un autre fichier. Les plus récentes d'abord. #>
    param([Parameter(Mandatory)] [string] $Folder)
    if (-not (Test-Path -LiteralPath $Folder)) { return @() }
    $items = foreach ($file in (Get-ChildItem -LiteralPath $Folder -File -Filter '*.coges' -ErrorAction SilentlyContinue)) {
        $parsed = ConvertFrom-CogesBackupName $file.Name
        if ($null -eq $parsed) { continue }
        if (-not (Test-Path -LiteralPath ($file.FullName + '.sha256'))) { continue }
        if (-not (Test-Path -LiteralPath ($file.FullName + '.manifest.json'))) { continue }
        $parsed | Add-Member -NotePropertyName Path -NotePropertyValue $file.FullName
        $parsed | Add-Member -NotePropertyName Size -NotePropertyValue $file.Length
        $parsed
    }
    return @($items | Sort-Object -Property @{ Expression = 'Date'; Descending = $true }, @{ Expression = 'Name'; Descending = $true })
}

function Remove-CogesBackupFile {
    <# Une sauvegarde et ses deux compagnons. #>
    param([Parameter(Mandatory)] [string] $Path)
    foreach ($suffix in @('', '.sha256', '.manifest.json')) {
        if (Test-Path -LiteralPath ($Path + $suffix)) { Remove-Item -LiteralPath ($Path + $suffix) -Force }
    }
}

function Get-CogesFileSha256 {
    param([Parameter(Mandatory)] [string] $Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Read-CogesSha256File {
    <# « <empreinte>  <nom> » (format de sha256sum). #>
    param([Parameter(Mandatory)] [string] $Path)
    $text = [IO.File]::ReadAllText($Path).Trim()
    return ($text -split '\s+')[0].ToLowerInvariant()
}

# ---------------------------------------------------------------------------- conteneurs

function Get-CogesToolArgument {
    <# Les arguments de compose pour un outil de sauvegarde : -T, montages, entrée standard
       ouverte (-i par défaut de « run »). Aucun -e : rien ne passe par l'environnement. #>
    param(
        [Parameter(Mandatory)] [ValidateSet('sauvegarde-py', 'sauvegarde-pg')] [string] $Service,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [AllowEmptyCollection()] [string[]] $Mounts = @()
    )
    $result = @('--profile', 'tools', 'run', '--rm', '-T')
    foreach ($mount in $Mounts) { $result += @('-v', $mount) }
    return ($result + @($Service) + $Arguments)
}

function Invoke-CogesTool {
    <# Lance un outil ; un échec devient un message (la ligne « ÉCHEC — … » de l'outil). #>
    param(
        [Parameter(Mandatory)] $Paths,
        [Parameter(Mandatory)] [string] $Service,
        [Parameter(Mandatory)] [string[]] $Arguments,
        [AllowEmptyCollection()] [string[]] $Mounts = @(),
        [AllowNull()] [string] $InputText = $null,
        [Parameter(Mandatory)] [string] $What
    )
    $composeArgs = Get-CogesToolArgument -Service $Service -Arguments $Arguments -Mounts $Mounts
    $result = Invoke-Docker -Arguments (Get-CogesComposeArgument -Paths $Paths -Arguments $composeArgs) -InputText $InputText
    if ($result.ExitCode -ne 0) {
        $reason = @($result.Output | Where-Object { $_ -match '^\s*(ÉCHEC|ECHEC|pg_dump: error|pg_restore: error|error)' } | Select-Object -Last 1)
        $detail = 'code ' + $result.ExitCode
        if ($reason.Count -gt 0) { $detail = $reason[0].Trim() }
        Stop-CogesStep -Probleme ('{0} : échec ({1}).' -f $What, $detail) `
            -QuoiFaire 'Relancez ; si l''échec revient, envoyez le journal (C:\CoGes\journaux) à CoGes.'
    }
    return $result
}

function Get-CogesLastJson {
    <# La dernière ligne JSON d'une sortie d'outil (après les lignes « Container … » de compose). #>
    param([AllowEmptyCollection()] [string[]] $Lines)
    $line = @($Lines | Where-Object { $_ -and ($_.Trim().StartsWith('{') -or $_.Trim().StartsWith('[')) }) | Select-Object -Last 1
    if (-not $line) { return $null }
    return ($line | ConvertFrom-Json)
}

function Get-CogesDockerMountPath {
    <# Un dossier du PC tel que docker l'attend dans -v (C:\CoGes\sauvegardes, ou /tmp/… sous Linux). #>
    param([Parameter(Mandatory)] [string] $Path)
    return [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
}

# ---------------------------------------------------------------------------- bloc A : faire une sauvegarde

function New-CogesBackup {
    <# Une sauvegarde complète : manifeste, dump, chiffrement relu, contrôles, rétention, copie
       hors du PC. Réutilisable (lot 5 : avant chaque mise à jour ; Desinstaller ; Restaurer).
       L'appelant tient le verrou. Rend la sauvegarde (Path, Name, Size, Manifest). -Trial :
       restauration d'essai du dump dans coges_verif avant de l'effacer (bloc D). #>
    param(
        [Parameter(Mandatory)] $Paths,
        [switch] $Trial,
        [switch] $SkipOffsite,
        [Nullable[datetime]] $Now = $null,
        # Sauvegarde faite avant une action : sa raison à la fin du nom (bloc 0 du lot 5).
        [AllowEmptyString()] [string] $Raison = ''
    )
    if ($null -eq $Now) { $Now = Get-Date }
    $backup = Get-CogesBackupPath $Paths
    if (-not (Test-Path -LiteralPath $backup.ClePublique)) {
        Stop-CogesStep -Probleme 'Aucune clé publique de sauvegarde sur ce PC : rien ne peut être chiffré.' `
            -QuoiFaire 'Lancez -Action Reparer -ClePublique <fichier> (ou -LecteurCle E: pour la tirer ici).'
    }
    $public = Read-CogesKeyFile -Path $backup.ClePublique -Kind Publique
    $settings = Get-CogesSetting $Paths
    $version = $settings['COGES_IMAGE_TAG']
    New-Item -ItemType Directory -Force -Path $backup.Dossier | Out-Null
    $folder = Get-CogesDockerMountPath $backup.Dossier
    $mount = $folder + ':/sortie'
    $file = $null
    $stem = 'sauvegarde-' + $Now.ToString('yyyyMMddHHmmss')
    $partialManifest = Join-Path $backup.Dossier ($stem + '.manifest.partiel')
    try {
        # 1. Lignes comptées AVANT le dump (comme backup.sh) : la base restaurée en aura au moins autant.
        $info = Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Manifeste (lignes comptées avant le dump)' `
                -Arguments @('base.py', 'manifeste', '--sortie', ('/sortie/' + (Split-Path -Leaf $partialManifest)), '--version', $version) -Mounts @($mount)).Stdout
        $previous = Get-CogesPreviousBackup -Folder $backup.Dossier -BaseId ([string]$info.base_id)
        $slugs = @($info.boutiques)
        $slug = 'sans-boutique'
        if ($slugs.Count -gt 0) { $slug = [string]$slugs[0] }
        $free = (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($backup.Dossier)))).AvailableFreeSpace
        if (-not (Test-CogesEnoughSpace -Free $free -Planned ([long]$info.base_octets))) {
            Stop-CogesStep -Probleme ('Pas assez de place sur le disque ({0:N1} Go libres, il en faut 2 de plus que la sauvegarde).' -f ($free / 1GB)) `
                -QuoiFaire 'Libérez de la place sur le disque du PC (Corbeille, Téléchargements), puis relancez. Les sauvegardes existantes sont gardées.'
        }
        $name = Get-CogesBackupName -Slug $slug -Date $Now -Version $version -Raison $Raison
        if (Test-Path -LiteralPath (Join-Path $backup.Dossier $name)) { $name = Get-CogesBackupName -Slug $slug -Date $Now -Version $version -WithSeconds -Raison $Raison }
        $file = Join-Path $backup.Dossier $name
        # 2. pg_dump dans le volume de travail, relu par pg_restore --list.
        $dump = Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-pg' -What 'Copie de la base (pg_dump)' -Arguments @('dump', $stem)
        $dumpLine = @($dump.Stdout | Where-Object { $_ -match '^dump \d+ ' }) | Select-Object -Last 1
        $dumpParts = ([string]$dumpLine).Split(' ')
        # 3. Chiffré vers le dossier du PC, puis relu et déchiffré dans le conteneur.
        $sealed = Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Chiffrement' -Mounts @($mount) `
            -Arguments @('coffre.py', 'chiffrer', '--publique', $public, ('/travail/' + $stem + '.dump'), ('/sortie/' + $name))
        $sealedLine = @($sealed.Stdout | Where-Object { $_ -match '^chiffre \d+ ' }) | Select-Object -Last 1
        $sealedParts = ([string]$sealedLine).Split(' ')
        if (-not (Test-Path -LiteralPath $file)) {
            Stop-CogesStep -Probleme 'Le fichier chiffré n''est pas dans le dossier des sauvegardes.' -QuoiFaire 'Relancez ; si l''échec revient, envoyez le journal à CoGes.'
        }
        # 4. Contrôles : taille (≥ 50 % de la dernière bonne), sha256 écrit puis relu, manifeste complet.
        $size = (Get-Item -LiteralPath $file).Length
        $previousSize = 0
        if ($previous) { $previousSize = [long]$previous.Size }
        if (-not (Test-CogesSizePlausible -Size $size -Previous $previousSize)) {
            Stop-CogesStep -Probleme ('Sauvegarde trop petite : {0:N0} octets, moins de la moitié de la précédente ({1:N0}). Base vidée ou copie coupée ?' -f $size, $previousSize) `
                -QuoiFaire 'N''effacez rien. Appelez CoGes : la sauvegarde précédente est gardée.'
        }
        $sha = Get-CogesFileSha256 $file
        if ($sealedParts.Count -ge 3 -and $sealedParts[2] -ne $sha) {
            Stop-CogesStep -Probleme 'L''empreinte du fichier chiffré a changé entre l''écriture et la relecture.' -QuoiFaire 'Vérifiez le disque du PC, puis relancez.'
        }
        [IO.File]::WriteAllText($file + '.sha256', ('{0}  {1}' -f $sha, $name) + "`n", (New-Object Text.UTF8Encoding $false))
        if ((Read-CogesSha256File ($file + '.sha256')) -ne (Get-CogesFileSha256 $file)) {
            Stop-CogesStep -Probleme 'L''empreinte relue ne correspond pas.' -QuoiFaire 'Vérifiez le disque du PC, puis relancez.'
        }
        $manifest = [IO.File]::ReadAllText($partialManifest) | ConvertFrom-Json
        $additions = [ordered]@{
            fichier = $name; octets = $size; sha256 = $sha
            pg_dump_version = $dumpParts[2]; dump_octets = [long]$dumpParts[1]; dump_sha256 = $sealedParts[3]
        }
        foreach ($key in $additions.Keys) { $manifest | Add-Member -NotePropertyName $key -NotePropertyValue $additions[$key] -Force }
        foreach ($key in @('alembic_revision', 'coges_version', 'server_version', 'pg_dump_version', 'tables', 'boutiques', 'dump_sha256')) {
            if (-not $manifest.PSObject.Properties[$key] -or $null -eq $manifest.$key -or '' -eq $manifest.$key) {
                Stop-CogesStep -Probleme ('Manifeste incomplet ({0} manque).' -f $key) -QuoiFaire 'Relancez ; si l''échec revient, envoyez le journal à CoGes.'
            }
        }
        [IO.File]::WriteAllText($file + '.manifest.json', ($manifest | ConvertTo-Json -Depth 5), (New-Object Text.UTF8Encoding $false))
        # 5. Bloc D : restauration d'essai du même dump (celui que le fichier chiffré redonne).
        if ($Trial) { Invoke-CogesTrialRestore -Paths $Paths -Stem $stem -Mount $mount -ManifestName ($name + '.manifest.json') }
    }
    catch {
        if ($file -and (Test-Path -LiteralPath $file)) {
            # Gardée pour l'enquête, jamais comptée : ni « bonne », ni dans la rétention.
            Move-Item -LiteralPath $file -Destination ($file + '.echec') -Force
            foreach ($suffix in @('.sha256', '.manifest.json')) {
                if (Test-Path -LiteralPath ($file + $suffix)) { Move-Item -LiteralPath ($file + $suffix) -Destination ($file + '.echec' + $suffix) -Force }
            }
        }
        Write-CogesBackupState -Paths $Paths -Changes @{ derniere_erreur = $Now.ToString('o'); derniere_erreur_texte = (Mask-Secrets $_.Exception.Message) }
        throw
    }
    finally {
        # Le dump en clair ne reste jamais : volume vidé même après un échec (disque plein compris).
        Clear-CogesWorkVolume -Paths $Paths
        if (Test-Path -LiteralPath $partialManifest) { Remove-Item -LiteralPath $partialManifest -Force }
    }
    Write-CogesBackupState -Paths $Paths -Changes @{ derniere_bonne = $Now.ToString('o'); derniere_bonne_fichier = $name }
    $removed = Invoke-CogesRetention -Folder $backup.Dossier -Now $Now
    $result = [pscustomobject]@{ Path = $file; Name = $name; Size = $size; Slugs = $slugs; Manifest = $manifest; Removed = $removed; Offsite = @() }
    if (-not $SkipOffsite) { $result.Offsite = @(Copy-CogesOffsite -Paths $Paths -Backup $result -Now $Now) }
    return $result
}

function Get-CogesPreviousBackup {
    <# La dernière bonne sauvegarde de la MÊME base (identifiant du serveur et de la base) : après
       une installation neuve ou une restauration, la comparaison à 50 % repart de zéro. #>
    param([Parameter(Mandatory)] [string] $Folder, [AllowEmptyString()] [string] $BaseId)
    if (-not $BaseId) { return $null }
    foreach ($item in @(Get-CogesGoodBackup $Folder)) {
        try { $manifest = [IO.File]::ReadAllText($item.Path + '.manifest.json') | ConvertFrom-Json } catch { continue }
        if ($manifest.PSObject.Properties['base_id'] -and [string]$manifest.base_id -eq $BaseId) { return $item }
    }
    return $null
}

function Clear-CogesWorkVolume {
    <# Vide le volume sauvegarde-travail. N'échoue jamais (journal seulement) : appelé dans un finally. #>
    param([Parameter(Mandatory)] $Paths)
    try {
        $result = Invoke-Docker -Arguments (Get-CogesComposeArgument -Paths $Paths -Arguments (Get-CogesToolArgument -Service 'sauvegarde-pg' -Arguments @('vider')))
        if ($result.ExitCode -ne 0) { Write-Log -Message ('volume de travail : vidage en échec (code {0})' -f $result.ExitCode) -Level ATTENTION }
    }
    catch { Write-Log -Message ('volume de travail : ' + $_.Exception.Message) -Level ATTENTION }
}

function Invoke-CogesRetention {
    <# Rétention sur le PC : seules les bonnes sauvegardes comptent ; la plus récente reste. #>
    param([Parameter(Mandatory)] [string] $Folder, [Parameter(Mandatory)] [datetime] $Now)
    $good = @(Get-CogesGoodBackup $Folder)
    $doomed = @(Select-CogesBackupToDelete -Items $good -Now $Now)
    foreach ($name in $doomed) {
        Remove-CogesBackupFile (Join-Path $Folder $name)
        Write-Log -Message ('rétention : ' + $name + ' effacée')
    }
    return $doomed
}

function Invoke-CogesTrialRestore {
    <# Bloc D : le dump restauré dans coges_verif, vérifié (contrôles de la production), supprimé. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [string] $Stem, [Parameter(Mandatory)] [string] $Mount, [Parameter(Mandatory)] [string] $ManifestName)
    $started = Get-Date
    try {
        [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Restauration d''essai (base vide)' -Arguments @('base.py', 'preparer', 'coges_verif'))
        [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-pg' -What 'Restauration d''essai (pg_restore)' -Arguments @('restaurer', $Stem, 'coges_verif'))
        $checked = Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Restauration d''essai (contrôles)' -Mounts @($Mount + ':ro') `
            -Arguments @('base.py', 'verifier', 'coges_verif', '--manifeste', ('/sortie/' + $ManifestName))
        foreach ($line in $checked.Stdout) { Write-Log -Message ('essai : ' + $line) }
        Write-CogesBackupState -Paths $Paths -Changes @{ dernier_essai = $started.ToString('o'); dernier_essai_ok = $true; dernier_essai_succes = $started.ToString('o') }
        Write-CogesLine ('  Restauration d''essai : tout est vert ({0:N0} s).' -f ((Get-Date) - $started).TotalSeconds) -Kind Ok
    }
    catch {
        Write-CogesBackupState -Paths $Paths -Changes @{ dernier_essai = $started.ToString('o'); dernier_essai_ok = $false }
        Write-CogesLine ('  Restauration d''essai en échec : ' + $_.Exception.Message) -Kind Echec
        Show-CogesToast 'La dernière sauvegarde ne se relit pas : appelez CoGes.'
        # La sauvegarde elle-même reste bonne (chiffrée et relue) : l'essai ne la déclasse pas.
    }
    finally {
        try { [void](Invoke-Docker -Arguments (Get-CogesComposeArgument -Paths $Paths -Arguments (Get-CogesToolArgument -Service 'sauvegarde-py' -Arguments @('base.py', 'supprimer', 'coges_verif')))) }
        catch { Write-Log -Message ('coges_verif : ' + $_.Exception.Message) -Level ATTENTION }
    }
}

# ---------------------------------------------------------------------------- bloc B : copie hors du PC

function Get-CogesOffsiteRoot {
    <# Les racines candidates : disques prêts, hors disque de Windows et hors C:\CoGes.
       Sous Linux (essais), la variable COGES_DISQUES_ESSAI donne des dossiers. #>
    param([Parameter(Mandatory)] $Paths)
    if ($env:COGES_DISQUES_ESSAI) { return @($env:COGES_DISQUES_ESSAI -split [IO.Path]::PathSeparator | Where-Object { $_ }) }
    if (-not (Test-CogesWindows)) { return @() }
    return @([IO.DriveInfo]::GetDrives() | Where-Object { $_.IsReady -and $_.DriveType -in @('Removable', 'Fixed') } |
            ForEach-Object { $_.RootDirectory.FullName } | Where-Object { Test-CogesExternalTarget -Path $_ -Racine $Paths.Racine })
}

function Copy-CogesOffsite {
    <# Copie la sauvegarde sur chaque disque portant le repère de CETTE boutique, puis relit
       (sha256). Garde les 10 dernières sur le disque ; la plus ancienne n'est effacée
       qu'après la copie relue. Sans repère : rien n'est écrit. N'échoue jamais. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] $Backup, [Parameter(Mandatory)] [datetime] $Now)
    $done = @()
    foreach ($root in (Get-CogesOffsiteRoot $Paths)) {
        try {
            $marker = Join-Path $root $script:CogesDiskMarker
            $text = $null
            if (Test-Path -LiteralPath $marker -PathType Leaf) { $text = [IO.File]::ReadAllText($marker) }
            $state = Get-CogesDiskMarkerState -MarkerText $text -Slugs $Backup.Slugs
            if ($state -ne 'ok') {
                if ($state -eq 'autre') { Write-Log -Message ('disque {0} : repère d''une autre boutique, rien n''est écrit' -f $root) }
                continue
            }
            $target = Join-Path $root $script:CogesOffsiteFolder
            New-Item -ItemType Directory -Force -Path $target | Out-Null
            $free = (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($target)))).AvailableFreeSpace
            if ($free -lt ($Backup.Size + 64MB)) {
                Write-CogesLine ('  Disque {0} : pas assez de place pour la copie.' -f $root) -Kind Attention
                continue
            }
            $copy = Join-Path $target $Backup.Name
            foreach ($suffix in @('.sha256', '.manifest.json', '')) {
                Copy-Item -LiteralPath ($Backup.Path + $suffix) -Destination ($copy + $suffix + '.partiel') -Force
            }
            if ((Get-CogesFileSha256 ($copy + '.partiel')) -ne (Read-CogesSha256File ($Backup.Path + '.sha256'))) {
                foreach ($suffix in @('.sha256', '.manifest.json', '')) { Remove-Item -LiteralPath ($copy + $suffix + '.partiel') -Force -ErrorAction SilentlyContinue }
                Write-CogesLine ('  Disque {0} : la copie relue ne correspond pas, elle est retirée.' -f $root) -Kind Attention
                continue
            }
            foreach ($suffix in @('.sha256', '.manifest.json', '')) { Move-Item -LiteralPath ($copy + $suffix + '.partiel') -Destination ($copy + $suffix) -Force }
            $all = @(Get-CogesGoodBackup $target)
            foreach ($old in ($all | Select-Object -Skip $script:CogesKeepOffsite)) { Remove-CogesBackupFile $old.Path }
            Write-CogesBackupState -Paths $Paths -Changes @{ derniere_copie_hors_pc = $Now.ToString('o'); derniere_copie_disque = $root }
            Write-CogesLine ('  Copie hors du PC : {0} (relue).' -f $copy) -Kind Ok
            $done += $copy
        }
        catch {
            Write-CogesLine ('  Disque {0} : copie impossible ({1}).' -f $root, $_.Exception.Message) -Kind Attention
        }
    }
    return $done
}

# ---------------------------------------------------------------------------- bloc C : prévenir

function Show-CogesToast {
    <# Notification Windows (API WinRT de Windows PowerShell 5.1). Désactivable ; un échec
       n'est jamais celui de la sauvegarde : journal seulement. #>
    param([Parameter(Mandatory)] [string] $Text)
    Write-Log -Message ('notification : ' + $Text) -Level ATTENTION
    if (-not $script:CogesToastEnabled -or $script:CogesState.Simulation -or -not (Test-CogesWindows)) { return $false }
    try {
        $null = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
        $null = [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]
        $escaped = [Security.SecurityElement]::Escape($Text)
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml(('<toast><visual><binding template="ToastGeneric"><text>CoGes</text><text>{0}</text></binding></visual></toast>' -f $escaped))
        # L'identifiant d'application de Windows PowerShell : aucun raccourci à poser.
        $appId = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show((New-Object Windows.UI.Notifications.ToastNotification $xml))
        return $true
    }
    catch {
        Write-Log -Message ('notification impossible : ' + $_.Exception.Message) -Level ATTENTION
        return $false
    }
}

function Get-CogesBackupSummary {
    <# Ce que dit Etat, et ce que regardent les alertes. #>
    param([Parameter(Mandatory)] $Paths)
    $backup = Get-CogesBackupPath $Paths
    $good = @(Get-CogesGoodBackup $backup.Dossier)
    $state = Read-CogesBackupState $Paths
    $free = [long]::MaxValue
    try { $free = (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Paths.Racine)))).AvailableFreeSpace } catch { Write-Verbose 'disque illisible' }
    $trialOk = $null
    if ($state.ContainsKey('dernier_essai_ok')) { $trialOk = [bool]$state['dernier_essai_ok'] }
    $last = $null
    if ($good.Count -gt 0) { $last = $good[0] }
    return [pscustomobject]@{
        Last          = $last
        LastGood      = $(if ($last) { $last.Date } else { $null })
        Count         = $good.Count
        Failed        = @(Get-ChildItem -LiteralPath $backup.Dossier -Filter '*.echec' -File -ErrorAction SilentlyContinue).Count
        LastOffsite   = ConvertTo-CogesStateDate $state['derniere_copie_hors_pc']
        OffsiteDisk   = $state['derniere_copie_disque']
        LastTrial     = ConvertTo-CogesStateDate $state['dernier_essai']
        LastTrialOk   = $trialOk
        LastTrialGood = ConvertTo-CogesStateDate $state['dernier_essai_succes']
        Free          = $free
        HasKey        = (Test-Path -LiteralPath $backup.ClePublique)
    }
}

# ---------------------------------------------------------------------------- actions du lot 4

function Invoke-CogesBackupAction {
    <# -Action Sauvegarder : une sauvegarde à la main, CoGes ouvert pendant ce temps. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans le bloc de l''étape (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if (-not $script:CogesState.Simulation -and -not (Test-Path -LiteralPath $Paths.EnvFile)) {
        Stop-CogesStep -Probleme ('CoGes n''est pas installé ici ({0} absent).' -f $Paths.EnvFile) -QuoiFaire 'Lancez -Action Installer.'
    }
    $lock = Enter-CogesLock -Paths $Paths -Action 'Sauvegarder'
    try {
        Invoke-CogesStep -Title 'Sauvegarde de la base (CoGes reste ouvert)' -Action {
            $summary = Get-CogesBackupSummary $Paths
            $trial = [bool]$Options.Essai -or (Test-CogesTrialDue -Now (Get-Date) -LastSuccess $summary.LastTrialGood)
            try { $made = New-CogesBackup -Paths $Paths -Trial:$trial }
            catch {
                [void](Send-CogesPing -Paths $Paths -Signal 'sauvegarde' -Failure -Reason (Get-CogesFailureCode $_.Exception.Message))
                throw
            }
            Write-CogesLine ('  {0} ({1:N1} Mo), chiffrée et relue.' -f $made.Path, ($made.Size / 1MB)) -Kind Ok
            if (@($made.Offsite).Count -eq 0) { Write-CogesLine '  Aucune clé CoGes branchée : pas de copie hors du PC cette fois.' -Kind Attention }
            if ($trial -and -not (Get-CogesBackupSummary $Paths).LastTrialOk) { [void](Send-CogesPing -Paths $Paths -Signal 'sauvegarde' -Failure -Reason 'essai-rate') }
            else { [void](Send-CogesPing -Paths $Paths -Signal 'sauvegarde') }
        }
    }
    finally { Exit-CogesLock $lock }
    if ($script:CogesState.Simulation) { Write-CogesLine 'Simulation terminée : rien n''a été écrit ni lancé.' -Kind Ok }
}

function Invoke-CogesScheduledBackup {
    <# La tâche « CoGes - sauvegarde » : aux heures prévues et à l'ouverture de session.
       Sans question ni fenêtre ; journal sauvegarde-AAAAMMJJ.log ; jamais d'exception. #>
    param([Parameter(Mandatory)] [string] $Racine, [int] $LockWaitSeconds = 1800, [Nullable[datetime]] $Now = $null)
    if ($null -eq $Now) { $Now = Get-Date }
    $paths = Get-CogesPath $Racine
    $script:CogesState.NonInteractif = $true
    New-Item -ItemType Directory -Force -Path $paths.Journaux | Out-Null
    $script:CogesState.LogPath = Join-Path $paths.Journaux ('sauvegarde-{0}.log' -f $Now.ToString('yyyyMMdd'))
    if (-not (Test-Path -LiteralPath $paths.EnvFile)) { Write-Log -Message 'CoGes n''est pas installé : rien à faire.'; return 0 }
    [void](Get-CogesSetting $paths)
    # Lot 6 : journaux bornés (60 jours, 200 Mo), à chaque passage.
    [void](Invoke-CogesLogRotation -Folder $paths.Journaux -Now $Now)
    $code = 0
    $lock = $null
    # Ce que dira le ping « sauvegarde » : $null (rien fait), ok, ou un code d'échec.
    $signal = $null
    try {
        $summary = Get-CogesBackupSummary $paths
        $due = Test-CogesBackupDue -Now $Now -LastGood $summary.LastGood
        $trial = Test-CogesTrialDue -Now $Now -LastSuccess $summary.LastTrialGood
        if (-not $due -and -not $trial) { Write-Log -Message 'Rien à faire : la dernière sauvegarde est récente.' }
        elseif ((Invoke-Docker -Arguments @('version', '--format', '{{.Server.Os}}')).ExitCode -ne 0) {
            Write-Log -Message 'Docker ne répond pas : pas de sauvegarde cette fois.' -Level ATTENTION
            $signal = 'docker-arrete'
        }
        else {
            $lock = Enter-CogesLock -Paths $paths -Action 'Sauvegarde planifiée' -WaitSeconds $LockWaitSeconds -IntervalSeconds 30
            $made = New-CogesBackup -Paths $paths -Trial:$trial
            Write-Log -Message ('sauvegarde bonne : {0}' -f $made.Name) -Level OK
            $signal = 'aucune'
            if ($trial -and -not (Get-CogesBackupSummary $paths).LastTrialOk) { $signal = 'essai-rate' }
        }
    }
    catch {
        Write-Log -Message ('sauvegarde en échec : ' + $_.Exception.Message) -Level ECHEC
        $signal = Get-CogesFailureCode $_.Exception.Message
        $code = 1
    }
    finally { Exit-CogesLock $lock }
    # Lot 6 : ce passage envoie « vie » (un PC jamais éteint ne rouvre pas de session), puis
    # « sauvegarde » s'il a sauvegardé ou dû le faire. Jamais bloquant.
    [void](Send-CogesPing -Paths $paths -Signal 'vie')
    if ($signal -eq 'aucune') { [void](Send-CogesPing -Paths $paths -Signal 'sauvegarde') }
    elseif ($signal) { [void](Send-CogesPing -Paths $paths -Signal 'sauvegarde' -Failure -Reason $signal) }
    try {
        $summary = Get-CogesBackupSummary $paths
        foreach ($alert in (Get-CogesBackupAlert -Now (Get-Date) -LastGood $summary.LastGood -LastOffsite $summary.LastOffsite -FreeBytes $summary.Free -TrialOk $summary.LastTrialOk)) {
            [void](Show-CogesToast $alert.Texte)
        }
    }
    catch { Write-Log -Message ('alertes : ' + $_.Exception.Message) -Level ATTENTION }
    return $code
}

function Install-CogesBackupTask {
    <# La tâche « CoGes - sauvegarde » : 13 h 00, 20 h 30 et à l'ouverture de session, comme
       « CoGes - démarrage » (utilisateur courant, sans élévation, fenêtre cachée), et
       StartWhenAvailable : une heure manquée (PC éteint) se rattrape au démarrage. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans le bloc de l''étape (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths)
    Invoke-CogesStep -Title ('Tâche planifiée « {0} » (13 h 00, 20 h 30 et au démarrage)' -f $script:CogesBackupTaskName) -Action {
        $launcher = Join-Path $Paths.Programme 'windows\sauvegarde.ps1'
        $argument = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Racine "{1}"' -f $launcher, $Paths.Racine
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $triggers = @()
        foreach ($slot in $script:CogesBackupSlots) { $triggers += New-ScheduledTaskTrigger -Daily -At $slot }
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $user
        # Laisse Docker Desktop démarrer d'abord.
        $logon.Delay = 'PT5M'
        $triggers += $logon
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
        Register-ScheduledTask -TaskName $script:CogesBackupTaskName -Action $action -Trigger $triggers -Principal $principal -Settings $settings -Force | Out-Null
    }
}

function Remove-CogesBackupTask {
    Invoke-CogesStep -Title ('Tâche planifiée « {0} » retirée' -f $script:CogesBackupTaskName) -Action {
        if (Get-ScheduledTask -TaskName $script:CogesBackupTaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:CogesBackupTaskName -Confirm:$false
        }
    }
}

function Invoke-CogesPrepareDisk {
    <# -Action PreparerDisque -Lecteur E: (technicien) : repère, place, première copie. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if (-not $Options.Lecteur) {
        Stop-CogesStep -Probleme 'Il manque le disque à préparer.' -QuoiFaire 'Relancez avec -Lecteur E: (la lettre de la clé USB ou du disque externe).'
    }
    $root = ConvertTo-CogesDriveRoot $Options.Lecteur
    $slug = Read-CogesAnswer -Question 'Code de la boutique' -Parameter 'CodeBoutique' -Value $Options.CodeBoutique `
        -Validate { param($v) Test-CogesSlug $v } -Rule 'minuscules, chiffres et tirets entre deux mots.'
    if ($script:CogesState.Simulation) {
        Write-CogesLine ('[simulation] Repère {0} écrit sur {1}, place vérifiée, première copie' -f $script:CogesDiskMarker, $root)
        return
    }
    if (-not (Test-CogesExternalTarget -Path $root -Racine $Paths.Racine)) {
        Stop-CogesStep -Probleme ('{0} n''est pas un disque branché hors du PC (ni C:, ni le dossier de CoGes).' -f $Options.Lecteur) `
            -QuoiFaire 'Branchez la clé USB ou le disque externe, puis donnez sa lettre (-Lecteur E:).'
    }
    $marker = Join-Path $root $script:CogesDiskMarker
    if (Test-Path -LiteralPath $marker) {
        $state = Get-CogesDiskMarkerState -MarkerText ([IO.File]::ReadAllText($marker)) -Slugs @($slug)
        if ($state -eq 'autre') {
            Stop-CogesStep -Probleme ('Ce disque est déjà préparé pour une autre boutique ({0}).' -f ([IO.File]::ReadAllText($marker).Trim())) `
                -QuoiFaire 'Utilisez un autre disque : une clé ne sert qu''à une boutique.'
        }
    }
    $lock = Enter-CogesLock -Paths $Paths -Action 'PreparerDisque'
    try {
        $backup = Get-CogesBackupPath $Paths
        $latest = @(Get-CogesGoodBackup $backup.Dossier) | Select-Object -First 1
        $need = 1GB
        if ($latest) { $need = [Math]::Max($need, 2 * [long]$latest.Size * $script:CogesKeepOffsite) }
        $free = (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($root)))).AvailableFreeSpace
        if ($free -lt $need) {
            Stop-CogesStep -Probleme ('Pas assez de place sur {0} ({1:N1} Go libres, {2:N1} Go conseillés pour 10 sauvegardes).' -f $root, ($free / 1GB), ($need / 1GB)) `
                -QuoiFaire 'Prenez une clé ou un disque plus grand.'
        }
        [IO.File]::WriteAllText($marker, $slug + "`n", (New-Object Text.UTF8Encoding $false))
        Write-CogesLine ('  Repère {0} écrit ({1}).' -f $marker, $slug) -Kind Ok
        $previous = $env:COGES_DISQUES_ESSAI
        if (-not (Test-CogesWindows)) { $env:COGES_DISQUES_ESSAI = $root }
        try {
            if ($latest -and (@($latest.Slug) -contains $slug)) {
                $copies = @(Copy-CogesOffsite -Paths $Paths -Backup ([pscustomobject]@{ Path = $latest.Path; Name = $latest.Name; Size = $latest.Size; Slugs = @($latest.Slug) }) -Now (Get-Date))
            }
            else {
                $copies = @((New-CogesBackup -Paths $Paths).Offsite)
            }
        }
        finally { $env:COGES_DISQUES_ESSAI = $previous }
        if ($copies.Count -eq 0) { Stop-CogesStep -Probleme 'La première copie n''a pas pu être faite.' -QuoiFaire 'Lisez les lignes ci-dessus, puis relancez.' }
        Write-CogesLine 'Disque prêt : à chaque sauvegarde où il est branché, CoGes y copie la dernière.' -Kind Ok
    }
    finally { Exit-CogesLock $lock }
}

# ---------------------------------------------------------------------------- bloc E : restaurer

function Test-CogesRevisionKnown {
    <# La révision de la sauvegarde doit être connue du programme installé : refus si elle est plus récente. #>
    param([Parameter(Mandatory)] [string] $Revision, [AllowEmptyCollection()] [string[]] $Known = @())
    return (@($Known) -ccontains $Revision)
}

function Read-CogesBackupFile {
    <# Étape 1 : fichier lisible, sha256 bon, manifeste lu. Rien n'est changé. #>
    param([Parameter(Mandatory)] [string] $Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Stop-CogesStep -Probleme ('Sauvegarde introuvable : {0}' -f $Path) -QuoiFaire 'Vérifiez le chemin (clé USB branchée ?), puis relancez. Rien n''a changé.'
    }
    $name = Split-Path -Leaf $Path
    if ($null -eq (ConvertFrom-CogesBackupName $name)) {
        Stop-CogesStep -Probleme ('{0} n''a pas le nom d''une sauvegarde CoGes.' -f $name) -QuoiFaire 'Donnez un fichier coges-….coges, sans le renommer. Rien n''a changé.'
    }
    foreach ($suffix in @('.sha256', '.manifest.json')) {
        if (-not (Test-Path -LiteralPath ($Path + $suffix))) {
            Stop-CogesStep -Probleme ('{0} manque à côté de la sauvegarde.' -f ($name + $suffix)) -QuoiFaire 'Copiez les trois fichiers ensemble (.coges, .sha256, .manifest.json). Rien n''a changé.'
        }
    }
    if ((Get-CogesFileSha256 $Path) -ne (Read-CogesSha256File ($Path + '.sha256'))) {
        Stop-CogesStep -Probleme 'Empreinte (sha256) différente : le fichier est abîmé ou modifié.' -QuoiFaire 'Prenez une autre sauvegarde (le PC en garde plusieurs, la clé USB aussi). Rien n''a changé.'
    }
    try { $manifest = [IO.File]::ReadAllText($Path + '.manifest.json') | ConvertFrom-Json }
    catch { Stop-CogesStep -Probleme 'Manifeste illisible.' -QuoiFaire 'Prenez une autre sauvegarde. Rien n''a changé.' }
    $declared = Get-CogesManifestValue $manifest 'sha256'
    if (-not (Get-CogesManifestValue $manifest 'alembic_revision') -or -not (Get-CogesManifestValue $manifest 'coges_version') -or ($declared -and $declared -ne (Read-CogesSha256File ($Path + '.sha256')))) {
        Stop-CogesStep -Probleme 'Manifeste incomplet ou d''une autre sauvegarde.' -QuoiFaire 'Prenez une autre sauvegarde. Rien n''a changé.'
    }
    return $manifest
}

function Get-CogesManifestValue {
    <# Un champ du manifeste, ou $default s'il manque (mode strict : jamais d'exception). #>
    param([Parameter(Mandatory)] $Manifest, [Parameter(Mandatory)] [string] $Name, $Default = $null)
    if ($null -ne $Manifest -and $Manifest.PSObject.Properties[$Name]) { return $Manifest.$Name }
    return $Default
}

function Get-CogesRestoreCandidate {
    <# Les bonnes sauvegardes du PC et des disques CoGes branchés (dossier CoGes d'un disque qui
       porte le repère), la plus récente d'abord. Chacune : Path, Name, Date, Origine, Version,
       Ventes (nombre ou $null), Societes, Raison. Une même sauvegarde vue deux fois : celle du PC. #>
    param([Parameter(Mandatory)] $Paths)
    $sources = @(@{ Folder = (Get-CogesBackupPath $Paths).Dossier; Origine = 'PC' })
    foreach ($root in (Get-CogesOffsiteRoot $Paths)) {
        if (Test-Path -LiteralPath (Join-Path $root $script:CogesDiskMarker) -PathType Leaf) {
            $sources += @{ Folder = (Join-Path $root $script:CogesOffsiteFolder); Origine = ('clé ' + $root) }
        }
    }
    $seen = @{}
    $found = foreach ($source in $sources) {
        foreach ($item in @(Get-CogesGoodBackup $source.Folder)) {
            if ($seen.ContainsKey($item.Name)) { continue }
            $seen[$item.Name] = $true
            $manifest = $null
            try { $manifest = [IO.File]::ReadAllText($item.Path + '.manifest.json') | ConvertFrom-Json } catch { Write-Verbose 'manifeste illisible' }
            $sales = Get-CogesManifestValue (Get-CogesManifestValue $manifest 'tables') 'sales'
            $companies = Get-CogesManifestValue $manifest 'companies'
            if ($null -eq $companies) { $companies = @(Get-CogesManifestValue $manifest 'boutiques' @()).Count }
            [pscustomobject]@{
                Path = $item.Path; Name = $item.Name; Date = $item.Date; Origine = $source.Origine; Raison = $item.Raison
                Version = (Get-CogesManifestValue $manifest 'coges_version' $item.Version)
                Ventes = $(if ($null -ne $sales) { [long]$sales } else { $null }); Societes = [int]$companies
            }
        }
    }
    return @($found | Sort-Object -Property @{ Expression = 'Date'; Descending = $true }, @{ Expression = 'Name'; Descending = $true })
}

function Format-CogesRestoreCandidate {
    <# Une ligne de la liste : « 1. 21/11/2026 13:00  v0.3.0  12 ventes, 1 société  PC  (avant mise à jour) ». #>
    param([Parameter(Mandatory)] $Candidate, [Parameter(Mandatory)] [int] $Number)
    $reasons = @{ 'avant-effacement' = 'avant effacement'; 'avant-restauration' = 'avant restauration'; 'avant-maj' = 'avant mise à jour'
        'avant-retour' = 'avant retour à la version précédente'; 'installation' = 'installation : base neuve' }
    $sales = 'ventes : ?'
    if ($null -ne $Candidate.Ventes) { $sales = '{0} vente(s)' -f $Candidate.Ventes }
    $line = '{0,3}. {1}  {2,-8}  {3}, {4} société(s)  {5}' -f $Number, $Candidate.Date.ToString('dd/MM/yyyy HH:mm'), $Candidate.Version, $sales, $Candidate.Societes, $Candidate.Origine
    if ($Candidate.Raison) { $line += '  (' + $reasons[$Candidate.Raison] + ')' }
    return $line
}

function Select-CogesRestoreFile {
    <# Restaurer sans -Fichier : la liste numérotée, puis le numéro choisi. #>
    param([Parameter(Mandatory)] $Paths)
    $candidates = @(Get-CogesRestoreCandidate $Paths)
    if ($candidates.Count -eq 0) {
        Stop-CogesStep -Probleme 'Aucune sauvegarde sur ce PC ni sur une clé CoGes branchée.' `
            -QuoiFaire 'Branchez la clé CoGes du client (ou donnez le fichier : -Fichier <chemin du .coges>). Rien n''a changé.'
    }
    Write-CogesLine 'Sauvegardes trouvées (la plus récente en haut)' -Kind Titre
    for ($index = 0; $index -lt $candidates.Count; $index++) { Write-CogesLine (Format-CogesRestoreCandidate -Candidate $candidates[$index] -Number ($index + 1)) }
    $count = $candidates.Count
    $answer = Read-CogesAnswer -Question 'Numéro de la sauvegarde à restaurer' -Parameter 'Fichier' -Value '' `
        -Validate { param($v) ($v -match '^\s*\d+\s*$') -and [int]$v -ge 1 -and [int]$v -le $count } -Rule ('un numéro de 1 à {0}.' -f $count)
    return $candidates[[int]$answer - 1].Path
}

function Get-CogesRestoreLoss {
    <# Avertissement renforcé : la sauvegarde n'a aucune vente (ou on ne sait pas), ou moins que
       la base actuelle. Rend le texte de l'avertissement, ou $null. #>
    param([AllowNull()] $BackupSales, [long] $CurrentSales = 0)
    if ($null -eq $BackupSales -or '' -eq $BackupSales -or '?' -eq $BackupSales) {
        return 'Cette sauvegarde ne dit pas combien elle contient de ventes.'
    }
    $backup = [long]$BackupSales
    if ($backup -eq 0) {
        $text = 'Cette sauvegarde ne contient AUCUNE vente (base neuve ou vide ?).'
        if ($CurrentSales -gt 0) { $text += (' Les {0} vente(s) de ce PC seraient perdues.' -f $CurrentSales) }
        return $text
    }
    if ($backup -lt $CurrentSales) {
        return ('Cette sauvegarde a {0} vente(s), la base de ce PC en a {1} : {2} vente(s) seraient perdues.' -f $backup, $CurrentSales, ($CurrentSales - $backup))
    }
    return $null
}

function Restore-CogesBackup {
    <# -Action Restaurer -Fichier <chemin> -Cle <chemin> : chaque étape s'arrête au premier
       problème sans avoir rien changé ; après la bascule, un échec ramène l'ancienne base. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if (-not $Options.Cle) { Stop-CogesStep -Probleme 'Il manque la clé privée.' -QuoiFaire 'Relancez avec -Cle <fichier de la clé privée de ce client> (gestionnaire de mots de passe de CoGes).' }
    if ($script:CogesState.Simulation) {
        foreach ($step in @('0. sans -Fichier : liste des sauvegardes du PC et de la clé CoGes, choix par numéro', '1. empreinte et manifeste, puis RESTAURER (RESTAURER-QUAND-MEME si des ventes seraient perdues)', '2. version', '3. sauvegarde de la base actuelle', '4. restauration à côté (coges_restauration) et contrôles',
                '5. arrêt de l''application, bascule (ancienne base gardée)', '6. migrate si besoin, démarrage, licence, page d''accueil', '7. retour automatique en cas d''échec')) {
            Write-CogesLine ('[simulation] ' + $step)
        }
        return
    }
    if (-not (Test-Path -LiteralPath $Paths.EnvFile)) {
        Stop-CogesStep -Probleme 'CoGes n''est pas installé sur ce PC.' -QuoiFaire 'Lancez d''abord -Action Installer (PC neuf), puis -Action Restaurer.'
    }
    $settings = Get-CogesSetting $Paths
    $backup = Get-CogesBackupPath $Paths
    $lock = Enter-CogesLock -Paths $Paths -Action 'Restaurer'
    try {
        # 0. Sans -Fichier : la liste du PC et de la clé CoGes, choisie par numéro (bloc 0 du lot 5).
        $chosen = $Options.Fichier
        if (-not $chosen) {
            if ($script:CogesState.NonInteractif) {
                Stop-CogesStep -Probleme 'Il manque la sauvegarde à restaurer.' -QuoiFaire 'En mode -NonInteractif, passez -Fichier <chemin du .coges>. Rien n''a changé.'
            }
            $chosen = Select-CogesRestoreFile $Paths
        }
        # 1. Fichier, empreinte, manifeste, clé : rien n'est changé.
        $source = [IO.Path]::GetFullPath($chosen)
        $manifest = Read-CogesBackupFile $source
        $key = Read-CogesKeyFile -Path $Options.Cle -Kind Privee
        $sales = Get-CogesManifestValue (Get-CogesManifestValue $manifest 'tables') 'sales' '?'
        $boutiques = @(Get-CogesManifestValue $manifest 'boutiques' @())
        Write-CogesLine 'Sauvegarde à restaurer' -Kind Titre
        Write-CogesLine ('  Boutique   : {0}' -f ($boutiques -join ', '))
        Write-CogesLine ('  Faite le   : {0}' -f (Get-CogesManifestValue $manifest 'cree_le' '?'))
        Write-CogesLine ('  Version    : {0} (révision {1})' -f $manifest.coges_version, $manifest.alembic_revision)
        Write-CogesLine ('  Ventes     : {0}' -f $sales)
        Write-CogesLine 'La base actuelle sera sauvegardée, puis GARDÉE à côté (rien n''est effacé).' -Kind Attention
        $current = Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Lecture de la base actuelle' -Arguments @('base.py', 'etat')).Stdout
        $currentSales = [long](Get-CogesManifestValue $current 'ventes' 0)
        Write-CogesLine ('  Ventes sur ce PC aujourd''hui : {0}' -f $currentSales)
        $loss = Get-CogesRestoreLoss -BackupSales $sales -CurrentSales $currentSales
        if ($loss) {
            Write-CogesLine ('ATTENTION : ' + $loss) -Kind Echec
            Write-CogesLine 'Vérifiez la date et le nombre de ventes : la plus récente n''est pas toujours la bonne (une installation neuve fait aussi une sauvegarde).' -Kind Echec
            Confirm-CogesWord -Word 'RESTAURER-QUAND-MEME' -Prompt 'Restaurer quand même cette sauvegarde ?' -Given $Options.RestaurerQuandMeme -Parameter 'RestaurerQuandMeme'
        }
        else {
            Confirm-CogesWord -Word 'RESTAURER' -Prompt 'Remplacer les données de ce PC par cette sauvegarde ?' -Given $Options.ConfirmerRestauration -Parameter 'ConfirmerRestauration'
        }

        # 2. Version : la révision doit être connue du programme installé.
        $revisions = Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Révisions du programme installé' -Arguments @('base.py', 'revisions')).Stdout
        if (-not (Test-CogesRevisionKnown -Revision ([string]$manifest.alembic_revision) -Known @($revisions.connues))) {
            Stop-CogesStep -Probleme ('Cette sauvegarde vient de CoGes {0}, plus récent que la version installée ({1}).' -f $manifest.coges_version, $settings['COGES_IMAGE_TAG']) `
                -QuoiFaire ('Installez d''abord la version {0} (-Action Reparer -Version {0}), puis relancez la restauration. Rien n''a changé.' -f $manifest.coges_version)
        }
        $migrate = ([string]$manifest.alembic_revision -ne [string]$revisions.tete)
        Write-CogesLine ('  Version : révision {0} connue de {1}{2}.' -f $manifest.alembic_revision, $settings['COGES_IMAGE_TAG'], $(if ($migrate) { ', la base sera mise à jour après' } else { '' })) -Kind Ok

        # 3. La base actuelle d'abord, si elle existe et n'est pas vide (lue à l'étape 1).
        if ($current.existe -and [int]$current.societes -gt 0) {
            Write-CogesLine '» Sauvegarde de la base actuelle avant tout changement' -Kind Titre
            $before = New-CogesBackup -Paths $Paths -Raison 'avant-restauration'
            Write-CogesLine ('  {0}' -f $before.Path) -Kind Ok
        }

        # 4. À côté : déchiffrée dans le conteneur (clé par l'entrée standard), restaurée dans
        #    coges_restauration, vérifiée. Le fichier chiffré est copié dans le dossier des
        #    sauvegardes (aucun montage d'un disque amovible) ; il reste chiffré.
        New-Item -ItemType Directory -Force -Path $backup.Restauration | Out-Null
        $name = Split-Path -Leaf $source
        $local = Join-Path $backup.Restauration $name
        if ($source -ne $local) {
            foreach ($suffix in @('.sha256', '.manifest.json', '')) { Copy-Item -LiteralPath ($source + $suffix) -Destination ($local + $suffix) -Force }
            if ((Get-CogesFileSha256 $local) -ne (Read-CogesSha256File ($local + '.sha256'))) {
                Stop-CogesStep -Probleme 'La copie de la sauvegarde sur le PC ne correspond pas.' -QuoiFaire 'Vérifiez la clé USB et le disque, puis relancez. Rien n''a changé.'
            }
        }
        $mount = (Get-CogesDockerMountPath $backup.Restauration) + ':/entree:ro'
        try {
            Invoke-CogesStep -Title 'Déchiffrement (dans le conteneur, la clé privée n''est pas copiée)' -Action {
                [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Déchiffrement' -Mounts @($mount) -InputText $key `
                        -Arguments @('coffre.py', 'dechiffrer', ('/entree/' + $name), '/travail/restauration.dump'))
            }
            $key = $null
            Invoke-CogesStep -Title 'Restauration à côté, dans coges_restauration' -Action {
                [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Base de restauration' -Arguments @('base.py', 'preparer', 'coges_restauration'))
                [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-pg' -What 'Restauration (pg_restore)' -Arguments @('restaurer', 'restauration', 'coges_restauration'))
            }
            Invoke-CogesStep -Title 'Contrôles de la base restaurée (ceux de la production)' -Action {
                $checked = Invoke-Docker -Arguments (Get-CogesComposeArgument -Paths $Paths -Arguments (Get-CogesToolArgument -Service 'sauvegarde-py' -Mounts @($mount) `
                            -Arguments @('base.py', 'verifier', 'coges_restauration', '--manifeste', ('/entree/' + $name + '.manifest.json'))))
                foreach ($line in $checked.Stdout) { if ($line -notmatch '^\s*Container ') { Write-CogesLine ('  ' + $line) } }
                if ($checked.ExitCode -ne 0) {
                    [void](Invoke-Docker -Arguments (Get-CogesComposeArgument -Paths $Paths -Arguments (Get-CogesToolArgument -Service 'sauvegarde-py' -Arguments @('base.py', 'supprimer', 'coges_restauration'))))
                    Stop-CogesStep -Probleme 'La base restaurée ne passe pas les contrôles (lignes ci-dessus).' -QuoiFaire 'Prenez une autre sauvegarde, ou envoyez le journal à CoGes. Rien n''a changé : la base actuelle est en place.'
                }
            }
        }
        finally { $key = $null; Clear-CogesWorkVolume -Paths $Paths }

        # 5. Bascule : application arrêtée (Caddy montre la page de maintenance), renommage.
        $stamp = (Get-Date).ToString('yyyyMMdd_HHmm')
        [void](Invoke-CogesCompose -Paths $Paths -Arguments @('stop', 'front', 'api', 'worker', 'beat', 'relay'))
        $switched = Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Bascule' -Arguments @('base.py', 'bascule', $stamp)).Stdout
        $old = $switched.ancienne
        Write-CogesLine ('  Bascule faite ; ancienne base gardée : {0}.' -f $(if ($old) { $old } else { 'aucune' })) -Kind Ok
        $slug = ''
        if ($boutiques.Count -gt 0) { $slug = [string]$boutiques[0] }
        try {
            # 6. migrate si besoin, démarrage, licence, page d'accueil.
            if ($env:COGES_ESSAI_ECHEC_APRES_BASCULE -eq '1') { throw 'échec simulé après la bascule (essai du retour automatique)' }
            if ($migrate) {
                $result = Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'run', '--rm', '-T', 'migrate')
                if ($result.ExitCode -ne 0) { throw 'la mise à jour de la base restaurée (migrate) a échoué' }
            }
            $up = Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans')
            if ($up.ExitCode -ne 0) { throw 'le démarrage a échoué' }
            Wait-CogesHealthy -Paths $Paths
            if ($slug) {
                $status = Get-CogesLicenseStatus -Paths $Paths -Slug $slug
                if (-not (Test-CogesLicenseActive $status.Output)) { throw ('la licence de {0} ne se relit pas « actif, sans fin »' -f $slug) }
                Write-CogesLine ('  Licence de {0} revenue avec la base : actif, sans fin.' -f $slug) -Kind Ok
            }
            Test-CogesSite -Url $settings['COGES_PUBLIC_URL']
        }
        catch {
            # 7. Retour automatique à l'ancienne base.
            $reason = $_.Exception.Message
            if (-not $old) {
                Stop-CogesStep -Probleme ('La restauration a échoué après la bascule ({0}), et ce PC n''avait pas d''ancienne base.' -f $reason) `
                    -QuoiFaire 'Relancez -Action Reparer, puis envoyez le journal à CoGes.'
            }
            Write-CogesLine ('Échec après la bascule ({0}) : retour à l''ancienne base.' -f $reason) -Kind Echec
            [void](Invoke-CogesCompose -Paths $Paths -Arguments @('stop', 'front', 'api', 'worker', 'beat', 'relay'))
            [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Retour à l''ancienne base' -Arguments @('base.py', 'retour', $stamp))
            [void](Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans'))
            Wait-CogesHealthy -Paths $Paths
            Stop-CogesStep -Probleme ('La restauration a échoué après la bascule ({0}). L''ancienne base est remise en place : CoGes fonctionne comme avant.' -f $reason) `
                -QuoiFaire ('La base restaurée est gardée sous coges_echec_{0} pour l''enquête. Envoyez le journal à CoGes.' -f $stamp)
        }
        Write-CogesBackupState -Paths $Paths -Changes @{ derniere_restauration = (Get-Date).ToString('o'); derniere_restauration_fichier = $name; ancienne_base = $old }
        Write-CogesLine ''
        Write-CogesLine ('Restauration terminée : {0} ({1}).' -f $settings['COGES_PUBLIC_URL'], $slug) -Kind Ok
        if ($old) { Write-CogesLine ('L''ancienne base est gardée ({0}) ; -Action NettoyerAncienneBase la supprime quand tout est vérifié.' -f $old) }
        Write-CogesLine 'Chacun se reconnecte avec son mot de passe habituel (celui de la sauvegarde). Les prévisions se recalculent seules (lundi nuit).'
        Remove-Item -LiteralPath $backup.Restauration -Recurse -Force -ErrorAction SilentlyContinue
    }
    finally { Exit-CogesLock $lock }
}

function Invoke-CogesCleanOldDatabase {
    <# -Action NettoyerAncienneBase : supprime les bases gardées après une restauration, après
       le code de la boutique retapé. Jamais automatique. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if ($script:CogesState.Simulation) { Write-CogesLine '[simulation] Liste des anciennes bases, code de la boutique, suppression'; return }
    [void](Get-CogesSetting $Paths)
    $lock = Enter-CogesLock -Paths $Paths -Action 'NettoyerAncienneBase'
    try {
        $kept = @(Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Anciennes bases' -Arguments @('base.py', 'bases')).Stdout)
        if ($kept.Count -eq 0) { Write-CogesLine 'Aucune ancienne base : rien à faire.' -Kind Ok; return }
        foreach ($base in $kept) { Write-CogesLine ('  {0} ({1:N1} Mo)' -f $base.nom, ($base.octets / 1MB)) }
        $slug = Read-CogesAnswer -Question 'Pour supprimer ces bases, retapez le code de la boutique' -Parameter 'CodeBoutique' -Value $Options.CodeBoutique `
            -Validate { param($v) Test-CogesSlug $v } -Rule 'minuscules, chiffres et tirets entre deux mots.'
        if ((Get-CogesLicenseStatus -Paths $Paths -Slug $slug).ExitCode -ne 0) {
            Stop-CogesStep -Probleme ('Aucune société « {0} » sur ce PC : rien n''est supprimé.' -f $slug) -QuoiFaire 'Relancez et retapez le code exact.'
        }
        foreach ($base in $kept) {
            [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What ('Suppression de ' + $base.nom) -Arguments @('base.py', 'supprimer', [string]$base.nom))
            Write-CogesLine ('  {0} supprimée.' -f $base.nom) -Kind Ok
        }
        Write-CogesBackupState -Paths $Paths -Changes @{ ancienne_base = $null }
    }
    finally { Exit-CogesLock $lock }
}

function Show-CogesBackupState {
    <# Les lignes du lot 4 dans Etat. #>
    param([Parameter(Mandatory)] $Paths)
    $summary = Get-CogesBackupSummary $Paths
    if ($summary.Last) {
        Write-CogesLine ('  Dernière sauvegarde : {0} ({1:N1} Mo)' -f $summary.Last.Date.ToString('dd/MM/yyyy HH:mm'), ($summary.Last.Size / 1MB))
    }
    else { Write-CogesLine '  Dernière sauvegarde : aucune' -Kind Attention }
    $offsite = 'jamais'
    if ($summary.LastOffsite) { $offsite = '{0} ({1})' -f $summary.LastOffsite.ToString('dd/MM/yyyy HH:mm'), $summary.OffsiteDisk }
    Write-CogesLine ('  Copie hors du PC    : {0}' -f $offsite)
    $trial = 'jamais'
    if ($summary.LastTrial) {
        $trial = '{0} ({1})' -f $summary.LastTrial.ToString('dd/MM/yyyy HH:mm'), $(if ($summary.LastTrialOk) { 'réussie' } else { 'EN ÉCHEC' })
    }
    Write-CogesLine ('  Restauration d''essai : {0}' -f $trial)
    Write-CogesLine ('  Sauvegardes gardées : {0}{1}' -f $summary.Count, $(if ($summary.Failed) { ' (+ {0} en échec, gardées pour l''enquête)' -f $summary.Failed } else { '' }))
    if (-not $summary.HasKey) { Write-CogesLine '  Clé de sauvegarde   : ABSENTE (-Action Reparer -ClePublique <fichier>)' -Kind Attention }
    $state = Read-CogesBackupState $Paths
    if ($state['ancienne_base']) { Write-CogesLine ('  Ancienne base gardée : {0} (-Action NettoyerAncienneBase)' -f $state['ancienne_base']) -Kind Attention }
    foreach ($alert in (Get-CogesBackupAlert -Now (Get-Date) -LastGood $summary.LastGood -LastOffsite $summary.LastOffsite -FreeBytes $summary.Free -TrialOk $summary.LastTrialOk)) {
        Write-CogesLine ('  À faire : ' + $alert.Texte) -Kind Attention
    }
}

function Install-CogesBackupSetup {
    <# Installer et Reparer : clé publique, tâche « CoGes - sauvegarde » ; Installer fait en
       plus une première sauvegarde et propose de préparer un disque (facultatif). #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans les blocs des étapes (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options, [Parameter(Mandatory)] [string] $Slug, [switch] $FirstBackup)
    Invoke-CogesStep -Title 'Clé de sauvegarde (le PC chiffre, seul CoGes relit)' -Action {
        Set-CogesBackupKey -Paths $Paths -Options $Options -Slug $Slug
    }
    Install-CogesBackupTask -Paths $Paths
    if (-not $FirstBackup) { return }
    Invoke-CogesStep -Title 'Première sauvegarde' -Action {
        $lock = Enter-CogesLock -Paths $Paths -Action 'Première sauvegarde'
        try {
            $made = New-CogesBackup -Paths $Paths -Trial -Raison 'installation'
            Write-CogesLine ('  {0} ({1:N1} Mo).' -f $made.Path, ($made.Size / 1MB)) -Kind Ok
        }
        finally { Exit-CogesLock $lock }
    }
    if ($script:CogesState.Simulation) {
        Write-CogesLine '[simulation] Proposition de préparer une clé USB de sauvegarde (facultatif)'
        return
    }
    $drive = $Options.Lecteur
    if (-not $drive -and -not $script:CogesState.NonInteractif) {
        $drive = Read-Host 'Préparer une clé USB de sauvegarde maintenant ? Sa lettre (ex. E:), ou Entrée pour passer'
    }
    if ($drive) {
        $prepare = @{} + $Options
        $prepare.Lecteur = $drive
        $prepare.CodeBoutique = $Slug
        Invoke-CogesPrepareDisk -Paths $Paths -Options $prepare
    }
    else { Write-CogesLine '  Clé USB : plus tard, -Action PreparerDisque -Lecteur E:.' }
}

function Get-CogesFreshBackup {
    <# Desinstaller -EffacerLesDonnees : une sauvegarde bonne de moins d'une heure, faite ici si besoin. #>
    param([Parameter(Mandatory)] $Paths)
    $summary = Get-CogesBackupSummary $Paths
    if ($summary.Last -and ((Get-Date) - $summary.Last.Date).TotalMinutes -lt 60) { return $summary.Last.Path }
    Write-CogesLine 'Sauvegarde des données avant de les effacer…' -Kind Titre
    $lock = Enter-CogesLock -Paths $Paths -Action 'Sauvegarde avant effacement'
    try { return (New-CogesBackup -Paths $Paths -Raison 'avant-effacement').Path }
    finally { Exit-CogesLock $lock }
}

# ---------------------------------------------------------------------------- actions

function Initialize-CogesSession {
    param(
        [Parameter(Mandatory)] $Paths,
        [bool] $Simulation,
        [bool] $NonInteractif,
        [bool] $WriteLog = $true
    )
    $script:CogesState.Simulation = $Simulation
    $script:CogesState.NonInteractif = $NonInteractif
    $script:CogesState.LogPath = $null
    $script:CogesState.MaskValues = @()
    # Les sorties de docker (accents de license-status) sont en UTF-8.
    try { [Console]::OutputEncoding = New-Object Text.UTF8Encoding $false } catch { Write-Verbose 'console sans encodage réglable' }
    if (-not [Net.ServicePointManager]::SecurityProtocol.HasFlag([Net.SecurityProtocolType]::Tls12)) {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    }
    if ($WriteLog -and -not $Simulation) {
        New-Item -ItemType Directory -Force -Path $Paths.Journaux | Out-Null
        $script:CogesState.LogPath = Join-Path $Paths.Journaux ('installation-{0}.log' -f (Get-Date).ToString('yyyyMMdd-HHmmss'))
    }
    if (Test-Path -LiteralPath $Paths.EnvFile) { [void](Get-CogesSetting $Paths) }
}

function Invoke-CogesInstall {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    $version = $Options.Version
    Assert-CogesVersion $version
    $settingsExist = Test-Path -LiteralPath $Paths.EnvFile
    if ($settingsExist) {
        $settings = Get-CogesSetting $Paths
        if ($settings['COGES_IMAGE_TAG'] -ne $version) {
            Stop-CogesStep -Probleme ('CoGes {0} est déjà installé sur ce PC (réglages gardés), pas {1}.' -f $settings['COGES_IMAGE_TAG'], $version) `
                -QuoiFaire ('Pour changer de version : -Action Reparer -Version {0}. Pour reprendre l''installation : -Version {1}.' -f $version, $settings['COGES_IMAGE_TAG'])
        }
        if ($Options.Port -and [int]$settings['COGES_HTTP_PORT'] -ne $Options.Port) {
            Stop-CogesStep -Probleme ('CoGes est déjà réglé sur le port {0}.' -f $settings['COGES_HTTP_PORT']) `
                -QuoiFaire ('Pour changer de port : -Action Reparer -Port {0}.' -f $Options.Port)
        }
    }
    $answers = Read-CogesInstallAnswer -Given $Options
    Test-CogesPrerequisite -Version $version -Racine $Paths.Racine -AlreadyInstalled:(Test-Path -LiteralPath $Paths.Programme)

    Invoke-CogesStep -Title ('Pose du programme {0} dans {1} (seulement deploy/onprem)' -f $version, $Paths.Programme) -Action {
        if (Test-CogesProgramme -Paths $Paths -Version $version) {
            Write-CogesLine '  Déjà posé, rien à faire.' -Kind Ok
            return
        }
        New-Item -ItemType Directory -Force -Path $Paths.Racine | Out-Null
        $archive = Join-Path ([IO.Path]::GetTempPath()) ('coges-{0}-{1}.zip' -f $version, [Guid]::NewGuid().ToString('N').Substring(0, 8))
        try {
            Save-CogesArchive -Version $version -Destination $archive
            $count = Install-Programme -Archive $archive -Racine $Paths.Racine -Version $version
            Write-CogesLine ('  {0} fichiers posés.' -f $count) -Kind Ok
        }
        finally {
            if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force }
        }
    }

    $portChosenNow = $false
    if ($settingsExist) {
        Invoke-CogesStep -Title ('Réglages : {0} existe, on n''y touche pas' -f $Paths.EnvFile) -Action { }
    }
    else {
        # Une étape ne rend rien : le port choisi passe par ce tableau.
        $choice = @{ Port = 80 }
        Invoke-CogesStep -Title 'Choix du port : 80, sinon 8080 ou le premier libre au-dessus' -Action {
            $listening = @()
            if (-not $Options.Port) { $listening = Get-CogesListeningPort }
            $chosen = Select-CogesPort -Requested $Options.Port -Listening $listening
            if (-not $Options.Port -and $chosen -ne 80) {
                Write-CogesLine ('  Le port 80 est pris par {0} : CoGes s''ouvrira sur le port {1}.' -f (Get-CogesPortOwner 80), $chosen) -Kind Attention
            }
            $choice.Port = $chosen
        }
        $portChosenNow = -not $Options.Port
        Invoke-CogesStep -Title ('Réglages : création de {0} (9 réglages secrets tirés au hasard)' -f $Paths.EnvFile) -Action {
            New-CogesSetting -Paths $Paths -Version $version -Port $choice.Port
            Write-CogesLine '  9 réglages secrets créés (aucun n''est affiché).' -Kind Ok
        }
        if (-not $script:CogesState.Simulation) {
            Write-CogesLine ''
            Write-CogesLine ('Copiez {0} dans le gestionnaire de mots de passe de CoGes MAINTENANT : sans lui, la base de ce client ne s''ouvre plus.' -f $Paths.EnvFile) -Kind Attention
        }
        else {
            Write-CogesLine '[simulation] Rappel : copier coges.env dans le gestionnaire de mots de passe (COPIE-FAITE exigé)'
        }
        if (-not $script:CogesState.Simulation) {
            Confirm-CogesWord -Word 'COPIE-FAITE' -Prompt 'Copie faite ?' -Given $Options.CopieFaite -Parameter 'CopieFaite'
        }
    }

    Start-CogesStack -Paths $Paths -PortChosenNow:$portChosenNow

    $url = 'http://localhost'
    if (-not $script:CogesState.Simulation) { $url = (Get-CogesSetting $Paths)['COGES_PUBLIC_URL'] }
    Invoke-CogesStep -Title ('Société {0} (créée seulement si elle n''existe pas)' -f $answers.CodeBoutique) -Action {
        New-CogesCompany -Paths $Paths -Answers $answers
    }
    Invoke-CogesStep -Title ('Licence {0} (rien à faire si elle est déjà posée)' -f $answers.Offre) -Action {
        Set-CogesLicense -Paths $Paths -Answers $answers
    }
    Invoke-CogesStep -Title 'Dernier contrôle : la page d''accueil répond, l''administration est absente' -Action {
        Test-CogesSite -Url $url
    }
    Install-CogesComfort -Paths $Paths -Url $url
    Initialize-CogesSupportSetting -Paths $Paths -Options $Options
    Install-CogesSupportShortcut -Paths $Paths
    Install-CogesBackupSetup -Paths $Paths -Options $Options -Slug $answers.CodeBoutique -FirstBackup
    Set-CogesUpdateOption -Paths $Paths -Options $Options
    Install-CogesUpdateTask -Paths $Paths
    Write-CogesLine ''
    if ($script:CogesState.Simulation) {
        Write-CogesLine 'Simulation terminée : rien n''a été écrit ni lancé.' -Kind Ok
        return
    }
    Write-CogesLine ('CoGes est installé : {0}' -f $url) -Kind Ok
    Write-CogesLine ('Connexion : code {0}, le téléphone ou l''e-mail du gérant, et son mot de passe.' -f $answers.CodeBoutique) -Kind Ok
    Write-CogesLine ('Journal : {0}' -f $script:CogesState.LogPath)
    try { Start-Process $url } catch { Write-CogesLine ('Ouvrez {0} dans Edge ou Chrome.' -f $url) }
}

function Invoke-CogesRepair {
    <# Blocs B à E sans rien recréer : réglages et données gardés. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if (-not $script:CogesState.Simulation -and -not (Test-Path -LiteralPath $Paths.EnvFile)) {
        Stop-CogesStep -Probleme ('CoGes n''est pas installé ici ({0} absent).' -f $Paths.EnvFile) -QuoiFaire 'Lancez -Action Installer.'
    }
    $version = $Options.Version
    $settings = @{ COGES_IMAGE_TAG = $version; COGES_HTTP_PORT = '80'; COGES_PUBLIC_URL = 'http://localhost' }
    if (-not $script:CogesState.Simulation) { $settings = Get-CogesSetting $Paths }
    if (-not $version) { $version = $settings['COGES_IMAGE_TAG'] }
    Assert-CogesVersion $version
    $slug = Read-CogesAnswer -Question 'Code de la boutique' -Parameter 'CodeBoutique' -Value $Options.CodeBoutique `
        -Validate { param($v) Test-CogesSlug $v } -Rule 'minuscules, chiffres et tirets entre deux mots.'
    $changed = ($settings['COGES_IMAGE_TAG'] -ne $version)
    # Jamais pendant une sauvegarde ou une restauration (verrou commun, ADR 0127).
    $lock = Enter-CogesLock -Paths $Paths -Action 'Reparer'
    try { Invoke-CogesRepairLocked -Paths $Paths -Options $Options -Version $version -Settings $settings -Slug $slug -Changed $changed }
    finally { Exit-CogesLock $lock }
}

function Invoke-CogesRepairLocked {
    <# Le corps de Reparer, verrou tenu. #>
    param(
        [Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options, [Parameter(Mandatory)] [string] $Version,
        [Parameter(Mandatory)] $Settings, [Parameter(Mandatory)] [string] $Slug, [bool] $Changed
    )
    $version = $Version
    $settings = $Settings
    $slug = $Slug
    $changed = $Changed
    Test-CogesPrerequisite -Version $version -Racine $Paths.Racine -AlreadyInstalled
    Invoke-CogesStep -Title ('Programme {0} : reposé s''il manque, est abîmé ou d''une autre version' -f $version) -Action {
        if (Test-CogesProgramme -Paths $Paths -Version $version) {
            Write-CogesLine '  Programme en bon état.' -Kind Ok
            return
        }
        $archive = Join-Path ([IO.Path]::GetTempPath()) ('coges-{0}-{1}.zip' -f $version, [Guid]::NewGuid().ToString('N').Substring(0, 8))
        try {
            Save-CogesArchive -Version $version -Destination $archive
            [void](Install-Programme -Archive $archive -Racine $Paths.Racine -Version $version)
            Write-CogesLine '  Programme reposé.' -Kind Ok
        }
        finally { if (Test-Path -LiteralPath $archive) { Remove-Item -LiteralPath $archive -Force } }
    }
    $edits = [ordered]@{}
    if ($changed) { $edits['COGES_IMAGE_TAG'] = $version }
    if ($Options.Port -and [string]$Options.Port -ne $settings['COGES_HTTP_PORT']) {
        $edits['COGES_HTTP_PORT'] = [string]$Options.Port
        $edits['COGES_PUBLIC_URL'] = Get-CogesPublicUrl $Options.Port
    }
    if ($edits.Count -gt 0) {
        Invoke-CogesStep -Title ('Réglages : seules les lignes {0} changent' -f ($edits.Keys -join ', ')) -Action {
            Set-CogesEnvValue -Path $Paths.EnvFile -Values $edits
        }
    }
    Start-CogesStack -Paths $Paths -StopApplicationFirst:$changed
    $url = 'http://localhost'
    if (-not $script:CogesState.Simulation) { $url = (Get-CogesSetting $Paths)['COGES_PUBLIC_URL'] }
    Invoke-CogesStep -Title ('Licence de {0} : relue' -f $slug) -Action {
        $status = Get-CogesLicenseStatus -Paths $Paths -Slug $slug
        foreach ($line in $status.Output) {
            if ($line -and $line -notmatch '^\s*Container ') { Write-CogesLine ('  ' + $line) }
        }
        if (Test-CogesCompanyMissing -ExitCode $status.ExitCode -Lines $status.Output) {
            Stop-CogesStep -Probleme ('La société {0} n''existe pas.' -f $slug) -QuoiFaire 'Vérifiez le code ; pour la créer, lancez -Action Installer.'
        }
        if (-not (Test-CogesLicenseActive $status.Output)) {
            Stop-CogesStep -Probleme 'La licence n''est pas « actif, sans fin ».' -QuoiFaire 'Lancez -Action Installer avec le même code : il la pose sans rien recréer.'
        }
    }
    Invoke-CogesStep -Title 'Dernier contrôle de la page d''accueil' -Action { Test-CogesSite -Url $url }
    Install-CogesComfort -Paths $Paths -Url $url
    Initialize-CogesSupportSetting -Paths $Paths -Options $Options
    Install-CogesSupportShortcut -Paths $Paths
    Install-CogesBackupSetup -Paths $Paths -Options $Options -Slug $slug
    Set-CogesUpdateOption -Paths $Paths -Options $Options
    Install-CogesUpdateTask -Paths $Paths
    Write-CogesLine ''
    if ($script:CogesState.Simulation) { Write-CogesLine 'Simulation terminée : rien n''a été écrit ni lancé.' -Kind Ok }
    else { Write-CogesLine ('Réparation terminée : {0}' -f $url) -Kind Ok }
}

function Show-CogesState {
    <# N'écrit rien : version, services, adresse, licence, disque, dernier journal. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if ($script:CogesState.Simulation) {
        Write-CogesLine '[simulation] Lecture de la version, des services, de l''adresse, de la licence, du disque et du dernier journal'
        return
    }
    if (-not (Test-Path -LiteralPath $Paths.EnvFile)) {
        Write-CogesLine ('CoGes n''est pas installé ici ({0} absent).' -f $Paths.EnvFile) -Kind Attention
        return
    }
    $settings = Get-CogesSetting $Paths
    Write-CogesLine 'État de CoGes' -Kind Titre
    Write-CogesLine ('  Programme        : {0}' -f (Get-CogesInstalledVersion $Paths))
    Write-CogesLine ('  Version réglée   : {0}' -f $settings['COGES_IMAGE_TAG'])
    Write-CogesLine ('  Adresse          : {0} (port {1})' -f $settings['COGES_PUBLIC_URL'], $settings['COGES_HTTP_PORT'])
    # Docker arrêté : on le dit, et on montre quand même ce que disent les fichiers.
    $engine = Get-CogesDockerEngineProblem
    if ($null -eq $engine) {
        $ps = Invoke-CogesCompose -Paths $Paths -Arguments @('ps', '-a', '--format', 'json')
        $containers = @(ConvertFrom-CogesComposeStatus $ps.Stdout)
        foreach ($service in $script:CogesServices) {
            $container = @($containers | Where-Object { $_.Service -eq $service }) | Select-Object -First 1
            $state = 'absent'
            if ($container) { $state = ($container.State + ' ' + $container.Health).Trim() }
            Write-CogesLine ('  {0,-16} : {1}' -f $service, $state)
        }
        $slug = Read-CogesAnswer -Question 'Code de la boutique (vide pour passer)' -Parameter 'CodeBoutique' -Value $Options.CodeBoutique -Optional `
            -Validate { param($v) Test-CogesSlug $v } -Rule 'minuscules, chiffres et tirets entre deux mots.'
        if ($slug) {
            foreach ($line in (Get-CogesLicenseStatus -Paths $Paths -Slug $slug).Output) {
                if ($line -and $line -notmatch '^\s*Container ') { Write-CogesLine ('  ' + $line) }
            }
        }
    }
    else { Write-CogesLine ('  Docker           : ' + $script:CogesDockerStoppedText) -Kind Echec }
    $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Paths.Racine)))
    $freeKind = 'Info'
    if ($drive.AvailableFreeSpace -lt $script:CogesAlertFreeBytes) { $freeKind = 'Echec' }
    $freeText = '  Disque libre     : {0:N1} Go sur {1}' -f ($drive.AvailableFreeSpace / 1GB), $drive.Name
    if ($freeKind -eq 'Echec') { $freeText += ' : MOINS DE 5 GO, libérez de la place (jamais « Clean / Purge data » dans Docker Desktop)' }
    Write-CogesLine $freeText -Kind $freeKind
    $last = Get-ChildItem -LiteralPath $Paths.Journaux -Filter 'installation-*.log' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
    if ($last) { Write-CogesLine ('  Dernier journal  : {0}' -f $last.FullName) }
    Show-CogesBackupState $Paths
    Show-CogesUpdateState -Paths $Paths
    Show-CogesSupportState -Paths $Paths
}

function Invoke-CogesUninstall {
    <# Conteneurs, tâche, raccourci, bin\ et PATH. Réglages et données gardés, sauf
       -EffacerLesDonnees (code de la boutique retapé, puis EFFACER). Jamais « down -v ». #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    $erase = [bool]$Options.EffacerLesDonnees
    if ($erase -and $script:CogesState.NonInteractif) {
        Stop-CogesStep -Probleme 'L''effacement des données exige une personne devant le PC.' -QuoiFaire 'Relancez sans -NonInteractif.'
    }
    if (-not $script:CogesState.Simulation) { Assert-CogesDockerRunning }
    $hasSettings = Test-Path -LiteralPath $Paths.EnvFile
    Write-CogesLine 'Désinstallation : les conteneurs, la tâche planifiée, le raccourci et la commande « coges » sont retirés.' -Kind Titre
    if ($erase) { Write-CogesLine 'ET LES DONNÉES (ventes, stock, clients…) seront effacées.' -Kind Echec }
    else { Write-CogesLine ('Les réglages ({0}) et les données sont gardés : -Action Installer les retrouve.' -f $Paths.Reglages) }
    if (-not $script:CogesState.Simulation) {
        Confirm-CogesWord -Word 'OUI' -Prompt 'Continuer ?' -Given $script:CogesState.NonInteractif
    }
    if ($erase -and -not $script:CogesState.Simulation) {
        $slug = Read-Host 'Pour effacer les données, retapez le code de la boutique'
        if (-not $hasSettings -or -not (Test-CogesSlug $slug)) {
            Stop-CogesStep -Probleme 'Code de boutique absent ou mal écrit : rien n''est effacé.' -QuoiFaire 'Relancez et retapez le code exact.'
        }
        $status = Get-CogesLicenseStatus -Paths $Paths -Slug $slug
        if ($status.ExitCode -ne 0) {
            Stop-CogesStep -Probleme ('Aucune société « {0} » sur ce PC : rien n''est effacé.' -f $slug) -QuoiFaire 'Relancez et retapez le code exact.'
        }
        # Une sauvegarde bonne de moins d'une heure d'abord (faite ici si besoin), puis seulement EFFACER.
        $kept = Get-CogesFreshBackup -Paths $Paths
        Write-CogesLine ('Sauvegarde gardée : {0} (chiffrée ; elle se restaure avec la clé privée de ce client, -Action Restaurer).' -f $kept) -Kind Attention
        Confirm-CogesWord -Word 'EFFACER' -Prompt ('Effacer pour toujours les données de {0} de ce PC ?' -f $slug)
    }
    Invoke-CogesStep -Title 'Arrêt et suppression des conteneurs (les volumes de données restent)' -Action {
        if ($hasSettings -and (Test-Path -LiteralPath $Paths.Compose)) {
            [void](Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'down', '--remove-orphans'))
        }
        else {
            $ids = @((Invoke-Docker -Arguments @('ps', '-aq', '--filter', ('label=com.docker.compose.project=' + $script:CogesProject))).Stdout | Where-Object { $_ })
            if (@($ids).Count -gt 0) { [void](Invoke-Docker -Arguments (@('rm', '-f') + @($ids))) }
        }
    }
    Invoke-CogesStep -Title ('Tâche planifiée « {0} » retirée' -f $script:CogesTaskName) -Action {
        if (Get-ScheduledTask -TaskName $script:CogesTaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:CogesTaskName -Confirm:$false
        }
    }
    Remove-CogesBackupTask
    Remove-CogesUpdateTask -Paths $Paths
    Remove-CogesSupportShortcut
    Invoke-CogesStep -Title 'Raccourci du Bureau retiré' -Action {
        $shortcut = Join-Path ([Environment]::GetFolderPath('Desktop')) 'CoGes.url'
        if (Test-Path -LiteralPath $shortcut) { Remove-Item -LiteralPath $shortcut -Force }
    }
    Invoke-CogesStep -Title 'Commande « coges » retirée (bin et PATH)' -Action {
        $current = Get-CogesUserPath
        $wanted = Remove-CogesPathEntry -PathValue $current -Directory $Paths.Bin
        if ($wanted -ne $current) { Set-CogesUserPath $wanted }
        if (Test-Path -LiteralPath $Paths.Bin) { Remove-Item -LiteralPath $Paths.Bin -Recurse -Force }
    }
    if ($erase) {
        Invoke-CogesStep -Title ('Effacement des volumes {0}_*' -f $script:CogesProject) -Action {
            $volumes = (Invoke-Docker -Arguments @('volume', 'ls', '-q', '--filter', ('label=com.docker.compose.project=' + $script:CogesProject))).Stdout
            foreach ($volume in @($volumes)) {
                if ($volume -like ($script:CogesProject + '_*')) { [void](Invoke-Docker -Arguments @('volume', 'rm', $volume)) }
            }
        }
    }
    Write-CogesLine ''
    if ($script:CogesState.Simulation) { Write-CogesLine 'Simulation terminée : rien n''a été écrit ni lancé.' -Kind Ok }
    elseif ($erase) { Write-CogesLine 'CoGes est désinstallé et ses données effacées. Les réglages restent dans le dossier reglages.' -Kind Ok }
    else { Write-CogesLine 'CoGes est désinstallé ; les réglages et les données sont gardés.' -Kind Ok }
}

function Invoke-CogesMain {
    <# Le point d'entrée commun : rend 0 (fait) ou 1 (échec expliqué). #>
    param(
        [ValidateSet('Installer', 'Reparer', 'Etat', 'Desinstaller', 'Sauvegarder', 'Restaurer', 'PreparerDisque', 'NettoyerAncienneBase',
            'VerifierMiseAJour', 'MettreAJour', 'RevenirVersionPrecedente', 'ConfigurerSupport', 'TesterSupport', 'Diagnostic', 'Aide')] [string] $Action = 'Installer',
        [string] $Version = '',
        [string] $Racine = 'C:\CoGes',
        [int] $Port = 0,
        [switch] $Simulation,
        [switch] $NonInteractif,
        [switch] $CopieFaite,
        [switch] $EffacerLesDonnees,
        [string] $NomBoutique = '',
        [string] $CodeBoutique = '',
        [string] $NomGerant = '',
        [string] $TelephoneGerant = '',
        [string] $EmailGerant = '',
        [string] $Offre = '',
        [string] $NoteContrat = '',
        [string] $Fichier = '',
        [string] $Cle = '',
        [string] $Lecteur = '',
        [string] $ClePublique = '',
        [string] $LecteurCle = '',
        [switch] $CleCopiee,
        [switch] $ConfirmerRestauration,
        [switch] $RestaurerQuandMeme,
        [switch] $Essai,
        [switch] $SansNotification,
        [switch] $Maintenant,
        [switch] $Bureau,
        [switch] $ConfirmerRetour,
        [string] $HeureMiseAJour = '',
        [string] $CanalMiseAJour = '',
        [string] $Support = ''
    )
    $script:CogesState.Simulation = [bool]$Simulation
    $script:CogesToastEnabled = -not [bool]$SansNotification
    $script:CogesState.NonInteractif = [bool]$NonInteractif
    $script:CogesState.LogPath = $null
    $script:CogesState.Output.Clear()
    $paths = Get-CogesPath $Racine
    $options = @{
        Version = $Version; Port = $Port; CopieFaite = [bool]$CopieFaite; EffacerLesDonnees = [bool]$EffacerLesDonnees
        NomBoutique = $NomBoutique; CodeBoutique = $CodeBoutique; NomGerant = $NomGerant
        TelephoneGerant = $TelephoneGerant; EmailGerant = $EmailGerant; Offre = $Offre; NoteContrat = $NoteContrat
        Fichier = $Fichier; Cle = $Cle; Lecteur = $Lecteur; ClePublique = $ClePublique; LecteurCle = $LecteurCle
        CleCopiee = [bool]$CleCopiee; ConfirmerRestauration = [bool]$ConfirmerRestauration; RestaurerQuandMeme = [bool]$RestaurerQuandMeme; Essai = [bool]$Essai
        Maintenant = [bool]$Maintenant; Bureau = [bool]$Bureau; ConfirmerRetour = [bool]$ConfirmerRetour
        HeureMiseAJour = $HeureMiseAJour; CanalMiseAJour = $CanalMiseAJour; Support = $Support
    }
    # Le raccourci du Bureau : une personne devant le PC, une fenêtre qui attend Entrée à la fin.
    if ($Bureau) { $NonInteractif = $false; $script:CogesState.NonInteractif = $false }
    try {
        if ($Port -and ($Port -lt 1 -or $Port -gt 65535)) {
            Stop-CogesStep -Probleme ('-Port {0} n''est pas un numéro de port.' -f $Port) -QuoiFaire 'Donnez un port entre 1 et 65535 (80, 8080…).'
        }
        if ($Action -eq 'Installer') { Assert-CogesVersion $Version }
        Initialize-CogesSession -Paths $paths -Simulation $Simulation -NonInteractif $NonInteractif -WriteLog ($Action -notin @('Etat', 'Aide'))
        Write-CogesLine ('CoGes sur site — {0}' -f $Action) -Kind Titre
        if ($Simulation) { Write-CogesLine 'Mode simulation : chaque étape est annoncée, rien n''est écrit ni lancé.' }
        # Installer et Reparer contrôlent Docker dans leurs prérequis ; Etat le dit sans s'arrêter.
        if (-not $Simulation -and ($script:CogesDockerActions -contains $Action)) { Assert-CogesDockerRunning }
        switch ($Action) {
            'Installer' { Invoke-CogesInstall -Paths $paths -Options $options }
            'Reparer' { Invoke-CogesRepair -Paths $paths -Options $options }
            'Etat' { Show-CogesState -Paths $paths -Options $options }
            'Desinstaller' { Invoke-CogesUninstall -Paths $paths -Options $options }
            'Sauvegarder' { Invoke-CogesBackupAction -Paths $paths -Options $options }
            'Restaurer' { Restore-CogesBackup -Paths $paths -Options $options }
            'PreparerDisque' { Invoke-CogesPrepareDisk -Paths $paths -Options $options }
            'NettoyerAncienneBase' { Invoke-CogesCleanOldDatabase -Paths $paths -Options $options }
            'VerifierMiseAJour' { Invoke-CogesUpdateCheckAction -Paths $paths }
            'MettreAJour' { Invoke-CogesUpdateAction -Paths $paths -Options $options }
            'RevenirVersionPrecedente' { Invoke-CogesRollbackAction -Paths $paths -Options $options }
            'ConfigurerSupport' { Invoke-CogesConfigureSupport -Paths $paths -Options $options }
            'TesterSupport' { Invoke-CogesTestSupport -Paths $paths }
            'Diagnostic' { Invoke-CogesDiagnosticAction -Paths $paths -Options $options }
            'Aide' { Invoke-CogesHelpAction -Paths $paths }
        }
        Wait-CogesDesktopWindow -Bureau ([bool]$Bureau)
        return 0
    }
    catch {
        $exception = $_.Exception
        Write-CogesLine ''
        if (Test-CogesMessage $exception) {
            Write-CogesLine ('ÉCHEC — ' + $exception.Message) -Kind Echec
        }
        else {
            Write-CogesLine ('ÉCHEC imprévu — ' + $exception.Message) -Kind Echec
            Write-CogesLine 'Relancez la même commande : ce qui est déjà fait est gardé. Si l''échec revient, envoyez le journal à CoGes.' -Kind Echec
            Write-Log -Message ('trace : ' + $_.ScriptStackTrace) -Level ECHEC
        }
        if ($script:CogesState.LogPath) { Write-CogesLine ('Journal : ' + $script:CogesState.LogPath) }
        Wait-CogesDesktopWindow -Bureau ([bool]$Bureau)
        return 1
    }
}

function Wait-CogesDesktopWindow {
    <# Lancé par le raccourci « Mettre CoGes à jour » : la fenêtre reste ouverte jusqu'à Entrée. #>
    param([bool] $Bureau)
    if (-not $Bureau) { return }
    try { [void](Read-Host 'Appuyez sur Entrée pour fermer cette fenêtre') } catch { Write-Verbose 'pas de console' }
}

# ---------------------------------------------------------------------------- lot 5 : mises à jour (ADR 0128)
#
# Le PC VA CHERCHER (aucun port ouvert, aucune connexion entrante) : il lit son canal
# (deploy/onprem/canal/<canal>.json sur main), télécharge pendant que CoGes tourne, applique à
# une heure calme, se vérifie, et revient seul en arrière si quelque chose casse. Le retour se
# fait SANS la clé privée (que le PC n'a pas) : par une copie de la base, faite application
# arrêtée, dans le même PostgreSQL. Il ne croit jamais une étiquette : images tirées par
# digest. Le canal n'est pas signé (ADR 0128) : champ « signature » réservé.

$script:CogesUpdateTaskName = 'CoGes - mise à jour'
$script:CogesChannelBase = 'https://raw.githubusercontent.com/papa-bothie/CoGes/main/deploy/onprem/canal'
$script:CogesArchiveBase = 'https://github.com/papa-bothie/CoGes/archive/refs/tags'
$script:CogesChannelFormat = 'COGES-CANAL-1'
$script:CogesChannels = @('stable', 'test')
$script:CogesImageNames = @('front', 'api', 'worker')
#: Images d'autres éditeurs du compose : tirées à l'avance, avant l'heure calme.
$script:CogesThirdPartyServices = @('caddy', 'autoheal', 'postgres', 'redis', 'sauvegarde-pg')
$script:CogesApplicationServices = @('front', 'api', 'worker', 'beat', 'relay')
$script:CogesUpdateCheckSlots = @('12:00', '18:00')
$script:CogesUpdateDefaultHour = '21:30'
#: L'application se tente entre l'heure réglée et deux heures après, jamais au démarrage.
$script:CogesUpdateWindowMinutes = 120
$script:CogesQuietMinutes = 30
$script:CogesBootMinutes = 15
$script:CogesKeepDays = 7
$script:CogesManualAfterDays = 3
$script:CogesUpdateMinFree = 5GB
$script:CogesUpdateShortcut = 'Mettre CoGes à jour.cmd'
$script:CogesUpdateMinutesDefault = 5
$script:CogesVersionRule = '^v(\d+)\.(\d+)\.(\d+)$'

function Get-CogesUpdatePath {
    param([Parameter(Mandatory)] $Paths)
    $folder = Join-Path $Paths.Racine 'mises-a-jour'
    return [pscustomobject]@{
        Dossier   = $folder
        Etat      = Join-Path $folder 'etat.json'
        Reglage   = Join-Path $Paths.Reglages 'mise-a-jour.json'
        Precedent = $Paths.Programme + '.precedent'
        Echec     = $Paths.Programme + '.echec'
    }
}

# ---------------------------------------------------------------------------- versions (fonctions pures)

function ConvertTo-CogesVersionKey {
    <# vX.Y.Z en [version] (comparable) ; $null pour tout autre texte. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Version)
    if (-not $Version -or $Version -notmatch $script:CogesVersionRule) { return $null }
    return New-Object Version ([int]$Matches[1]), ([int]$Matches[2]), ([int]$Matches[3])
}

function Get-CogesDockerDesktopVersion {
    <# « Docker Desktop 4.37.1 (178610) » → 4.37.1 ; $null ailleurs (moteur Linux de la CI). #>
    param([AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    $text = @($Lines) -join "`n"
    if ($text -match 'Docker Desktop (\d+)\.(\d+)\.(\d+)') { return New-Object Version ([int]$Matches[1]), ([int]$Matches[2]), ([int]$Matches[3]) }
    return $null
}

function Test-CogesHour {
    param([AllowEmptyString()] [AllowNull()] [string] $Value)
    return ([string]$Value -match '^([01]\d|2[0-3]):[0-5]\d$')
}

# ---------------------------------------------------------------------------- état et réglage

function ConvertTo-CogesHashtable {
    <# Le JSON relu (objets de ConvertFrom-Json) en tables, récursivement : 5.1 n'a pas -AsHashtable. #>
    param([AllowNull()] $Value)
    if ($null -eq $Value) { return $null }
    if ($Value -is [System.Management.Automation.PSCustomObject]) {
        $table = @{}
        foreach ($property in $Value.PSObject.Properties) { $table[$property.Name] = ConvertTo-CogesHashtable $property.Value }
        return $table
    }
    if ($Value -is [System.Collections.IList] -and $Value -isnot [string]) { return , @($Value | ForEach-Object { ConvertTo-CogesHashtable $_ }) }
    return $Value
}

function Read-CogesUpdateState {
    <# mises-a-jour\etat.json : versions vues et leur état, dernière mise à jour, rappels. #>
    param([Parameter(Mandatory)] $Paths)
    $file = (Get-CogesUpdatePath $Paths).Etat
    $state = @{}
    if (Test-Path -LiteralPath $file) {
        try { $state = ConvertTo-CogesHashtable ([IO.File]::ReadAllText($file) | ConvertFrom-Json) }
        catch { Write-Log -Message 'mises-a-jour\etat.json illisible : ignoré' -Level ATTENTION; $state = @{} }
    }
    if (-not ($state -is [hashtable])) { $state = @{} }
    if (-not ($state['versions'] -is [hashtable])) { $state['versions'] = @{} }
    return $state
}

function Write-CogesUpdateState {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $State)
    $file = (Get-CogesUpdatePath $Paths).Etat
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    $temporary = $file + '.nouveau'
    [IO.File]::WriteAllText($temporary, ($State | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $file -Force
}

function Set-CogesVersionState {
    <# L'état d'une version : vue, telechargement, prete, appliquee, echec, annulee. #>
    param([Parameter(Mandatory)] [hashtable] $State, [Parameter(Mandatory)] [string] $Version, [Parameter(Mandatory)] [hashtable] $Changes)
    if (-not ($State['versions'][$Version] -is [hashtable])) { $State['versions'][$Version] = @{} }
    foreach ($key in $Changes.Keys) { $State['versions'][$Version][$key] = $Changes[$key] }
}

function Get-CogesVersionState {
    param([Parameter(Mandatory)] [hashtable] $State, [AllowEmptyString()] [string] $Version)
    if (-not $Version) { return $null }
    $entry = $State['versions'][$Version]
    if ($entry -is [hashtable]) { return $entry }
    return $null
}

function Get-CogesReadyVersion {
    <# La version téléchargée et vérifiée, prête à appliquer (une seule à la fois), ou $null. #>
    param([Parameter(Mandatory)] [hashtable] $State)
    $ready = @($State['versions'].Keys | Where-Object { $State['versions'][$_]['etat'] -eq 'prete' } |
            Sort-Object { ConvertTo-CogesVersionKey $_ } -Descending)
    if ($ready.Count -eq 0) { return $null }
    return [string]$ready[0]
}

function Read-CogesUpdateSetting {
    <# reglages\mise-a-jour.json : canal (stable, test), automatique (oui/non), heure (HH:MM).
       Absent ou faux : les valeurs par défaut (journal), jamais d'arrêt. #>
    param([Parameter(Mandatory)] $Paths)
    $result = [ordered]@{ canal = 'stable'; automatique = $true; heure = $script:CogesUpdateDefaultHour }
    $file = (Get-CogesUpdatePath $Paths).Reglage
    if (Test-Path -LiteralPath $file) {
        try {
            $data = ConvertTo-CogesHashtable ([IO.File]::ReadAllText($file) | ConvertFrom-Json)
            if ($data['canal'] -and ($script:CogesChannels -ccontains [string]$data['canal'])) { $result.canal = [string]$data['canal'] }
            elseif ($data.ContainsKey('canal')) { Write-Log -Message ('mise-a-jour.json : canal « {0} » inconnu, stable gardé' -f $data['canal']) -Level ATTENTION }
            if ($data['automatique'] -is [bool]) { $result.automatique = [bool]$data['automatique'] }
            if (Test-CogesHour ([string]$data['heure'])) { $result.heure = [string]$data['heure'] }
            elseif ($data.ContainsKey('heure')) { Write-Log -Message ('mise-a-jour.json : heure « {0} » illisible, {1} gardée' -f $data['heure'], $result.heure) -Level ATTENTION }
        }
        catch { Write-Log -Message 'mise-a-jour.json illisible : réglages par défaut' -Level ATTENTION }
    }
    return [pscustomobject]$result
}

function Write-CogesUpdateSetting {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Changes)
    $current = Read-CogesUpdateSetting $Paths
    $data = [ordered]@{ canal = $current.canal; automatique = $current.automatique; heure = $current.heure }
    foreach ($key in $Changes.Keys) { $data[$key] = $Changes[$key] }
    $file = (Get-CogesUpdatePath $Paths).Reglage
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    [IO.File]::WriteAllText($file + '.nouveau', (([pscustomobject]$data) | ConvertTo-Json) + "`n", (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath ($file + '.nouveau') -Destination $file -Force
}

# ---------------------------------------------------------------------------- bloc A : le canal

function Get-CogesChannelSource {
    <# L'adresse du canal ; COGES_CANAL_ESSAI (dossier ou adresse) la remplace pour les essais. #>
    param([Parameter(Mandatory)] [string] $Canal)
    $base = $script:CogesChannelBase
    if ($env:COGES_CANAL_ESSAI) { $base = $env:COGES_CANAL_ESSAI.TrimEnd('/', '\') }
    if ($base -match '^https?://') { return ('{0}/{1}.json' -f $base, $Canal) }
    return (Join-Path $base ($Canal + '.json'))
}

function Read-CogesRemoteText {
    <# Un texte par https (canal) ou un fichier local (essais). Lève si rien ne répond. #>
    param([Parameter(Mandatory)] [string] $Source)
    if ($Source -match '^https?://') {
        $previous = $ProgressPreference
        $ProgressPreference = 'SilentlyContinue'
        try {
            $response = Invoke-WebRequest -Uri $Source -UseBasicParsing -TimeoutSec 30 -Headers @{ 'Cache-Control' = 'no-cache' } -ErrorAction Stop
            $content = $response.Content
            if ($content -is [byte[]]) { $content = (New-Object Text.UTF8Encoding $false).GetString($content) }
            return [string]$content
        }
        finally { $ProgressPreference = $previous }
    }
    return [IO.File]::ReadAllText($Source)
}

function ConvertFrom-CogesChannel {
    <# Le canal lu et vérifié : Data (l'objet) et Problems (les refus, en français). Mêmes
       règles que canal_problems() de publier.py. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Text)
    $problems = New-Object System.Collections.Generic.List[string]
    $data = $null
    try { $data = ConvertTo-CogesHashtable ($Text | ConvertFrom-Json) } catch { $data = $null }
    if (-not ($data -is [hashtable])) {
        $problems.Add('le canal n''est pas un objet JSON')
        return [pscustomobject]@{ Data = $null; Problems = $problems.ToArray() }
    }
    $fields = @('format', 'canal', 'version', 'publiee_le', 'depuis_minimum', 'images', 'programme', 'docker_desktop_minimum', 'note', 'signature')
    $missing = @($fields | Where-Object { -not $data.ContainsKey($_) })
    if ($missing.Count -gt 0) {
        $problems.Add('champs absents : ' + ($missing -join ', '))
        return [pscustomobject]@{ Data = $data; Problems = $problems.ToArray() }
    }
    if ($data['format'] -cne $script:CogesChannelFormat) { $problems.Add(('format {0}, {1} attendu' -f $data['format'], $script:CogesChannelFormat)) }
    if ($script:CogesChannels -cnotcontains [string]$data['canal']) { $problems.Add(('canal {0} inconnu' -f $data['canal'])) }
    foreach ($name in @('version', 'depuis_minimum')) {
        if (-not (ConvertTo-CogesVersionKey ([string]$data[$name]))) { $problems.Add(('{0} : vX.Y.Z attendu' -f $name)) }
    }
    if ($problems.Count -eq 0 -and (ConvertTo-CogesVersionKey $data['depuis_minimum']) -gt (ConvertTo-CogesVersionKey $data['version'])) {
        $problems.Add('depuis_minimum est plus récent que la version')
    }
    $images = $data['images']
    if (-not ($images -is [hashtable]) -or @($images.Keys).Count -ne 3) { $problems.Add('images : front, api et worker attendues') }
    else {
        foreach ($name in $script:CogesImageNames) {
            if ([string]$images[$name] -cnotmatch '^sha256:[0-9a-f]{64}$') { $problems.Add(('images.{0} : sha256:<64 hexadécimaux> attendu' -f $name)) }
        }
    }
    $programme = $data['programme']
    if (-not ($programme -is [hashtable]) -or [string]$programme['sha256'] -cnotmatch '^[0-9a-f]{64}$' -or -not ($programme['fichiers'] -is [int] -or $programme['fichiers'] -is [long]) -or [long]$programme['fichiers'] -lt 1) {
        $problems.Add('programme : sha256 et nombre de fichiers attendus')
    }
    $minimum = $data['docker_desktop_minimum']
    if ($null -ne $minimum -and [string]$minimum -notmatch '^\d+\.\d+\.\d+$') { $problems.Add('docker_desktop_minimum : X.Y.Z ou null attendu') }
    if (-not ($data['note'] -is [string]) -or $data['note'].Trim().Length -lt 1 -or $data['note'].Length -gt 300) { $problems.Add('note : une ou deux phrases (300 caractères au plus)') }
    if ($null -ne $data['signature']) { $problems.Add('signature : réservée, null attendu') }
    return [pscustomobject]@{ Data = $data; Problems = $problems.ToArray() }
}

function Get-CogesChannelDecision {
    <# Que faire de ce canal sur ce PC : a-jour, nouvelle, ou un refus (plus-ancienne, saut,
       docker, installee) avec sa phrase. #>
    param([Parameter(Mandatory)] [hashtable] $Channel, [AllowEmptyString()] [string] $Installed, [AllowNull()] $DockerDesktop = $null)
    $wanted = ConvertTo-CogesVersionKey $Channel['version']
    $current = ConvertTo-CogesVersionKey $Installed
    $version = [string]$Channel['version']
    if ($null -eq $current) {
        return [pscustomobject]@{ Decision = 'installee'; Texte = ('La version installée ({0}) ne se compare pas : mise à jour par le canal impossible, faites-la à la main (-Action Reparer -Version {1}).' -f $Installed, $version) }
    }
    if ($wanted -eq $current) { return [pscustomobject]@{ Decision = 'a-jour'; Texte = ('CoGes est à jour ({0}).' -f $Installed) } }
    if ($wanted -lt $current) {
        return [pscustomobject]@{ Decision = 'plus-ancienne'; Texte = ('Le canal annonce {0}, plus ancienne que {1} installée : refusé (le canal ne fait jamais redescendre ; voir RevenirVersionPrecedente).' -f $version, $Installed) }
    }
    $minimum = ConvertTo-CogesVersionKey $Channel['depuis_minimum']
    if ($current -lt $minimum) {
        return [pscustomobject]@{ Decision = 'saut'; Texte = ('{0} demande d''avoir déjà {1} au moins ; ce PC a {2} : installez d''abord {1} (-Action Reparer -Version {1}).' -f $version, $Channel['depuis_minimum'], $Installed) }
    }
    if ($Channel['docker_desktop_minimum'] -and $null -ne $DockerDesktop -and $DockerDesktop -lt [version]$Channel['docker_desktop_minimum']) {
        return [pscustomobject]@{ Decision = 'docker'; Texte = ('{0} demande Docker Desktop {1} au moins ; ce PC a {2} : mettez Docker Desktop à jour (Paramètres > Software updates).' -f $version, $Channel['docker_desktop_minimum'], $DockerDesktop) }
    }
    return [pscustomobject]@{ Decision = 'nouvelle'; Texte = ('Nouvelle version disponible : {0} (installée : {1}).' -f $version, $Installed) }
}

function Get-CogesProgrammeDigest {
    <# L'empreinte du CONTENU de deploy/onprem dans l'archive (pas du .zip, que GitHub peut
       recompresser) : sha256 du texte « <sha256>  <chemin>`n » trié par chemin. Même calcul que
       programme_digest() de publier.py (test). Mêmes fichiers que ceux qu'Install-Programme pose. #>
    param([Parameter(Mandatory)] [string] $Archive)
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $entries = New-Object 'System.Collections.Generic.List[string[]]'
    $zip = [IO.Compression.ZipFile]::OpenRead($Archive)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName -notmatch '^[^/]+/deploy/onprem/(.+)$') { continue }
            $relative = $Matches[1]
            if ($relative.EndsWith('/') -or $relative -match '(^|/)__pycache__(/|$)') { continue }
            if ($relative.Split('/') -contains '..') { throw ('Chemin refusé dans l''archive : ' + $entry.FullName) }
            $stream = $entry.Open()
            try { $hash = -join ($sha.ComputeHash($stream) | ForEach-Object { $_.ToString('x2') }) }
            finally { $stream.Dispose() }
            $entries.Add(@($relative, $hash))
        }
    }
    finally { $zip.Dispose() }
    $keys = [string[]]@($entries | ForEach-Object { $_[0] })
    $items = $entries.ToArray()
    [Array]::Sort($keys, $items, [StringComparer]::Ordinal)
    $builder = New-Object Text.StringBuilder
    foreach ($item in $items) { [void]$builder.Append($item[1]).Append('  ').Append($item[0]).Append("`n") }
    $bytes = (New-Object Text.UTF8Encoding $false).GetBytes($builder.ToString())
    $digest = -join ($sha.ComputeHash($bytes) | ForEach-Object { $_.ToString('x2') })
    $sha.Dispose()
    return [pscustomobject]@{ Sha256 = $digest; Count = $items.Count }
}

function Get-CogesRemoteDigest {
    <# Vers quel digest pointe <registre>/<image>:<étiquette> sur le registre (jeton anonyme,
       comme registry_digest() de publier.py). HttpClient : même code sous 5.1 et 7. #>
    param([Parameter(Mandatory)] [string] $Registry, [Parameter(Mandatory)] [string] $Image, [Parameter(Mandatory)] [string] $Tag)
    Add-Type -AssemblyName System.Net.Http
    $registryHost, $path = $Registry.Split('/', 2)
    $scheme = 'https'
    if ($registryHost.Split(':')[0] -in @('localhost', '127.0.0.1')) { $scheme = 'http' }
    $repository = $path + '/' + $Image
    $url = '{0}://{1}/v2/{2}/manifests/{3}' -f $scheme, $registryHost, $repository, $Tag
    $accept = 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json'
    $client = New-Object Net.Http.HttpClient
    $client.Timeout = [TimeSpan]::FromSeconds(30)
    try {
        $token = $null
        for ($attempt = 0; $attempt -lt 2; $attempt++) {
            $request = New-Object Net.Http.HttpRequestMessage ([Net.Http.HttpMethod]::Head), $url
            [void]$request.Headers.TryAddWithoutValidation('Accept', $accept)
            if ($token) { [void]$request.Headers.TryAddWithoutValidation('Authorization', 'Bearer ' + $token) }
            $response = $client.SendAsync($request).GetAwaiter().GetResult()
            $code = [int]$response.StatusCode
            if ($code -eq 401 -and -not $token) {
                $challenge = [string]$response.Headers.WwwAuthenticate
                $params = @{}
                foreach ($match in [regex]::Matches($challenge, '(\w+)="([^"]*)"')) { $params[$match.Groups[1].Value] = $match.Groups[2].Value }
                if (-not $params.ContainsKey('scope')) { $params['scope'] = 'repository:{0}:pull' -f $repository }
                $query = (@('service', 'scope') | Where-Object { $params.ContainsKey($_) } | ForEach-Object { '{0}={1}' -f $_, [Uri]::EscapeDataString($params[$_]) }) -join '&'
                $answer = $client.GetStringAsync(('{0}?{1}' -f $params['realm'], $query)).GetAwaiter().GetResult() | ConvertFrom-Json
                $token = $answer.token
                if (-not $token -and $answer.PSObject.Properties['access_token']) { $token = $answer.access_token }
                continue
            }
            if ($code -eq 404) { throw ('{0}:{1} n''existe pas sur le registre' -f $repository, $Tag) }
            if ($code -ne 200) { throw ('{0}:{1} : le registre répond {2}' -f $repository, $Tag, $code) }
            $values = $null
            if ($response.Headers.TryGetValues('Docker-Content-Digest', [ref]$values)) { return [string](@($values)[0]) }
            throw ('{0}:{1} : pas de digest dans la réponse' -f $repository, $Tag)
        }
        throw ('{0}:{1} : accès refusé par le registre' -f $repository, $Tag)
    }
    finally { $client.Dispose() }
}

function Read-CogesChannel {
    <# Le canal réglé : lu, vérifié, et la décision pour ce PC. Lève un message clair. #>
    param([Parameter(Mandatory)] [hashtable] $Settings, [Parameter(Mandatory)] $UpdateSetting)
    $source = Get-CogesChannelSource $UpdateSetting.canal
    try { $text = Read-CogesRemoteText $source }
    catch {
        Stop-CogesStep -Probleme ('Le canal « {0} » ne se lit pas ({1}).' -f $UpdateSetting.canal, $source) `
            -QuoiFaire 'Vérifiez Internet ; la vérification se refait seule deux fois par jour. Rien n''a changé.'
    }
    $parsed = ConvertFrom-CogesChannel $text
    if ($parsed.Problems.Count -gt 0) {
        Stop-CogesStep -Probleme ('Canal illisible : {0}.' -f ($parsed.Problems -join ' ; ')) `
            -QuoiFaire 'Prévenez CoGes : le fichier du canal est à republier. Rien n''a changé.'
    }
    if ([string]$parsed.Data['canal'] -cne $UpdateSetting.canal) {
        Stop-CogesStep -Probleme ('Le fichier du canal « {0} » se dit du canal « {1} ».' -f $UpdateSetting.canal, $parsed.Data['canal']) `
            -QuoiFaire 'Prévenez CoGes : le fichier du canal est à republier. Rien n''a changé.'
    }
    $docker = $null
    try { $docker = Get-CogesDockerDesktopVersion (Invoke-Docker -Arguments @('version', '--format', '{{.Server.Platform.Name}}')).Stdout } catch { $docker = $null }
    $decision = Get-CogesChannelDecision -Channel $parsed.Data -Installed $Settings['COGES_IMAGE_TAG'] -DockerDesktop $docker
    return [pscustomobject]@{ Data = $parsed.Data; Decision = $decision.Decision; Texte = $decision.Texte; Source = $source }
}

# ---------------------------------------------------------------------------- bloc B : télécharger sans gêner

function Get-CogesArchiveSource {
    <# L'archive de l'étiquette sur GitHub ; COGES_ARCHIVE_ESSAI (dossier de <version>.zip) pour les essais. #>
    param([Parameter(Mandatory)] [string] $Version)
    if ($env:COGES_ARCHIVE_ESSAI) { return (Join-Path $env:COGES_ARCHIVE_ESSAI ($Version + '.zip')) }
    return ('{0}/{1}.zip' -f $script:CogesArchiveBase, $Version)
}

function Get-CogesUpdateMinFree {
    <# 5 Go ; COGES_PLACE_MIN_ESSAI (octets) l'abaisse pour les essais sur un poste au disque plein. #>
    if ($env:COGES_PLACE_MIN_ESSAI -match '^\d+$') { return [long]$env:COGES_PLACE_MIN_ESSAI }
    return [long]$script:CogesUpdateMinFree
}

function Get-CogesFreeSpace {
    param([Parameter(Mandatory)] [string] $Path)
    return (New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Path)))).AvailableFreeSpace
}

function Test-CogesImageDigest {
    <# L'image locale <registre>/<image>:<version> vient-elle bien de ce digest ? #>
    param([Parameter(Mandatory)] [string] $Registry, [Parameter(Mandatory)] [string] $Image, [Parameter(Mandatory)] [string] $Version, [Parameter(Mandatory)] [string] $Digest)
    $inspect = Invoke-Docker -Arguments @('image', 'inspect', '--format', '{{json .RepoDigests}}', ('{0}/{1}:{2}' -f $Registry, $Image, $Version))
    if ($inspect.ExitCode -ne 0) { return $false }
    $wanted = '{0}/{1}@{2}' -f $Registry, $Image, $Digest
    return (@($inspect.Stdout) -join '').Contains('"' + $wanted + '"')
}

function Save-CogesUpdate {
    <# Bloc B : archive (empreinte du contenu), images tirées PAR DIGEST pendant que CoGes tourne,
       images d'autres éditeurs du nouveau compose ; puis « prete ». Rien de ce qui tourne ne change. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Settings, [Parameter(Mandatory)] [hashtable] $Channel, [Parameter(Mandatory)] [hashtable] $State)
    $version = [string]$Channel['version']
    $update = Get-CogesUpdatePath $Paths
    $folder = Join-Path $update.Dossier $version
    $archive = Join-Path $folder 'programme.zip'
    $registry = Get-CogesRegistryOf $Settings
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    Set-CogesVersionState -State $State -Version $version -Changes @{ etat = 'telechargement'; vue_le = (Get-Date).ToString('o'); note = [string]$Channel['note'] }
    Write-CogesUpdateState -Paths $Paths -State $State

    # 1. Le programme, vérifié à son contenu.
    $wanted = [string]$Channel['programme']['sha256']
    $good = $false
    if (Test-Path -LiteralPath $archive) { $good = ((Get-CogesProgrammeDigest $archive).Sha256 -eq $wanted) }
    if (-not $good) {
        $source = Get-CogesArchiveSource $version
        $partial = $archive + '.partiel'
        try {
            if ($source -match '^https?://') {
                $previous = $ProgressPreference
                $ProgressPreference = 'SilentlyContinue'
                try { Invoke-WebRequest -Uri $source -OutFile $partial -UseBasicParsing -TimeoutSec 600 -ErrorAction Stop }
                finally { $ProgressPreference = $previous }
            }
            else { Copy-Item -LiteralPath $source -Destination $partial -Force }
        }
        catch {
            Stop-CogesStep -Probleme ('Le programme de {0} ne se télécharge pas ({1}).' -f $version, $source) -QuoiFaire 'Rien n''a changé ; nouvel essai à la prochaine vérification.'
        }
        $digest = Get-CogesProgrammeDigest $partial
        if ($digest.Sha256 -ne $wanted -or $digest.Count -ne [long]$Channel['programme']['fichiers']) {
            Remove-Item -LiteralPath $partial -Force
            Stop-CogesStep -Probleme ('L''empreinte du programme {0} ne correspond pas au canal : téléchargement refusé.' -f $version) `
                -QuoiFaire 'Rien n''a changé. Prévenez CoGes (canal ou archive à revoir).'
        }
        Move-Item -LiteralPath $partial -Destination $archive -Force
    }
    $staged = Join-Path $folder 'programme'
    if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Recurse -Force }
    [void](Expand-CogesProgramme -Archive $archive -Destination $staged)
    Write-CogesLine ('  Programme {0} téléchargé, empreinte vérifiée.' -f $version) -Kind Ok

    # 2. Les trois images de CoGes : l'étiquette doit pointer vers le digest du canal, et l'image
    #    est tirée par ce digest (jamais par l'étiquette), puis étiquetée sur le PC.
    #    Les trois étiquettes d'abord : un canal faux ne fait rien tirer du tout.
    $missing = @($script:CogesImageNames | Where-Object { -not (Test-CogesImageDigest -Registry $registry -Image $_ -Version $version -Digest ([string]$Channel['images'][$_])) })
    foreach ($image in $missing) {
        $digest = [string]$Channel['images'][$image]
        try { $remote = Get-CogesRemoteDigest -Registry $registry -Image $image -Tag $version }
        catch { Stop-CogesStep -Probleme ('L''image {0} de {1} ne se lit pas sur le registre ({2}).' -f $image, $version, $_.Exception.Message) -QuoiFaire 'Rien n''a changé ; nouvel essai à la prochaine vérification.' }
        if ($remote -ne $digest) {
            Stop-CogesStep -Probleme ('L''étiquette {0} de l''image {1} ne pointe plus vers le digest du canal ({2} au lieu de {3}) : refusé.' -f $version, $image, $remote, $digest) `
                -QuoiFaire 'Rien n''a changé. Prévenez CoGes : une étiquette a bougé après la publication du canal.'
        }
    }
    foreach ($image in $missing) {
        $digest = [string]$Channel['images'][$image]
        $byDigest = '{0}/{1}@{2}' -f $registry, $image, $digest
        $pull = Invoke-Docker -Arguments @('pull', '--quiet', $byDigest)
        if ($pull.ExitCode -ne 0) { Stop-CogesStep -Probleme ('Le téléchargement de l''image {0} a échoué.' -f $image) -QuoiFaire 'Rien n''a changé ; ce qui est téléchargé est gardé, nouvel essai à la prochaine vérification.' }
        [void](Invoke-Docker -Arguments @('tag', $byDigest, ('{0}/{1}:{2}' -f $registry, $image, $version)))
        if (-not (Test-CogesImageDigest -Registry $registry -Image $image -Version $version -Digest $digest)) {
            Stop-CogesStep -Probleme ('L''image {0} téléchargée ne vient pas du digest du canal.' -f $image) -QuoiFaire 'Rien n''a changé. Prévenez CoGes.'
        }
    }
    Write-CogesLine '  Images front, api et worker téléchargées, digests vérifiés.' -Kind Ok

    # 3. Les images d'autres éditeurs que le nouveau compose demande (Caddy, PostgreSQL…),
    #    seulement celles qui manquent : le plus souvent elles n'ont pas changé.
    $compose = Join-Path $staged 'docker-compose.yml'
    $pull = Invoke-Docker -Arguments (@('compose', '--env-file', $Paths.EnvFile, '-f', $compose, '--profile', 'tools', 'pull', '--quiet', '--policy', 'missing') + $script:CogesThirdPartyServices)
    if ($pull.ExitCode -ne 0) { Stop-CogesStep -Probleme 'Les images d''accompagnement (Caddy, PostgreSQL, Redis) ne se téléchargent pas.' -QuoiFaire 'Rien n''a changé ; nouvel essai à la prochaine vérification.' }

    # 4. Place : 5 Go libres après le téléchargement (la copie de la base et la sauvegarde viennent ensuite).
    $free = Get-CogesFreeSpace $Paths.Racine
    if ($free -lt (Get-CogesUpdateMinFree)) {
        Stop-CogesStep -Probleme ('Il ne reste que {0:N1} Go libres après le téléchargement ; la mise à jour en demande 5.' -f ($free / 1GB)) `
            -QuoiFaire 'Libérez de la place sur le disque du PC ; la mise à jour se fera ensuite. Rien n''a changé.'
    }
    Set-CogesVersionState -State $State -Version $version -Changes @{ etat = 'prete'; prete_le = (Get-Date).ToString('o'); digests = $Channel['images'] }
    Write-CogesUpdateState -Paths $Paths -State $State
    Write-CogesLine ('  {0} prête à appliquer.' -f $version) -Kind Ok
}

function Select-CogesImageToRemove {
    <# Les versions dont les images peuvent partir : plus de deux versions en arrière. Jamais
       celle en service, ni la précédente, ni une plus récente (prête ou à l'essai). #>
    param([AllowEmptyCollection()] [string[]] $Tags = @(), [Parameter(Mandatory)] [string] $Current)
    $current = ConvertTo-CogesVersionKey $Current
    if ($null -eq $current) { return @() }
    $older = @($Tags | Where-Object { $k = ConvertTo-CogesVersionKey $_; $null -ne $k -and $k -lt $current } | Sort-Object { ConvertTo-CogesVersionKey $_ } -Descending -Unique)
    if ($older.Count -le 1) { return @() }
    return @($older | Select-Object -Skip 1)
}

function Remove-CogesOldImage {
    <# Bloc B : les images de plus de deux versions en arrière. N'échoue jamais (journal). #>
    param([Parameter(Mandatory)] [hashtable] $Settings)
    try {
        $registry = Get-CogesRegistryOf $Settings
        foreach ($image in $script:CogesImageNames) {
            $tags = @((Invoke-Docker -Arguments @('image', 'ls', ('{0}/{1}' -f $registry, $image), '--format', '{{.Tag}}')).Stdout | Where-Object { $_ })
            foreach ($tag in (Select-CogesImageToRemove -Tags $tags -Current $Settings['COGES_IMAGE_TAG'])) {
                $removed = Invoke-Docker -Arguments @('image', 'rm', ('{0}/{1}:{2}' -f $registry, $image, $tag))
                Write-Log -Message ('image {0}:{1} retirée (code {2})' -f $image, $tag, $removed.ExitCode)
            }
        }
    }
    catch { Write-Log -Message ('images anciennes : ' + $_.Exception.Message) -Level ATTENTION }
}

function Invoke-CogesUpdateCheck {
    <# Lit le canal ; une nouvelle version est téléchargée et vérifiée (« prete »). Rend la
       décision. Une version en échec ou annulée n'est jamais reprise seule (ADR 0128). #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $State)
    $settings = Get-CogesSetting $Paths
    $setting = Read-CogesUpdateSetting $Paths
    $State['derniere_verification'] = (Get-Date).ToString('o')
    try { $channel = Read-CogesChannel -Settings $settings -UpdateSetting $setting }
    catch {
        $State['derniere_verification_texte'] = (Mask-Secrets ($_.Exception.Message.Split("`n")[0]))
        Write-CogesUpdateState -Paths $Paths -State $State
        throw
    }
    $State['derniere_verification_texte'] = $channel.Texte
    $State['disponible'] = @{ version = [string]$channel.Data['version']; note = [string]$channel.Data['note']; publiee_le = [string]$channel.Data['publiee_le']; canal = $setting.canal }
    Write-CogesUpdateState -Paths $Paths -State $State
    Write-CogesLine ('  ' + $channel.Texte) -Kind $(if ($channel.Decision -in @('a-jour', 'nouvelle')) { 'Ok' } else { 'Attention' })
    if ($channel.Decision -ne 'nouvelle') { return $channel }
    $version = [string]$channel.Data['version']
    $known = Get-CogesVersionState -State $State -Version $version
    if ($known -and $known['etat'] -in @('echec', 'annulee')) {
        Write-CogesLine ('  {0} est marquée « {1} » sur ce PC : elle ne s''applique plus seule (-Action MettreAJour -Maintenant pour la forcer).' -f $version, $known['etat']) -Kind Attention
        return $channel
    }
    if ($known -and $known['etat'] -eq 'prete' -and (Test-Path -LiteralPath (Join-Path (Join-Path (Get-CogesUpdatePath $Paths).Dossier $version) 'programme.zip'))) {
        Write-CogesLine ('  {0} est déjà téléchargée.' -f $version) -Kind Ok
        return $channel
    }
    # Une version plus ancienne prête, dépassée par celle-ci : elle n'est plus proposée.
    foreach ($other in @($State['versions'].Keys)) {
        if ($other -ne $version -and $State['versions'][$other]['etat'] -eq 'prete') { Set-CogesVersionState -State $State -Version $other -Changes @{ etat = 'remplacee' } }
    }
    $saved = $false
    try { Save-CogesUpdate -Paths $Paths -Settings $settings -Channel $channel.Data -State $State; $saved = $true }
    finally {
        if (-not $saved) {
            Set-CogesVersionState -State $State -Version $version -Changes @{ etat = 'vue'; dernier_telechargement_rate = (Get-Date).ToString('o') }
            Write-CogesUpdateState -Paths $Paths -State $State
        }
    }
    Remove-CogesOldImage -Settings $settings
    return $channel
}

# ---------------------------------------------------------------------------- bloc C : quand appliquer (fonctions pures)

function Test-CogesApplyDue {
    <# La tâche du soir applique-t-elle maintenant ? Entre l'heure réglée et deux heures après,
       PC allumé depuis 15 minutes au moins (jamais au démarrage), aucune vente depuis 30
       minutes, réglage automatique. Rend Due et, sinon, Motif et Texte (pour Etat). #>
    param(
        [Parameter(Mandatory)] [datetime] $Now,
        [Parameter(Mandatory)] [string] $Heure,
        [AllowNull()] $BootTime = $null,
        [AllowNull()] $LastActivity = $null,
        [bool] $Automatique = $true
    )
    if (-not $Automatique) { return [pscustomobject]@{ Due = $false; Motif = 'manuel'; Texte = 'mise à jour automatique coupée (mise-a-jour.json)' } }
    $parts = $Heure.Split(':')
    $start = $Now.Date.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
    if ($Now -lt $start) { $start = $start.AddDays(-1) }
    if ($Now -ge $start.AddMinutes($script:CogesUpdateWindowMinutes)) {
        return [pscustomobject]@{ Due = $false; Motif = 'hors-heure'; Texte = ('en attente de {0}' -f $Heure) }
    }
    if ($null -ne $BootTime -and ($Now - [datetime]$BootTime).TotalMinutes -lt $script:CogesBootMinutes) {
        return [pscustomobject]@{ Due = $false; Motif = 'demarrage'; Texte = 'PC allumé depuis moins de 15 minutes (jamais au démarrage)' }
    }
    $quiet = Test-CogesQuiet -Now $Now -LastActivity $LastActivity
    if (-not $quiet.Due) { return $quiet }
    return [pscustomobject]@{ Due = $true; Motif = ''; Texte = '' }
}

function Test-CogesQuiet {
    <# Aucune vente créée, modifiée ou confirmée depuis 30 minutes ? #>
    param([Parameter(Mandatory)] [datetime] $Now, [AllowNull()] $LastActivity = $null)
    if ($null -ne $LastActivity) {
        $minutes = ($Now - [datetime]$LastActivity).TotalMinutes
        if ($minutes -lt $script:CogesQuietMinutes) {
            return [pscustomobject]@{ Due = $false; Motif = 'vente'; Texte = ('une vente il y a {0} minute(s) : on attend 30 minutes sans vente' -f [int][Math]::Max(0, [Math]::Floor($minutes))) }
        }
    }
    return [pscustomobject]@{ Due = $true; Motif = ''; Texte = '' }
}

function Get-CogesUpdateWait {
    <# Depuis combien de jours une version prête attend, et pourquoi (Etat, raccourci du bloc
       « 3 jours »). Sans essai lors de la dernière heure prévue : PC éteint ou en veille. #>
    param([Parameter(Mandatory)] [hashtable] $Entry, [Parameter(Mandatory)] [datetime] $Now, [Parameter(Mandatory)] [string] $Heure)
    $ready = ConvertTo-CogesStateDate $Entry['prete_le']
    $days = 0
    if ($ready) { $days = [int][Math]::Floor(($Now - $ready).TotalDays) }
    $parts = $Heure.Split(':')
    $slot = $Now.Date.AddHours([int]$parts[0]).AddMinutes([int]$parts[1])
    if ($slot -gt $Now) { $slot = $slot.AddDays(-1) }
    $reason = 'pas encore passée par l''heure prévue'
    if ($ready -and $slot -lt $ready) { $reason = ('prête depuis peu ; prochaine heure prévue : {0}' -f $Heure) }
    else {
        $tried = ConvertTo-CogesStateDate $Entry['dernier_essai']
        if ($null -eq $tried -or $tried -lt $slot) { $reason = ('PC éteint ou en veille à {0}' -f $Heure) }
        elseif ($Entry['dernier_motif_texte']) { $reason = [string]$Entry['dernier_motif_texte'] }
    }
    return [pscustomobject]@{ Days = $days; Reason = $reason; Manual = ($days -ge $script:CogesManualAfterDays) }
}

function Get-CogesBootTime {
    if (-not (Test-CogesWindows)) { return $null }
    try { return (Get-CimInstance Win32_OperatingSystem).LastBootUpTime } catch { return $null }
}

# ---------------------------------------------------------------------------- bloc C : appliquer

function Get-CogesMissingSetting {
    <# Les lignes que le modèle de la nouvelle version a et que coges.env n'a pas : ajoutées
       avec leur valeur par défaut documentée ; un secret manquant est un refus (jamais inventé). #>
    param([Parameter(Mandatory)] [string] $ModelText, [Parameter(Mandatory)] [System.Collections.IDictionary] $Values)
    $additions = [ordered]@{}
    $secrets = New-Object System.Collections.Generic.List[string]
    foreach ($raw in ($ModelText -split "`r?`n")) {
        if ($raw -notmatch '^\s*([A-Z0-9_]+)\s*=(.*)$') { continue }
        $key = $Matches[1]
        $value = $Matches[2].Trim()
        if ($Values.Contains($key)) { continue }
        if ((@($script:CogesSecretKeys) + $script:CogesMfaKey) -contains $key -or -not $value) { $secrets.Add($key) }
        else { $additions[$key] = $value }
    }
    return [pscustomobject]@{ Additions = $additions; Secrets = $secrets.ToArray() }
}

function ConvertTo-CogesEditedEnvText {
    <# Le texte de coges.env avec des lignes changées (liste blanche) et d'autres ajoutées à la
       fin ; tout le reste à l'identique, fins de ligne gardées. #>
    param(
        [Parameter(Mandatory)] [string] $Text,
        [System.Collections.IDictionary] $Values = @{},
        [System.Collections.IDictionary] $Additions = @{}
    )
    foreach ($key in $Values.Keys) {
        if ($script:CogesEditableKeys -notcontains $key) { throw ('Le script ne change jamais ' + $key + ' dans coges.env.') }
    }
    $newline = "`n"
    if ($Text.Contains("`r`n")) { $newline = "`r`n" }
    $pending = @{}
    foreach ($key in $Values.Keys) { $pending[$key] = $true }
    $lines = foreach ($raw in ($Text -split "`r?`n")) {
        if ($raw -match '^\s*([A-Z0-9_]+)\s*=' -and $Values.Contains($Matches[1])) {
            $pending.Remove($Matches[1])
            $Matches[1] + '=' + $Values[$Matches[1]]
        }
        else { $raw }
    }
    $result = ($lines -join $newline).TrimEnd("`r", "`n") + $newline
    foreach ($key in $pending.Keys) { $result += $key + '=' + $Values[$key] + $newline }
    if ($Additions.Count -gt 0) {
        $result += '# Ajouté par la mise à jour (valeur par défaut du modèle).' + $newline
        foreach ($key in $Additions.Keys) { $result += $key + '=' + $Additions[$key] + $newline }
    }
    return $result
}

function Write-CogesEnvAtomic {
    <# coges.env remplacé d'un coup (jamais à moitié écrit), droits restreints reposés sous Windows. #>
    param([Parameter(Mandatory)] [string] $Path, [Parameter(Mandatory)] [string] $Text)
    $temporary = $Path + '.nouveau'
    [IO.File]::WriteAllText($temporary, $Text, (New-Object Text.UTF8Encoding $false))
    if (Test-Path -LiteralPath $Path) { [IO.File]::Replace($temporary, $Path, [NullString]::Value) }
    else { Move-Item -LiteralPath $temporary -Destination $Path }
    if (Test-CogesWindows) { Set-CogesPrivateAcl $Path }
}

function Get-CogesCount {
    <# base.py compter : sociétés, ventes, codes, dernière activité de vente. #>
    param([Parameter(Mandatory)] $Paths, [AllowEmptyString()] [string] $Since = '')
    $arguments = @('base.py', 'compter')
    if ($Since) { $arguments += @('--depuis', $Since) }
    return Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Lecture de la base (sociétés, ventes)' -Arguments $arguments).Stdout
}

function Invoke-CogesNewSettingCheck {
    <# Étape 3 : check_onprem_env.py du NOUVEAU programme, dans la NOUVELLE image worker, contre
       les réglages actuels (plus les lignes ajoutées), par l'entrée standard : aucun fichier
       temporaire de secrets. #>
    param([Parameter(Mandatory)] [string] $Programme, [Parameter(Mandatory)] [string] $Image, [Parameter(Mandatory)] [string] $EnvText)
    $result = Invoke-Docker -Arguments @('run', '--rm', '-i', '--network', 'none', '-v', ((Get-CogesDockerMountPath $Programme) + ':/onprem:ro'),
        '--entrypoint', 'python', $Image, '/onprem/check_onprem_env.py', '--env-file', '/dev/stdin') -InputText $EnvText
    foreach ($line in $result.Output) { if ($line -match '^REFUS') { Write-CogesLine ('  ' + $line) -Kind Attention } }
    if ($result.ExitCode -ne 0) {
        Stop-CogesStep -Probleme 'La nouvelle version refuse les réglages de ce PC (lignes REFUS ci-dessus).' `
            -QuoiFaire 'Rien n''a changé. Envoyez le journal à CoGes.'
    }
}

function Restore-CogesProgrammeFolder {
    <# Le programme précédent remis en place ; celui qu'il remplace est écarté (.echec). #>
    param([Parameter(Mandatory)] $Paths)
    $update = Get-CogesUpdatePath $Paths
    if (-not (Test-Path -LiteralPath $update.Precedent)) { throw 'programme précédent absent' }
    if (Test-Path -LiteralPath $update.Echec) { Remove-Item -LiteralPath $update.Echec -Recurse -Force }
    if (Test-Path -LiteralPath $Paths.Programme) { Rename-Item -LiteralPath $Paths.Programme -NewName (Split-Path -Leaf $update.Echec) }
    Rename-Item -LiteralPath $update.Precedent -NewName (Split-Path -Leaf $Paths.Programme)
}

function Test-CogesUpdatedSite {
    <# Étape 7 (et après un retour) : services, page d'accueil, administration, licence, et les
       mêmes nombres de sociétés et de ventes qu'avant. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] $Before)
    Wait-CogesHealthy -Paths $Paths
    Test-CogesSite -Url (Get-CogesSetting $Paths)['COGES_PUBLIC_URL']
    $after = Get-CogesCount -Paths $Paths
    if ([long]$after.societes -ne [long]$Before.societes -or [long]$after.ventes -ne [long]$Before.ventes) {
        throw ('données différentes : {0} société(s) et {1} vente(s) avant, {2} et {3} après' -f $Before.societes, $Before.ventes, $after.societes, $after.ventes)
    }
    foreach ($slug in @($Before.boutiques)) {
        $status = Get-CogesLicenseStatus -Paths $Paths -Slug ([string]$slug)
        if (-not (Test-CogesLicenseActive $status.Output)) { throw ('la licence de {0} ne se relit pas « actif, sans fin »' -f $slug) }
    }
    Write-CogesLine ('  {0} société(s), {1} vente(s) : identiques ; licence active ; page d''accueil en 200.' -f $after.societes, $after.ventes) -Kind Ok
}

function Install-CogesTasksAgain {
    <# Étape 7 : les trois tâches planifiées reposées (les scripts ont pu changer). Windows seulement. #>
    param([Parameter(Mandatory)] $Paths)
    if (-not (Test-CogesWindows)) { Write-Log -Message 'tâches planifiées : hors Windows, rien à reposer'; return }
    Install-CogesStartupTask -Paths $Paths
    Install-CogesBackupTask -Paths $Paths
    Install-CogesUpdateTask -Paths $Paths
}

function Undo-CogesUpdate {
    <# Étape 8 : retour automatique. Ancien programme, ancien coges.env (à l'octet), copie de la
       base remise (la base en échec gardée sous coges_echec_maj_H), démarrage, vérifications. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Context)
    [void](Invoke-CogesCompose -Paths $Paths -Arguments (@('stop') + $script:CogesApplicationServices))
    if ($Context.ProgrammeSwapped) { Restore-CogesProgrammeFolder $Paths }
    if ($Context.EnvChanged) { Write-CogesEnvAtomic -Path $Paths.EnvFile -Text $Context.OldEnvText }
    [void](Get-CogesSetting $Paths)
    if ($Context.Copy) {
        [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Retour à la base d''avant la mise à jour' -Arguments @('base.py', 'remettre', $Context.Copy, '--ecarter', 'echec'))
    }
    $up = Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans')
    if ($up.ExitCode -ne 0) { throw 'le redémarrage de l''ancienne version a échoué' }
    Test-CogesUpdatedSite -Paths $Paths -Before $Context.Before
}

function Invoke-CogesUpdateLocked {
    <# Bloc C, étapes 1 à 9, verrou tenu. Avant l'étape 4, rien n'a changé ; un échec aux étapes
       6 ou 7 ramène seul l'état d'avant, données comprises. Rend « appliquee » ou lève. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $State, [Parameter(Mandatory)] [string] $Version, [switch] $Force, [Nullable[datetime]] $Now = $null)
    if ($null -eq $Now) { $Now = Get-Date }
    $settings = Get-CogesSetting $Paths
    $from = [string]$settings['COGES_IMAGE_TAG']
    $update = Get-CogesUpdatePath $Paths
    $folder = Join-Path $update.Dossier $Version
    $archive = Join-Path $folder 'programme.zip'
    $staged = Join-Path $folder 'programme'
    $registry = Get-CogesRegistryOf $settings
    $watch = [Diagnostics.Stopwatch]::StartNew()
    Set-CogesVersionState -State $State -Version $Version -Changes @{ dernier_essai = $Now.ToString('o') }

    # 1. Conditions.
    Write-CogesLine ('» 1. Conditions : {0} prête, Docker, place, calme' -f $Version) -Kind Titre
    if (-not (Test-Path -LiteralPath $archive) -or -not (Test-Path -LiteralPath (Join-Path $staged 'docker-compose.yml'))) {
        Stop-CogesStep -Probleme ('{0} n''est pas téléchargée sur ce PC.' -f $Version) -QuoiFaire 'Lancez -Action VerifierMiseAJour, puis relancez. Rien n''a changé.'
    }
    $entry = Get-CogesVersionState -State $State -Version $Version
    foreach ($image in $script:CogesImageNames) {
        if (-not $entry -or -not $entry['digests'] -or -not (Test-CogesImageDigest -Registry $registry -Image $image -Version $Version -Digest ([string]$entry['digests'][$image]))) {
            Stop-CogesStep -Probleme ('L''image {0} de {1} manque ou ne vient pas du digest du canal.' -f $image, $Version) -QuoiFaire 'Lancez -Action VerifierMiseAJour, puis relancez. Rien n''a changé.'
        }
    }
    Assert-CogesDockerRunning
    $free = Get-CogesFreeSpace $Paths.Racine
    if ($free -lt (Get-CogesUpdateMinFree)) {
        Stop-CogesStep -Probleme ('Il ne reste que {0:N1} Go libres ; la mise à jour en demande 5.' -f ($free / 1GB)) -QuoiFaire 'Libérez de la place sur le disque du PC, puis relancez. Rien n''a changé.'
    }
    $count = Get-CogesCount -Paths $Paths
    if (-not $Force) {
        $quiet = Test-CogesQuiet -Now $Now -LastActivity (ConvertTo-CogesStateDate $count.derniere_activite)
        if (-not $quiet.Due) {
            Set-CogesVersionState -State $State -Version $Version -Changes @{ dernier_motif = $quiet.Motif; dernier_motif_texte = $quiet.Texte }
            Stop-CogesStep -Probleme ('Pas maintenant : {0}.' -f $quiet.Texte) -QuoiFaire 'Rien n''a changé. Relancez plus tard, ou avec -Maintenant si la boutique est fermée.'
        }
    }
    Write-CogesLine '  Tout est prêt.' -Kind Ok

    # 2. Sauvegarde chiffrée, copiée sur la clé si elle est branchée.
    Write-CogesLine '» 2. Sauvegarde chiffrée avant la mise à jour' -Kind Titre
    $backup = New-CogesBackup -Paths $Paths -Raison 'avant-maj' -Now $Now
    Write-CogesLine ('  {0}' -f $backup.Path) -Kind Ok

    # 3. Contrôle à blanc des réglages par la nouvelle version (lignes ajoutées à l'étape 6 seulement).
    Write-CogesLine '» 3. Contrôle des réglages par la nouvelle version' -Kind Titre
    $oldText = [IO.File]::ReadAllText($Paths.EnvFile)
    $missing = Get-CogesMissingSetting -ModelText ([IO.File]::ReadAllText((Join-Path $staged 'coges.env.example'))) -Values $settings
    if ($missing.Secrets.Count -gt 0) {
        Stop-CogesStep -Probleme ('La nouvelle version demande des réglages secrets absents de coges.env : {0}.' -f ($missing.Secrets -join ', ')) `
            -QuoiFaire 'Rien n''a changé. Appelez CoGes : un secret ne s''invente pas en silence.'
    }
    foreach ($key in $missing.Additions.Keys) { Write-CogesLine ('  Ligne ajoutée à l''étape 6 : {0}={1} (valeur par défaut du modèle)' -f $key, $missing.Additions[$key]) -Kind Attention }
    $newText = ConvertTo-CogesEditedEnvText -Text $oldText -Values ([ordered]@{ COGES_IMAGE_TAG = $Version }) -Additions $missing.Additions
    Invoke-CogesNewSettingCheck -Programme $staged -Image ('{0}/worker:{1}' -f $registry, $Version) -EnvText $newText
    Write-CogesLine '  Réglages acceptés par la nouvelle version.' -Kind Ok

    # 4. Page de maintenance : l'application s'arrête (Caddy, PostgreSQL et Redis restent).
    $context = @{ ProgrammeSwapped = $false; EnvChanged = $false; Copy = $null; OldEnvText = $oldText; Before = $null }
    Write-CogesLine '» 4. Arrêt de l''application (page « CoGes revient dans un instant »)' -Kind Titre
    $stop = Invoke-CogesCompose -Paths $Paths -Arguments (@('stop') + $script:CogesApplicationServices)
    if ($stop.ExitCode -ne 0) {
        [void](Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d'))
        Stop-CogesStep -Probleme 'L''application ne s''arrête pas.' -QuoiFaire 'Rien n''a changé ; CoGes est relancé. Relancez plus tard.'
    }
    try {
        # 5. Copie locale de la base, application arrêtée : le retour arrière sans la clé privée.
        Write-CogesLine '» 5. Copie de la base dans PostgreSQL (retour possible sans la clé privée)' -Kind Titre
        $context.Before = Get-CogesCount -Paths $Paths
        # Une nouvelle mise à jour remplace le point de retour de la précédente.
        foreach ($old in @(Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Anciennes copies' -Arguments @('base.py', 'copies')).Stdout)) {
            if ($old -and $old.nom) { [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What ('Suppression de ' + $old.nom) -Arguments @('base.py', 'supprimer', [string]$old.nom)) }
        }
        if ($State['derniere_maj'] -is [hashtable]) { $State['derniere_maj']['copie'] = $null }
        $stamp = $Now.ToString('yyyyMMdd_HHmmss')
        [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Copie de la base' -Arguments @('base.py', 'copier', $stamp))
        $context.Copy = $stamp
        Write-CogesLine ('  coges_avant_maj_{0} : {1} société(s), {2} vente(s).' -f $stamp, $context.Before.societes, $context.Before.ventes) -Kind Ok
    }
    catch {
        [void](Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d'))
        Stop-CogesStep -Probleme ('La copie de la base a échoué ({0}).' -f $_.Exception.Message.Split("`n")[0]) -QuoiFaire 'Rien n''a changé ; CoGes est relancé. Envoyez le journal à CoGes.'
    }

    try {
        # 6. Programme, version, base, démarrage.
        Write-CogesLine ('» 6. Programme {0}, réglage de la version, migrations, démarrage' -f $Version) -Kind Titre
        [void](Install-Programme -Archive $archive -Racine $Paths.Racine -Version $Version -GarderPrecedent)
        $context.ProgrammeSwapped = $true
        Write-CogesEnvAtomic -Path $Paths.EnvFile -Text $newText
        $context.EnvChanged = $true
        [void](Get-CogesSetting $Paths)
        $migrate = Invoke-CogesCompose -Paths $Paths -Arguments @('--profile', 'tools', 'run', '--rm', '-T', 'migrate')
        if ($migrate.ExitCode -ne 0) {
            foreach ($line in ($migrate.Output | Select-Object -Last 8)) { Write-CogesLine ('    ' + $line) }
            throw 'les migrations de la nouvelle version ont échoué'
        }
        $up = Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans')
        if ($up.ExitCode -ne 0) { throw 'le démarrage de la nouvelle version a échoué' }

        # 7. Vérifications.
        Write-CogesLine '» 7. Vérifications' -Kind Titre
        Test-CogesUpdatedSite -Paths $Paths -Before $context.Before
        Install-CogesTasksAgain $Paths
    }
    catch {
        # 8. Retour arrière automatique.
        $reason = $_.Exception.Message.Split("`n")[0]
        Write-CogesLine ('Échec ({0}) : retour automatique à {1}.' -f $reason, $from) -Kind Echec
        Set-CogesVersionState -State $State -Version $Version -Changes @{ etat = 'echec'; echec_le = (Get-Date).ToString('o'); raison = (Mask-Secrets $reason) }
        $State['derniere_maj'] = @{ de = $from; vers = $Version; le = $Now.ToString('o'); resultat = 'revenue'; raison = (Mask-Secrets $reason); copie = $null }
        Write-CogesUpdateState -Paths $Paths -State $State
        try { Undo-CogesUpdate -Paths $Paths -Context $context }
        catch {
            $text = 'La mise à jour vers {0} a échoué et le retour à {1} aussi. Appelez CoGes.' -f $Version, $from
            Show-CogesToast $text | Out-Null
            [void](Send-CogesPing -Paths $Paths -Signal 'mise-a-jour' -Failure -Reason 'retour-rate')
            Stop-CogesStep -Probleme ('{0} ({1} ; puis {2})' -f $text, $reason, $_.Exception.Message.Split("`n")[0]) `
                -QuoiFaire ('N''effacez rien. La sauvegarde {0} et la copie coges_avant_maj_{1} (ou coges_echec_maj_{1}) sont gardées.' -f $backup.Name, $context.Copy)
        }
        Set-CogesUpdateShortcut -Paths $Paths -Present $false
        # Lot 6 : CoGes est prévenu tout de suite (si la remontée est active et Internet là).
        $told = Send-CogesPing -Paths $Paths -Signal 'mise-a-jour' -Failure -Reason 'retour-arriere'
        $text = 'La mise à jour vers {0} a échoué ; CoGes est revenu à {1}. Rien n''est perdu.' -f $Version, $from
        if ($told) { $text += ' CoGes est prévenu.' }
        Show-CogesToast $text | Out-Null
        Stop-CogesStep -Probleme $text -QuoiFaire ('Rien à faire tout de suite. {0} ne se réessaie plus seule ; envoyez le journal à CoGes.' -f $Version)
    }

    # 9. Réussite : la copie et l'ancien programme sont gardés 7 jours.
    $minutes = [Math]::Max(1, [int][Math]::Ceiling($watch.Elapsed.TotalMinutes))
    Set-CogesVersionState -State $State -Version $Version -Changes @{ etat = 'appliquee'; appliquee_le = (Get-Date).ToString('o') }
    $State['derniere_maj'] = @{ de = $from; vers = $Version; le = $Now.ToString('o'); resultat = 'reussie'; copie = $context.Copy
        copie_fin = $Now.AddDays($script:CogesKeepDays).ToString('o'); minutes = $minutes; sauvegarde = $backup.Name
        societes = [long]$context.Before.societes; ventes = [long]$context.Before.ventes }
    Write-CogesUpdateState -Paths $Paths -State $State
    if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Recurse -Force }
    Set-CogesUpdateShortcut -Paths $Paths -Present $false
    Remove-CogesOldImage -Settings (Get-CogesSetting $Paths)
    [void](Send-CogesPing -Paths $Paths -Signal 'mise-a-jour')
    Write-CogesLine ('CoGes est à jour ({0}), en {1} minute(s). Retour possible jusqu''au {2} (-Action RevenirVersionPrecedente).' -f $Version, $minutes, $Now.AddDays($script:CogesKeepDays).ToString('dd/MM/yyyy')) -Kind Ok
    return 'appliquee'
}

function Invoke-CogesUpdateCleanup {
    <# Bloc C, étape 9 : après 7 jours, la copie de la base et l'ancien programme sont supprimés
       (jamais avant). N'échoue jamais. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $State, [Parameter(Mandatory)] [datetime] $Now)
    $last = $State['derniere_maj']
    if (-not ($last -is [hashtable]) -or -not $last['copie']) { return }
    $end = ConvertTo-CogesStateDate $last['copie_fin']
    if ($null -eq $end -or $Now -lt $end) { return }
    try {
        [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Copie d''avant la mise à jour' -Arguments @('base.py', 'supprimer', ('coges_avant_maj_' + $last['copie'])))
        $update = Get-CogesUpdatePath $Paths
        foreach ($folder in @($update.Precedent, $update.Echec)) { if (Test-Path -LiteralPath $folder) { Remove-Item -LiteralPath $folder -Recurse -Force } }
        $last['copie'] = $null
        Write-CogesUpdateState -Paths $Paths -State $State
        Write-Log -Message ('7 jours passés : copie coges_avant_maj_* et ancien programme ({0}) supprimés' -f $last['de']) -Level OK
    }
    catch { Write-Log -Message ('nettoyage des 7 jours : ' + $_.Exception.Message) -Level ATTENTION }
}

# ---------------------------------------------------------------------------- le raccourci des 3 jours

function Get-CogesDesktopPath {
    if ($env:COGES_BUREAU_ESSAI) { return $env:COGES_BUREAU_ESSAI }
    return [Environment]::GetFolderPath('Desktop')
}

function New-CogesUpdateShortcutText {
    <# Le raccourci « Mettre CoGes à jour » : une fenêtre visible, -Action MettreAJour -Maintenant -Bureau. #>
    param([Parameter(Mandatory)] $Paths)
    $script = Join-Path $Paths.Programme 'windows\installer.ps1'
    return ("@echo off`r`nrem CoGes : mettre a jour quand la boutique est calme (ADR 0128).`r`n" +
        ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Action MettreAJour -Maintenant -Bureau -Racine "{1}"' -f $script, $Paths.Racine) + "`r`n")
}

function Set-CogesUpdateShortcut {
    <# Posé quand une version attend depuis 3 jours, retiré quand elle est appliquée ou annulée. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [bool] $Present)
    try {
        $desktop = Get-CogesDesktopPath
        if (-not $desktop) { return }
        $file = Join-Path $desktop $script:CogesUpdateShortcut
        if ($Present) {
            New-Item -ItemType Directory -Force -Path $desktop | Out-Null
            [IO.File]::WriteAllText($file, (New-CogesUpdateShortcutText $Paths), [Text.Encoding]::ASCII)
        }
        elseif (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
    }
    catch { Write-Log -Message ('raccourci de mise à jour : ' + $_.Exception.Message) -Level ATTENTION }
}

function Invoke-CogesManualReminder {
    <# Une version prête attend depuis 3 jours : raccourci sur le Bureau, et un rappel par jour au plus. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $State, [Parameter(Mandatory)] [datetime] $Now, [Parameter(Mandatory)] [string] $Heure)
    $version = Get-CogesReadyVersion $State
    if (-not $version) { Set-CogesUpdateShortcut -Paths $Paths -Present $false; return $false }
    $wait = Get-CogesUpdateWait -Entry (Get-CogesVersionState -State $State -Version $version) -Now $Now -Heure $Heure
    if (-not $wait.Manual) { return $false }
    Set-CogesUpdateShortcut -Paths $Paths -Present $true
    [void](Send-CogesUpdateWaitPing -Paths $Paths -Now $Now)
    $today = $Now.ToString('yyyy-MM-dd')
    if ($State['dernier_rappel'] -eq $today) { return $false }
    [void](Show-CogesToast 'Une mise à jour de CoGes est prête. Quand vous avez 5 minutes sans client, double-cliquez sur « Mettre CoGes à jour » sur le Bureau.')
    $State['dernier_rappel'] = $today
    Write-CogesUpdateState -Paths $Paths -State $State
    return $true
}

# ---------------------------------------------------------------------------- tâche planifiée

function Install-CogesStartupTask {
    <# « CoGes - démarrage » seule (Install-CogesComfort la pose avec le reste). #>
    param([Parameter(Mandatory)] $Paths)
    $launcher = Join-Path $Paths.Programme 'windows\demarrage.ps1'
    $argument = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Racine "{1}"' -f $launcher, $Paths.Racine
    $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
    Register-ScheduledTask -TaskName $script:CogesTaskName -Action (New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument) `
        -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $user) -Principal (New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited) -Settings $settings -Force | Out-Null
}

function Install-CogesUpdateTask {
    <# « CoGes - mise à jour » : vérifie le canal à 12 h, 18 h et à l'ouverture de session
       (+10 min), et passe à l'heure réglée pour appliquer. Même style que les deux autres :
       utilisateur courant, sans élévation, fenêtre cachée. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans le bloc de l''étape (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths)
    $hour = (Read-CogesUpdateSetting $Paths).heure
    Invoke-CogesStep -Title ('Tâche planifiée « {0} » (canal à 12 h et 18 h, application à {1})' -f $script:CogesUpdateTaskName, $hour) -Action {
        $launcher = Join-Path $Paths.Programme 'windows\mise-a-jour.ps1'
        $argument = '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}" -Racine "{1}"' -f $launcher, $Paths.Racine
        $user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        $triggers = @()
        foreach ($slot in (@($script:CogesUpdateCheckSlots) + $hour)) { $triggers += New-ScheduledTaskTrigger -Daily -At $slot }
        $logon = New-ScheduledTaskTrigger -AtLogOn -User $user
        $logon.Delay = 'PT10M'
        $triggers += $logon
        $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2)
        Register-ScheduledTask -TaskName $script:CogesUpdateTaskName -Action (New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argument) `
            -Trigger $triggers -Principal $principal -Settings $settings -Force | Out-Null
    }
}

function Remove-CogesUpdateTask {
    param([Parameter(Mandatory)] $Paths)
    Invoke-CogesStep -Title ('Tâche planifiée « {0} » et raccourci de mise à jour retirés' -f $script:CogesUpdateTaskName) -Action {
        if (Get-ScheduledTask -TaskName $script:CogesUpdateTaskName -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $script:CogesUpdateTaskName -Confirm:$false
        }
    }
    if (-not $script:CogesState.Simulation) { Set-CogesUpdateShortcut -Paths $Paths -Present $false }
}

function Invoke-CogesScheduledUpdate {
    <# La tâche « CoGes - mise à jour » : sans question ni fenêtre ; journal
       mise-a-jour-AAAAMMJJ.log ; jamais d'exception. Nettoie après 7 jours, lit le canal (et
       télécharge), applique si c'est l'heure et que la boutique est calme, rappelle au bout de 3 jours. #>
    param([Parameter(Mandatory)] [string] $Racine, [int] $LockWaitSeconds = 1800, [Nullable[datetime]] $Now = $null)
    if ($null -eq $Now) { $Now = Get-Date }
    $paths = Get-CogesPath $Racine
    $script:CogesState.NonInteractif = $true
    New-Item -ItemType Directory -Force -Path $paths.Journaux | Out-Null
    $script:CogesState.LogPath = Join-Path $paths.Journaux ('mise-a-jour-{0}.log' -f $Now.ToString('yyyyMMdd'))
    if (-not (Test-Path -LiteralPath $paths.EnvFile)) { Write-Log -Message 'CoGes n''est pas installé : rien à faire.'; return 0 }
    [void](Get-CogesSetting $paths)
    if ($null -ne (Get-CogesDockerEngineProblem)) { Write-Log -Message 'Docker ne répond pas : rien cette fois.' -Level ATTENTION; return 0 }
    $code = 0
    $state = Read-CogesUpdateState $paths
    $setting = Read-CogesUpdateSetting $paths
    Invoke-CogesUpdateCleanup -Paths $paths -State $state -Now $Now
    try { [void](Invoke-CogesUpdateCheck -Paths $paths -State $state) }
    catch { Write-Log -Message ('canal : ' + $_.Exception.Message) -Level ATTENTION }
    $version = Get-CogesReadyVersion $state
    if ($version) {
        $lock = $null
        try {
            $count = Get-CogesCount -Paths $paths
            $due = Test-CogesApplyDue -Now $Now -Heure $setting.heure -BootTime (Get-CogesBootTime) -LastActivity (ConvertTo-CogesStateDate $count.derniere_activite) -Automatique $setting.automatique
            if ($due.Due) {
                $lock = Enter-CogesLock -Paths $paths -Action 'Mise à jour du soir' -WaitSeconds $LockWaitSeconds -IntervalSeconds 30
                [void](Invoke-CogesUpdateLocked -Paths $paths -State $state -Version $version -Now $Now)
            }
            elseif ($due.Motif -ne 'hors-heure') {
                Set-CogesVersionState -State $state -Version $version -Changes @{ dernier_essai = $Now.ToString('o'); dernier_motif = $due.Motif; dernier_motif_texte = $due.Texte }
                Write-CogesUpdateState -Paths $paths -State $state
                Write-Log -Message ('{0} attend : {1}' -f $version, $due.Texte)
            }
        }
        catch {
            Write-Log -Message ('mise à jour : ' + $_.Exception.Message) -Level ECHEC
            Write-CogesUpdateState -Paths $paths -State $state
            $code = 1
        }
        finally { Exit-CogesLock $lock }
    }
    try { [void](Invoke-CogesManualReminder -Paths $paths -State (Read-CogesUpdateState $paths) -Now $Now -Heure $setting.heure) }
    catch { Write-Log -Message ('rappel : ' + $_.Exception.Message) -Level ATTENTION }
    return $code
}

# ---------------------------------------------------------------------------- actions du lot 5

function Initialize-CogesUpdateLog {
    param([Parameter(Mandatory)] $Paths)
    if ($script:CogesState.Simulation) { return }
    New-Item -ItemType Directory -Force -Path $Paths.Journaux | Out-Null
    $script:CogesState.LogPath = Join-Path $Paths.Journaux ('mise-a-jour-{0}.log' -f (Get-Date).ToString('yyyyMMdd'))
}

function Invoke-CogesUpdateCheckAction {
    <# -Action VerifierMiseAJour : lit le canal et télécharge, sans rien appliquer. #>
    param([Parameter(Mandatory)] $Paths)
    if ($script:CogesState.Simulation) {
        foreach ($step in @('lecture du canal (mise-a-jour.json : stable ou test)', 'refus : canal illisible, version plus ancienne, saut trop grand, Docker Desktop trop ancien',
                'archive du programme, empreinte du contenu', 'images front, api, worker tirées par digest, étiquettes vérifiées', 'images d''accompagnement', '5 Go libres', 'état « prete »')) {
            Write-CogesLine ('[simulation] ' + $step)
        }
        return
    }
    Initialize-CogesUpdateLog $Paths
    Write-CogesLine ('Canal : {0}' -f (Read-CogesUpdateSetting $Paths).canal) -Kind Titre
    $state = Read-CogesUpdateState $Paths
    [void](Invoke-CogesUpdateCheck -Paths $Paths -State $state)
}

function Invoke-CogesUpdateAction {
    <# -Action MettreAJour [-Maintenant] [-Bureau] : la version prête, tout de suite (verrou commun). #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if ($script:CogesState.Simulation) {
        foreach ($step in @('1. conditions : version prête et vérifiée, Docker, 5 Go libres, aucune vente depuis 30 min (sauf -Maintenant), verrou',
                '2. sauvegarde chiffrée -avant-maj, copiée sur la clé si branchée', '3. contrôle à blanc des réglages par la nouvelle version',
                '4. page de maintenance, arrêt de front, api, worker, beat, relay', '5. copie de la base coges_avant_maj_<horodatage>',
                '6. programme remplacé (ancien gardé), COGES_IMAGE_TAG changé, migrate, up -d',
                '7. vérifications : neuf services, page d''accueil, licence, mêmes sociétés et ventes, tâches reposées',
                '8. échec en 6 ou 7 : retour automatique (ancien programme, ancienne version, copie de la base)', '9. copie et ancien programme gardés 7 jours')) {
            Write-CogesLine ('[simulation] ' + $step)
        }
        return
    }
    Initialize-CogesUpdateLog $Paths
    $state = Read-CogesUpdateState $Paths
    $version = Get-CogesReadyVersion $state
    if (-not $version) {
        $forced = @($state['versions'].Keys | Where-Object { $state['versions'][$_]['etat'] -in @('echec', 'annulee') -and (Test-Path -LiteralPath (Join-Path (Join-Path (Get-CogesUpdatePath $Paths).Dossier $_) 'programme')) } |
                Sort-Object { ConvertTo-CogesVersionKey $_ } -Descending)
        if ($Options.Maintenant -and $forced.Count -gt 0 -and -not $Options.Bureau) { $version = [string]$forced[0] }
        else {
            Stop-CogesStep -Probleme 'Aucune mise à jour prête sur ce PC.' -QuoiFaire 'Lancez -Action VerifierMiseAJour (ou attendez la prochaine vérification). Rien n''a changé.'
        }
    }
    $settings = Get-CogesSetting $Paths
    $last = $state['derniere_maj']
    $minutes = $script:CogesUpdateMinutesDefault
    if ($last -is [hashtable] -and $last['minutes']) { $minutes = [Math]::Max(2, [int]$last['minutes'] + 1) }
    if ($Options.Bureau) {
        Write-CogesLine ''
        Write-CogesLine ('CoGes va passer de {0} à {1}.' -f $settings['COGES_IMAGE_TAG'], $version) -Kind Titre
        Write-CogesLine ('CoGes sera indisponible environ {0} minutes ; vos données sont sauvegardées avant.' -f $minutes)
        Write-CogesLine 'Si quelque chose ne va pas, CoGes revient tout seul à la version d''avant.'
        Write-CogesLine 'Ne fermez pas cette fenêtre et n''éteignez pas le PC pendant ce temps.' -Kind Attention
        Confirm-CogesWord -Word 'OUI' -Prompt 'On y va ?'
    }
    $lock = Enter-CogesLock -Paths $Paths -Action 'MettreAJour'
    try {
        [void](Invoke-CogesUpdateLocked -Paths $Paths -State $state -Version $version -Force:([bool]$Options.Maintenant))
        if ($Options.Bureau) { Write-CogesLine ''; Write-CogesLine ('CoGes est à jour ({0}). Vous pouvez reprendre.' -f $version) -Kind Ok }
    }
    catch {
        Write-CogesUpdateState -Paths $Paths -State $state
        throw
    }
    finally { Exit-CogesLock $lock }
}

function Invoke-CogesRollbackAction {
    <# -Action RevenirVersionPrecedente (technicien, dans les 7 jours) : ancien programme,
       ancienne version et copie de la base d'avant la mise à jour. Les ventes faites depuis
       sont perdues : comptées, sauvegardées d'abord, REVENIR puis le code de la boutique. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if ($script:CogesState.Simulation) {
        foreach ($step in @('1. dernière mise à jour réussie de moins de 7 jours, copie et ancien programme présents', '2. ventes faites depuis la mise à jour comptées',
                '3. sauvegarde chiffrée -avant-retour', '4. REVENIR, puis le code de la boutique', '5. arrêt, copie de la base remise (base d''après gardée)',
                '6. ancien programme et ancienne version, démarrage, vérifications ; version marquée « annulee »')) {
            Write-CogesLine ('[simulation] ' + $step)
        }
        return
    }
    Initialize-CogesUpdateLog $Paths
    $state = Read-CogesUpdateState $Paths
    $settings = Get-CogesSetting $Paths
    $update = Get-CogesUpdatePath $Paths
    $last = $state['derniere_maj']
    if (-not ($last -is [hashtable]) -or $last['resultat'] -ne 'reussie' -or -not $last['copie']) {
        Stop-CogesStep -Probleme 'Aucune mise à jour récente à défaire sur ce PC (ou elle a plus de 7 jours).' `
            -QuoiFaire 'Pour revenir plus loin : -Action Restaurer avec une sauvegarde « avant mise à jour » (guide, « Restaurer »). Rien n''a changé.'
    }
    $end = ConvertTo-CogesStateDate $last['copie_fin']
    if ($null -eq $end -or (Get-Date) -ge $end) {
        Stop-CogesStep -Probleme ('La mise à jour vers {0} a plus de 7 jours : la copie de la base n''est plus gardée.' -f $last['vers']) `
            -QuoiFaire ('Pour revenir à {0} : -Action Reparer -Version {0}, puis -Action Restaurer avec la sauvegarde {1}. Rien n''a changé.' -f $last['de'], $last['sauvegarde'])
    }
    if ($settings['COGES_IMAGE_TAG'] -ne $last['vers'] -or -not (Test-Path -LiteralPath $update.Precedent) -or (([IO.File]::ReadAllText((Join-Path $update.Precedent '.version'))).Trim() -ne $last['de'])) {
        Stop-CogesStep -Probleme 'L''ancien programme ou la version installée ne correspondent plus à la dernière mise à jour.' -QuoiFaire 'Envoyez le journal à CoGes. Rien n''a changé.'
    }
    $copies = @(Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Copies d''avant la mise à jour' -Arguments @('base.py', 'copies')).Stdout | Where-Object { $_ -and $_.nom -eq ('coges_avant_maj_' + $last['copie']) })
    if ($copies.Count -eq 0) { Stop-CogesStep -Probleme ('La copie coges_avant_maj_{0} n''est plus dans PostgreSQL.' -f $last['copie']) -QuoiFaire 'Voyez « Restaurer » dans le guide. Rien n''a changé.' }
    $since = ConvertTo-CogesStateDate $last['le']
    $count = Get-CogesCount -Paths $Paths -Since ($since.ToUniversalTime().ToString('o'))
    $lost = [long]$count.ventes_depuis
    Write-CogesLine ('Revenir de {0} à {1}' -f $last['vers'], $last['de']) -Kind Titre
    Write-CogesLine ('  Mise à jour faite le {0} ; la base revient à cet instant-là.' -f $since.ToString('dd/MM/yyyy à HH:mm'))
    if ($lost -gt 0) { Write-CogesLine ('  {0} VENTE(S) FAITE(S) DEPUIS SERAIENT PERDUES (elles restent dans la sauvegarde faite juste avant le retour).' -f $lost) -Kind Echec }
    else { Write-CogesLine '  Aucune vente faite depuis la mise à jour.' -Kind Ok }
    $lock = Enter-CogesLock -Paths $Paths -Action 'RevenirVersionPrecedente'
    try {
        Write-CogesLine '» Sauvegarde chiffrée avant le retour' -Kind Titre
        $backup = New-CogesBackup -Paths $Paths -Raison 'avant-retour'
        Write-CogesLine ('  {0}' -f $backup.Path) -Kind Ok
        Confirm-CogesWord -Word 'REVENIR' -Prompt ('Revenir à {0} ?' -f $last['de']) -Given $Options.ConfirmerRetour -Parameter 'ConfirmerRetour'
        $slug = Read-CogesAnswer -Question 'Pour confirmer, retapez le code de la boutique' -Parameter 'CodeBoutique' -Value $Options.CodeBoutique `
            -Validate { param($v) Test-CogesSlug $v } -Rule 'minuscules, chiffres et tirets entre deux mots.'
        if (@($count.boutiques) -cnotcontains $slug) { Stop-CogesStep -Probleme ('Aucune société « {0} » sur ce PC : rien n''est fait.' -f $slug) -QuoiFaire 'Relancez et retapez le code exact.' }
        [void](Invoke-CogesCompose -Paths $Paths -Arguments (@('stop') + $script:CogesApplicationServices))
        [void](Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Copie de la base remise' -Arguments @('base.py', 'remettre', [string]$last['copie'], '--ecarter', 'apres'))
        $after = $Paths.Programme + '.apres'
        if (Test-Path -LiteralPath $after) { Remove-Item -LiteralPath $after -Recurse -Force }
        Rename-Item -LiteralPath $Paths.Programme -NewName (Split-Path -Leaf $after)
        Rename-Item -LiteralPath $update.Precedent -NewName (Split-Path -Leaf $Paths.Programme)
        Set-CogesEnvValue -Path $Paths.EnvFile -Values ([ordered]@{ COGES_IMAGE_TAG = [string]$last['de'] })
        [void](Get-CogesSetting $Paths)
        $up = Invoke-CogesCompose -Paths $Paths -Arguments @('up', '-d', '--remove-orphans')
        if ($up.ExitCode -ne 0) { Stop-CogesStep -Probleme ('Le démarrage de {0} a échoué.' -f $last['de']) -QuoiFaire ('Appelez CoGes. La base d''après est gardée sous coges_apres_maj_{0}, et la sauvegarde {1}.' -f $last['copie'], $backup.Name) }
        # La base remise doit être celle de la mise à jour : mêmes sociétés et ventes qu'à ce moment-là.
        $reference = Get-CogesCount -Paths $Paths
        if ($last.ContainsKey('ventes') -and $null -ne $last['ventes']) {
            $reference = [pscustomobject]@{ societes = $last['societes']; ventes = $last['ventes']; boutiques = $reference.boutiques }
        }
        Test-CogesUpdatedSite -Paths $Paths -Before $reference
        Install-CogesTasksAgain $Paths
        if (Test-Path -LiteralPath $after) { Remove-Item -LiteralPath $after -Recurse -Force }
        Set-CogesVersionState -State $state -Version ([string]$last['vers']) -Changes @{ etat = 'annulee'; annulee_le = (Get-Date).ToString('o') }
        $state['derniere_maj'] = @{ de = $last['vers']; vers = $last['de']; le = (Get-Date).ToString('o'); resultat = 'revenue-a-la-main'; copie = $null; ventes_perdues = $lost; sauvegarde = $backup.Name }
        Write-CogesUpdateState -Paths $Paths -State $state
        Set-CogesUpdateShortcut -Paths $Paths -Present $false
        Write-CogesLine ''
        Write-CogesLine ('CoGes est revenu à {0}. {1} ne s''appliquera plus seule. La base d''après reste sous coges_apres_maj_{2} (-Action NettoyerAncienneBase).' -f $last['de'], $last['vers'], $last['copie']) -Kind Ok
    }
    finally { Exit-CogesLock $lock }
}

function Show-CogesUpdateState {
    <# Les lignes du lot 5 dans Etat. #>
    param([Parameter(Mandatory)] $Paths)
    $setting = Read-CogesUpdateSetting $Paths
    $state = Read-CogesUpdateState $Paths
    $mode = 'automatique'
    if (-not $setting.automatique) { $mode = 'À LA MAIN (mise-a-jour.json)' }
    Write-CogesLine ('  Mises à jour      : canal {0}, {1}, à {2}' -f $setting.canal, $mode, $setting.heure)
    $checked = ConvertTo-CogesStateDate $state['derniere_verification']
    if ($checked) { Write-CogesLine ('  Dernier canal lu  : {0} — {1}' -f $checked.ToString('dd/MM/yyyy HH:mm'), $state['derniere_verification_texte']) }
    else { Write-CogesLine '  Dernier canal lu  : jamais' }
    $ready = Get-CogesReadyVersion $state
    if ($ready) {
        $entry = Get-CogesVersionState -State $state -Version $ready
        $wait = Get-CogesUpdateWait -Entry $entry -Now (Get-Date) -Heure $setting.heure
        Write-CogesLine ('  Disponible        : {0}, prête ; attend depuis {1} jour(s) : {2}' -f $ready, $wait.Days, $wait.Reason) -Kind $(if ($wait.Manual) { 'Attention' } else { 'Info' })
        if ($setting.automatique) { Write-CogesLine ('  Prochaine application : ce soir ou demain à {0}, si la boutique est calme depuis 30 minutes' -f $setting.heure) }
        if ($wait.Manual) { Write-CogesLine '  Raccourci « Mettre CoGes à jour » posé sur le Bureau.' -Kind Attention }
    }
    elseif ($state['disponible'] -is [hashtable]) {
        $other = Get-CogesVersionState -State $state -Version ([string]$state['disponible']['version'])
        if ($other -and $other['etat'] -ne 'appliquee') { Write-CogesLine ('  Disponible        : {0} ({1})' -f $state['disponible']['version'], $other['etat']) -Kind $(if ($other['etat'] -in @('echec', 'annulee')) { 'Attention' } else { 'Info' }) }
    }
    $last = $state['derniere_maj']
    if ($last -is [hashtable]) {
        $when = ConvertTo-CogesStateDate $last['le']
        $words = @{ 'reussie' = 'réussie'; 'revenue' = 'RATÉE, revenue seule en arrière'; 'revenue-a-la-main' = 'défaite à la main (RevenirVersionPrecedente)' }
        Write-CogesLine ('  Dernière mise à jour : {0} → {1}, le {2}, {3}' -f $last['de'], $last['vers'], $when.ToString('dd/MM/yyyy HH:mm'), $words[[string]$last['resultat']]) -Kind $(if ($last['resultat'] -eq 'reussie') { 'Ok' } else { 'Attention' })
        if ($last['raison']) { Write-CogesLine ('    Raison : {0}' -f $last['raison']) -Kind Attention }
        if ($last['copie']) {
            Write-CogesLine ('  Copie gardée      : coges_avant_maj_{0} et programme {1}, jusqu''au {2} (-Action RevenirVersionPrecedente)' -f $last['copie'], $last['de'], (ConvertTo-CogesStateDate $last['copie_fin']).ToString('dd/MM/yyyy HH:mm'))
        }
    }
}

function Set-CogesUpdateOption {
    <# Reparer -HeureMiseAJour HH:MM, -CanalMiseAJour stable|test : réglage écrit, tâche reposée. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans le bloc de l''étape (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    $changes = @{}
    if ($Options.HeureMiseAJour) {
        if (-not (Test-CogesHour $Options.HeureMiseAJour)) { Stop-CogesStep -Probleme ('-HeureMiseAJour {0} n''est pas une heure HH:MM.' -f $Options.HeureMiseAJour) -QuoiFaire 'Par exemple -HeureMiseAJour 13:00.' }
        $changes['heure'] = $Options.HeureMiseAJour
    }
    if ($Options.CanalMiseAJour) {
        if ($script:CogesChannels -cnotcontains $Options.CanalMiseAJour) { Stop-CogesStep -Probleme ('-CanalMiseAJour {0} : stable ou test.' -f $Options.CanalMiseAJour) -QuoiFaire 'stable pour les clients, test pour le PC d''essai de CoGes.' }
        $changes['canal'] = $Options.CanalMiseAJour
    }
    if ($changes.Count -eq 0) { return }
    Invoke-CogesStep -Title ('Réglage des mises à jour : {0}' -f (($changes.Keys | Sort-Object | ForEach-Object { '{0} {1}' -f $_, $changes[$_] }) -join ', ')) -Action {
        Write-CogesUpdateSetting -Paths $Paths -Changes $changes
    }
}

# ---------------------------------------------------------------------------- lot 6 : support à distance (ADR 0129)
#
# TOUJOURS SORTANT, JAMAIS ENTRANT : le PC envoie des pings (POST https) à un service
# « homme mort » (Healthchecks.io), comme les tâches de la production (ADR 0077). Aucun
# port ouvert, aucun service qui écoute, aucune commande reçue. Ce qui sort est la liste
# fermée de support\champs.txt, et rien d'autre : aucun texte libre, aucune donnée
# commerciale. Un ping qui échoue n'arrête jamais rien : journal seulement.

$script:CogesSupportSignals = @('vie', 'sauvegarde', 'mise-a-jour')
$script:CogesSupportFormat = 'COGES-SUPPORT-1'
$script:CogesReportFormat = 'COGES-RESUME-1'
$script:CogesPingTimeoutSeconds = 10
$script:CogesPingTries = 2
$script:CogesPingPauseSeconds = 2
$script:CogesReportMaxBytes = 2048
$script:CogesLogSources = @('installation', 'demarrage', 'sauvegarde', 'mise-a-jour', 'support')
$script:CogesLogKeepDays = 60
$script:CogesLogMaxBytes = 200MB
$script:CogesDiagnosticMaxBytes = 10MB
$script:CogesDiagnosticLogDays = 7
$script:CogesDiagnosticTails = @(300, 100, 30)
$script:CogesHelpShortcut = 'Aide CoGes.cmd'
$script:CogesDiagnosticShortcut = 'Diagnostic CoGes.cmd'
$script:CogesQuickAssistPackage = 'MicrosoftCorporationII.QuickAssist'
$script:CogesQuickAssistStore = 'ms-windows-store://pdp/?productid=9P7BP5VNWKX5'
#: La liste des champs, à côté de ce fichier quand il n'est pas encore dans le programme.
$script:CogesFieldsBeside = $null
if ($PSScriptRoot) { $script:CogesFieldsBeside = Join-Path (Split-Path -Parent $PSScriptRoot) 'support\champs.txt' }

function Get-CogesSupportPath {
    param([Parameter(Mandatory)] $Paths)
    $folder = Join-Path $Paths.Racine 'support'
    return [pscustomobject]@{
        Reglage = Join-Path $Paths.Reglages 'support.json'
        Dossier = $folder
        Etat    = Join-Path $folder 'etat.json'
    }
}

# ---------------------------------------------------------------------------- bloc A : la liste et le résumé (fonctions pures)

function ConvertFrom-CogesFieldList {
    <# support\champs.txt en liste ordonnée : Name, Rule (expression ancrée), Text. #>
    param([Parameter(Mandatory)] [AllowEmptyString()] [string] $Text)
    $fields = New-Object System.Collections.Generic.List[object]
    foreach ($line in ($Text -split "`r?`n")) {
        if (-not $line.Trim() -or $line.TrimStart().StartsWith('#')) { continue }
        $parts = $line -split ' \| ', 3
        if ($parts.Count -ne 3) { throw ('champs.txt : ligne illisible « {0} »' -f $line) }
        $fields.Add([pscustomobject]@{ Name = $parts[0].Trim(); Rule = ('^(?:{0})$' -f $parts[1].Trim()); Text = $parts[2].Trim() })
    }
    return $fields.ToArray()
}

function Get-CogesFieldList {
    <# La liste du programme installé ; sinon celle d'à côté (dépôt, tests). $null : aucune. #>
    param($Paths = $null)
    $candidates = @()
    if ($Paths) { $candidates += (Join-Path $Paths.Programme 'support\champs.txt') }
    if ($script:CogesFieldsBeside) { $candidates += $script:CogesFieldsBeside }
    foreach ($file in $candidates) {
        if (Test-Path -LiteralPath $file) { return , (ConvertFrom-CogesFieldList ([IO.File]::ReadAllText($file))) }
    }
    return $null
}

function Get-CogesReport {
    <# Le résumé : un objet FERMÉ, aux seuls champs de la liste, dans son ordre. Un champ
       inconnu, ou une valeur hors de sa règle, lève (rien ne part). Fonction pure. #>
    param([Parameter(Mandatory)] [System.Collections.IDictionary] $Facts, [Parameter(Mandatory)] [object[]] $Fields)
    $names = @($Fields | ForEach-Object { $_.Name })
    foreach ($key in $Facts.Keys) {
        if ($names -cnotcontains [string]$key) { throw ('résumé : le champ « {0} » n''est pas dans champs.txt' -f $key) }
    }
    $report = [ordered]@{}
    foreach ($field in $Fields) {
        if (-not $Facts.Contains($field.Name)) { throw ('résumé : le champ « {0} » manque' -f $field.Name) }
        $value = [string]$Facts[$field.Name]
        if ($value -cnotmatch $field.Rule) { throw ('résumé : la valeur du champ « {0} » est hors de sa règle' -f $field.Name) }
        $report[$field.Name] = $value
    }
    return $report
}

function Format-CogesReport {
    <# Le corps du ping : « nom: valeur », une ligne par champ, moins de 2 Ko. #>
    param([Parameter(Mandatory)] [System.Collections.IDictionary] $Report)
    $text = (@($Report.Keys | ForEach-Object { '{0}: {1}' -f $_, $Report[$_] }) -join "`n") + "`n"
    if ([Text.Encoding]::UTF8.GetByteCount($text) -gt $script:CogesReportMaxBytes) { throw 'résumé : plus de 2 Ko' }
    return $text
}

function Get-CogesMinimalFact {
    <# Les faits sûrs de tout envoi ; le reste « inconnu » : ce qui part quand la lecture de
       l'état a échoué (le ping part quand même). #>
    param([Parameter(Mandatory)] [string] $Pc, [Parameter(Mandatory)] [string] $Signal, [bool] $Failure, [string] $Reason = 'aucune', [Nullable[datetime]] $Now = $null)
    if ($null -eq $Now) { $Now = Get-Date }
    $result = 'ok'
    if ($Failure) { $result = 'echec' }
    if ($Failure -and $Reason -eq 'aucune') { $Reason = 'autre' }
    return [ordered]@{
        format = $script:CogesReportFormat; pc = $Pc; signal = $Signal; resultat = $result; raison = $Reason
        envoye_le = $Now.ToString('yyyy-MM-ddTHH:mm'); version = 'inconnue'; canal = 'stable'; maj = 'aucune'; maj_le = 'jamais'
        maj_attente = 'aucune'; services_ok = 'inconnu'; services_ko = 'inconnu'; licence = 'inconnue'; offre = 'inconnue'
        sauvegarde_le = 'jamais'; copie_le = 'jamais'; essai = 'jamais'; essai_le = 'jamais'; disque_go = 'inconnu'
        memoire_go = 'inconnue'; windows = 'inconnue'; docker = 'inconnue'; wsl = 'inconnue'; erreurs_24h = 'aucune'
    }
}

function ConvertTo-CogesReportDate {
    param([AllowNull()] $Date)
    if ($null -eq $Date) { return 'jamais' }
    return ([datetime]$Date).ToString('yyyy-MM-ddTHH:mm')
}

function Get-CogesFailureCode {
    <# Le code d'une raison d'échec (liste fermée de champs.txt) : le texte reste au journal. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Message)
    $text = [string]$Message
    $rules = [ordered]@{
        'docker-arrete' = 'Docker ne répond pas|moteur Docker|Docker Desktop n''est pas|docker.*(introuvable|not found)'
        'verrou'        = 'verrou|déjà en cours|occupé'
        'place-disque'  = 'place sur le disque|Pas assez de place|disque plein|No space left'
        'cle-absente'   = 'clé publique'
        'taille'        = 'trop petite'
        'empreinte'     = 'empreinte'
        'demarrage'     = 'up -d|démarrage|ne répond pas'
    }
    foreach ($code in $rules.Keys) { if ($text -match $rules[$code]) { return $code } }
    return 'autre'
}

function Get-CogesErrorCount {
    <# Lignes « [ECHEC] » des journaux, sur 24 h, par source (préfixe du nom du fichier). #>
    param([Parameter(Mandatory)] [string] $Folder, [Parameter(Mandatory)] [datetime] $Now)
    $since = $Now.AddHours(-24)
    $counts = [ordered]@{}
    foreach ($file in @(Get-ChildItem -LiteralPath $Folder -File -Filter '*.log' -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $since })) {
        $source = $null
        foreach ($name in $script:CogesLogSources) { if ($file.Name -like ($name + '-*')) { $source = $name } }
        if (-not $source) { continue }
        foreach ($line in [IO.File]::ReadAllLines($file.FullName)) {
            if ($line -notmatch '^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \[ECHEC\]') { continue }
            $at = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture)
            if ($at -lt $since) { continue }
            if (-not $counts.Contains($source)) { $counts[$source] = 0 }
            $counts[$source] = $counts[$source] + 1
        }
    }
    if ($counts.Count -eq 0) { return 'aucune' }
    return (@($script:CogesLogSources | Where-Object { $counts.Contains($_) } | ForEach-Object { '{0}={1}' -f $_, $counts[$_] }) -join ' ')
}

function ConvertTo-CogesLicenseFact {
    <# La sortie de « base.py licence » en deux champs : licence et offre. #>
    param([AllowNull()] $Data)
    if ($null -eq $Data) { return @{ licence = 'inconnue'; offre = 'inconnue' } }
    $states = @{}
    if ($Data.etats) { foreach ($property in $Data.etats.PSObject.Properties) { $states[$property.Name] = [int]$property.Value } }
    $licence = 'aucune'
    if ($states['suspended']) { $licence = 'suspendue' }
    elseif ($states['past_due']) { $licence = 'impayee' }
    elseif ($states['trial']) { $licence = 'essai' }
    elseif ($states['active']) { $licence = 'active' }
    $plans = @($Data.offres | Where-Object { $_ -in @('starter', 'business', 'premium') })
    $offre = 'aucune'
    if ($plans.Count -gt 0) { $offre = ($plans | Sort-Object) -join ',' }
    return @{ licence = $licence; offre = $offre }
}

function Get-CogesWslVersion {
    if (-not (Test-CogesWindows)) { return 'inconnue' }
    try {
        # wsl.exe écrit en UTF-16 : PowerShell en lit des caractères nuls.
        $text = ((& wsl.exe --version 2>$null) -join ' ') -replace "`0", ''
        if ($text -match '(\d+\.\d+\.\d+(?:\.\d+)?)') { return $Matches[1] }
    }
    catch { Write-Verbose 'wsl absent' }
    return 'inconnue'
}

function Get-CogesMemoryGo {
    try {
        if (Test-CogesWindows) { return ('{0:0.0}' -f ((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)).Replace(',', '.') }
        if (Test-Path -LiteralPath '/proc/meminfo') {
            $line = @(Get-Content -LiteralPath '/proc/meminfo' | Where-Object { $_ -match '^MemTotal:\s+(\d+) kB' })[0]
            if ($line -match '(\d+) kB') { return ('{0:0.0}' -f ([double]$Matches[1] * 1KB / 1GB)).Replace(',', '.') }
        }
    }
    catch { Write-Verbose 'mémoire illisible' }
    return 'inconnue'
}

function Read-CogesReportFact {
    <# Lit l'état du PC (fichiers d'état, compose ps, base.py licence) en faits du résumé.
       Chaque lecture qui échoue laisse « inconnu » : le ping part quand même. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [string] $Pc, [Parameter(Mandatory)] [string] $Signal,
        [bool] $Failure, [string] $Reason = 'aucune', [Nullable[datetime]] $Now = $null)
    if ($null -eq $Now) { $Now = Get-Date }
    $facts = Get-CogesMinimalFact -Pc $Pc -Signal $Signal -Failure $Failure -Reason $Reason -Now $Now
    try {
        $version = Get-CogesInstalledVersion $Paths
        if (Test-CogesVersion $version) { $facts.version = $version }
    }
    catch { Write-Verbose 'version illisible' }
    try {
        $facts.canal = (Read-CogesUpdateSetting $Paths).canal
        $state = Read-CogesUpdateState $Paths
        $last = $state['derniere_maj']
        if ($last -is [hashtable] -and $last['resultat']) {
            $facts.maj = [string]$last['resultat']
            $facts.maj_le = ConvertTo-CogesReportDate (ConvertTo-CogesStateDate $last['le'])
        }
        $ready = Get-CogesReadyVersion $state
        if ($ready) {
            $wait = Get-CogesUpdateWait -Entry (Get-CogesVersionState -State $state -Version $ready) -Now $Now -Heure (Read-CogesUpdateSetting $Paths).heure
            $facts.maj_attente = '{0} depuis {1} j' -f $ready, $wait.Days
        }
    }
    catch { Write-Verbose 'état des mises à jour illisible' }
    try {
        $summary = Get-CogesBackupSummary $Paths
        $facts.sauvegarde_le = ConvertTo-CogesReportDate $summary.LastGood
        $facts.copie_le = ConvertTo-CogesReportDate $summary.LastOffsite
        $facts.essai_le = ConvertTo-CogesReportDate $summary.LastTrial
        if ($null -ne $summary.LastTrialOk) { $facts.essai = $(if ($summary.LastTrialOk) { 'ok' } else { 'echec' }) }
        if ($summary.Free -ne [long]::MaxValue) { $facts.disque_go = ('{0:0.0}' -f ($summary.Free / 1GB)).Replace(',', '.') }
    }
    catch { Write-Verbose 'état des sauvegardes illisible' }
    $facts.memoire_go = Get-CogesMemoryGo
    try {
        $os = [Environment]::OSVersion.Version
        $facts.windows = '{0}.{1}.{2}' -f $os.Major, $os.Minor, $os.Build
    }
    catch { Write-Verbose 'version du système illisible' }
    $facts.wsl = Get-CogesWslVersion
    try { $facts.erreurs_24h = Get-CogesErrorCount -Folder $Paths.Journaux -Now $Now } catch { Write-Verbose 'journaux illisibles' }
    # Ce qui demande Docker, en dernier : Docker arrêté laisse « inconnu ».
    try {
        $engine = Invoke-Docker -Arguments @('version', '--format', '{{.Server.Platform.Name}}|{{.Server.Version}}')
        if ($engine.ExitCode -eq 0) {
            $line = [string](@($engine.Stdout) -join ' ')
            $desktop = Get-CogesDockerDesktopVersion @($line)
            if ($desktop) { $facts.docker = $desktop.ToString() }
            elseif ($line -match '\|(\d+\.\d+\.\d+)') { $facts.docker = $Matches[1] }
            $containers = @(ConvertFrom-CogesComposeStatus (Invoke-CogesCompose -Paths $Paths -Arguments @('ps', '-a', '--format', 'json')).Stdout)
            $bad = @($script:CogesServices | Where-Object {
                    $name = $_
                    $container = @($containers | Where-Object { $_.Service -eq $name }) | Select-Object -First 1
                    -not ($container -and $container.State -eq 'running' -and ($container.Health -eq 'healthy' -or -not $container.Health))
                })
            $facts.services_ok = '{0}/9' -f ($script:CogesServices.Count - $bad.Count)
            $facts.services_ko = $(if ($bad.Count -eq 0) { 'aucun' } else { $bad -join ',' })
            $licence = Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Licence (support)' -Arguments @('base.py', 'licence')
            $license = ConvertTo-CogesLicenseFact (Get-CogesLastJson $licence.Stdout)
            $facts.licence = $license.licence
            $facts.offre = $license.offre
        }
    }
    catch { Write-Log -Message ('résumé : lecture par Docker impossible : ' + $_.Exception.Message) -Level ATTENTION }
    return $facts
}

# ---------------------------------------------------------------------------- bloc B : réglages et envoi

function Test-CogesPingUrl {
    <# https, ou http sur la machine elle-même (faux serveur des essais) ; jamais d'espace. #>
    param([AllowEmptyString()] [AllowNull()] [string] $Url)
    return ([string]$Url -match '^(https://[A-Za-z0-9.-]+(:\d+)?/[^\s]+|http://(127\.0\.0\.1|localhost)(:\d+)?/[^\s]+)$')
}

function Read-CogesSupportSetting {
    <# reglages\support.json : pc, remontee, adresses (vie, sauvegarde, mise-a-jour), telephone_coges. #>
    param([Parameter(Mandatory)] $Paths)
    $result = @{ format = $script:CogesSupportFormat; pc = ''; remontee = $false; adresses = @{}; telephone_coges = '' }
    $file = (Get-CogesSupportPath $Paths).Reglage
    if (-not (Test-Path -LiteralPath $file)) { return $result }
    try { $data = ConvertTo-CogesHashtable ([IO.File]::ReadAllText($file) | ConvertFrom-Json) }
    catch { Write-Log -Message 'support.json illisible : remontée inactive' -Level ATTENTION; return $result }
    if (-not ($data -is [hashtable])) { return $result }
    if ([string]$data['pc'] -match '^[0-9a-f]{32}$') { $result.pc = [string]$data['pc'] }
    if ($data['adresses'] -is [hashtable]) {
        foreach ($signal in $script:CogesSupportSignals) {
            if (Test-CogesPingUrl ([string]$data['adresses'][$signal])) { $result.adresses[$signal] = [string]$data['adresses'][$signal] }
        }
    }
    $result.remontee = ($data['remontee'] -eq $true) -and $result.pc -and ($result.adresses.Count -gt 0)
    if ($data['telephone_coges']) { $result.telephone_coges = [string]$data['telephone_coges'] }
    return $result
}

function Get-CogesSupportMaskValue {
    <# Les adresses de ping sont des secrets : masquées dans toute ligne du journal. #>
    param([Parameter(Mandatory)] $Paths)
    $values = @()
    try {
        foreach ($url in (Read-CogesSupportSetting $Paths).adresses.Values) {
            $values += $url
            $values += ($url -replace '^https?://[^/]+/', '')
        }
    }
    catch { Write-Verbose 'support.json illisible' }
    return @($values | Where-Object { $_ -and $_.Length -ge 8 })
}

function Write-CogesSupportSetting {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Setting)
    $file = (Get-CogesSupportPath $Paths).Reglage
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    $data = [ordered]@{ format = $script:CogesSupportFormat; pc = $Setting.pc; remontee = [bool]$Setting.remontee
        adresses = [ordered]@{}; telephone_coges = [string]$Setting.telephone_coges }
    foreach ($signal in $script:CogesSupportSignals) { if ($Setting.adresses[$signal]) { $data.adresses[$signal] = $Setting.adresses[$signal] } }
    $temporary = $file + '.nouveau'
    [IO.File]::WriteAllText($temporary, ($data | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $file -Force
    $script:CogesState.MaskValues = @($script:CogesState.MaskValues) + @(Get-CogesSupportMaskValue $Paths)
}

function New-CogesPcId {
    return -join ((New-CogesRandomByte 16) | ForEach-Object { $_.ToString('x2') })
}

function Initialize-CogesSupportSetting {
    <# Installer, Reparer : l'identifiant du PC tiré une fois (jamais changé ensuite) ; le
       fichier du technicien (-Support) pose les adresses et le numéro de CoGes. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans le bloc de l''étape (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    $given = $null
    if ($Options.Support) { $given = Read-CogesSupportFile $Options.Support }
    $title = 'Support à distance : identifiant du PC (remontée inactive tant que les adresses ne sont pas posées)'
    if ($given) { $title = 'Support à distance : adresses de remontée posées (fichier du technicien)' }
    Invoke-CogesStep -Title $title -Action {
        $setting = Read-CogesSupportSetting $Paths
        $exists = Test-Path -LiteralPath (Get-CogesSupportPath $Paths).Reglage
        if (-not $setting.pc) { $setting.pc = New-CogesPcId }
        if ($given) {
            $setting.adresses = $given.adresses
            $setting.remontee = $given.remontee
            if ($given.telephone_coges) { $setting.telephone_coges = $given.telephone_coges }
        }
        if ($given -or -not $exists) { Write-CogesSupportSetting -Paths $Paths -Setting $setting }
        if ($given) { Write-CogesLine ('  {0} adresse(s) posée(s) ; essai : -Action TesterSupport.' -f $setting.adresses.Count) -Kind Ok }
    }
}

function Read-CogesSupportFile {
    <# Le fichier préparé chez CoGes : { "adresses": { "vie": …, "sauvegarde": …,
       "mise-a-jour": … }, "telephone_coges": "…", "remontee": true }. #>
    param([Parameter(Mandatory)] [string] $Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        Stop-CogesStep -Probleme ('Fichier de support introuvable : {0}' -f $Path) -QuoiFaire 'Donnez le support.json préparé chez CoGes (-Support E:\support.json).'
    }
    try { $data = ConvertTo-CogesHashtable ([IO.File]::ReadAllText($Path) | ConvertFrom-Json) }
    catch { Stop-CogesStep -Probleme 'Le fichier de support n''est pas un JSON lisible.' -QuoiFaire 'Refaites-le chez CoGes (modèle : docs/runbooks/sur-site.md, « Support à distance »).' }
    $addresses = @{}
    foreach ($signal in $script:CogesSupportSignals) {
        $url = ''
        if ($data -is [hashtable] -and $data['adresses'] -is [hashtable]) { $url = [string]$data['adresses'][$signal] }
        if (-not (Test-CogesPingUrl $url)) {
            Stop-CogesStep -Probleme ('Adresse « {0} » absente ou fausse dans le fichier de support.' -f $signal) -QuoiFaire 'Chaque check : https://hc-ping.com/<uuid> (copiée depuis Healthchecks.io).'
        }
        $addresses[$signal] = $url
    }
    $enabled = $true
    if ($data.ContainsKey('remontee') -and $data['remontee'] -is [bool]) { $enabled = [bool]$data['remontee'] }
    return @{ adresses = $addresses; remontee = $enabled; telephone_coges = [string]$data['telephone_coges'] }
}

function Read-CogesSupportState {
    param([Parameter(Mandatory)] $Paths)
    $file = (Get-CogesSupportPath $Paths).Etat
    $state = @{}
    if (Test-Path -LiteralPath $file) {
        try { $state = ConvertTo-CogesHashtable ([IO.File]::ReadAllText($file) | ConvertFrom-Json) } catch { $state = @{} }
    }
    if (-not ($state -is [hashtable])) { $state = @{} }
    return $state
}

function Write-CogesSupportState {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Changes)
    $state = Read-CogesSupportState $Paths
    foreach ($key in $Changes.Keys) { $state[$key] = $Changes[$key] }
    $file = (Get-CogesSupportPath $Paths).Etat
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $file) | Out-Null
    $temporary = $file + '.nouveau'
    [IO.File]::WriteAllText($temporary, ($state | ConvertTo-Json -Depth 4), (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $temporary -Destination $file -Force
}

function Invoke-CogesPingRequest {
    <# Un POST, texte en UTF-8 ; lève si pas de 2xx. Remplacé par un faux en test. #>
    param([Parameter(Mandatory)] [string] $Url, [Parameter(Mandatory)] [string] $Body, [int] $TimeoutSeconds = 10)
    $previous = $ProgressPreference
    $ProgressPreference = 'SilentlyContinue'
    try {
        $bytes = (New-Object Text.UTF8Encoding $false).GetBytes($Body)
        $response = Invoke-WebRequest -Uri $Url -Method Post -Body $bytes -ContentType 'text/plain; charset=utf-8' -UseBasicParsing -TimeoutSec $TimeoutSeconds -ErrorAction Stop
        return [int]$response.StatusCode
    }
    finally { $ProgressPreference = $previous }
}

function Send-CogesPing {
    <# Un signal vers CoGes : POST du résumé à l'adresse, ou à <adresse>/fail. 10 s, 2 essais ;
       JAMAIS bloquant : rend $true (reçu) ou $false (inactif, injoignable), n'échoue jamais. #>
    param(
        [Parameter(Mandatory)] $Paths,
        [Parameter(Mandatory)] [ValidateSet('vie', 'sauvegarde', 'mise-a-jour')] [string] $Signal,
        [switch] $Failure,
        [string] $Reason = 'aucune',
        [string] $ReportSignal = '',
        [switch] $Force
    )
    if ($script:CogesState.Simulation) { return $false }
    try {
        $setting = Read-CogesSupportSetting $Paths
        $url = $setting.adresses[$Signal]
        if (-not ($setting.remontee -or $Force) -or -not $url) {
            Write-Log -Message ('remontée inactive : signal {0} non envoyé' -f $Signal)
            return $false
        }
        $script:CogesState.MaskValues = @($script:CogesState.MaskValues) + @(Get-CogesSupportMaskValue $Paths)
        if (-not $ReportSignal) { $ReportSignal = $Signal }
        $fields = Get-CogesFieldList $Paths
        if ($null -eq $fields) { Write-Log -Message 'support\champs.txt absent : signal non envoyé' -Level ATTENTION; return $false }
        try {
            $facts = Read-CogesReportFact -Paths $Paths -Pc $setting.pc -Signal $ReportSignal -Failure ([bool]$Failure) -Reason $Reason
            $body = Format-CogesReport (Get-CogesReport -Facts $facts -Fields $fields)
        }
        catch {
            Write-Log -Message ('résumé incomplet (' + $_.Exception.Message + ') : envoi du résumé minimal') -Level ATTENTION
            $body = Format-CogesReport (Get-CogesReport -Facts (Get-CogesMinimalFact -Pc $setting.pc -Signal $ReportSignal -Failure ([bool]$Failure) -Reason $Reason) -Fields $fields)
        }
        $target = $url
        if ($Failure) { $target = $url.TrimEnd('/') + '/fail' }
        for ($try = 1; $try -le $script:CogesPingTries; $try++) {
            try {
                $status = Invoke-CogesPingRequest -Url $target -Body $body -TimeoutSeconds $script:CogesPingTimeoutSeconds
                if ($status -ge 200 -and $status -lt 300) {
                    $result = 'ok'
                    if ($Failure) { $result = 'echec' }
                    Write-Log -Message ('signal {0} ({1}, {2}) reçu par CoGes' -f $Signal, $result, $Reason) -Level OK
                    Write-CogesSupportState -Paths $Paths -Changes @{ dernier_envoi = (Get-Date).ToString('o'); dernier_signal = $Signal; dernier_resultat = $result }
                    return $true
                }
                Write-Log -Message ('signal {0} : réponse {1} (essai {2})' -f $Signal, $status, $try) -Level ATTENTION
            }
            catch { Write-Log -Message ('signal {0} : {1} (essai {2})' -f $Signal, $_.Exception.Message, $try) -Level ATTENTION }
            if ($try -lt $script:CogesPingTries) { Start-Sleep -Seconds $script:CogesPingPauseSeconds }
        }
        Write-CogesSupportState -Paths $Paths -Changes @{ dernier_echec_envoi = (Get-Date).ToString('o') }
        return $false
    }
    catch {
        Write-Log -Message ('signal {0} non envoyé : {1}' -f $Signal, $_.Exception.Message) -Level ATTENTION
        return $false
    }
}

function Invoke-CogesTestSupport {
    <# -Action TesterSupport : un ping « test » sur les trois adresses, et qui a répondu. #>
    param([Parameter(Mandatory)] $Paths)
    if ($script:CogesState.Simulation) {
        foreach ($signal in $script:CogesSupportSignals) { Write-CogesLine ('[simulation] ping de test vers l''adresse « {0} »' -f $signal) }
        return
    }
    Initialize-CogesSupportLog $Paths
    $setting = Read-CogesSupportSetting $Paths
    if ($setting.adresses.Count -eq 0) {
        Stop-CogesStep -Probleme 'Aucune adresse de remontée sur ce PC.' -QuoiFaire 'Posez-les : -Action Reparer -Support <fichier.json>, ou -Action ConfigurerSupport.'
    }
    $failed = 0
    foreach ($signal in $script:CogesSupportSignals) {
        if (-not $setting.adresses[$signal]) { Write-CogesLine ('  {0,-12} : aucune adresse' -f $signal) -Kind Attention; $failed++; continue }
        if (Send-CogesPing -Paths $Paths -Signal $signal -ReportSignal 'test' -Force) { Write-CogesLine ('  {0,-12} : reçu par CoGes' -f $signal) -Kind Ok }
        else { Write-CogesLine ('  {0,-12} : PAS de réponse (Internet, adresse ?)' -f $signal) -Kind Echec; $failed++ }
    }
    if (-not $setting.remontee) { Write-CogesLine '  La remontée est désactivée dans support.json (« remontee »: false) : rien ne part en dehors de ce test.' -Kind Attention }
    if ($failed -gt 0) { Stop-CogesStep -Probleme ('{0} adresse(s) sans réponse.' -f $failed) -QuoiFaire 'Vérifiez Internet, puis les adresses dans Healthchecks.io ; relancez -Action TesterSupport.' }
}

function Invoke-CogesConfigureSupport {
    <# -Action ConfigurerSupport : les trois adresses et le numéro de CoGes, en questions. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if ($Options.Support) { Initialize-CogesSupportSetting -Paths $Paths -Options $Options; return }
    if ($script:CogesState.NonInteractif) {
        Stop-CogesStep -Probleme 'ConfigurerSupport pose des questions.' -QuoiFaire 'En -NonInteractif, passez -Support <fichier.json>.'
    }
    $setting = Read-CogesSupportSetting $Paths
    if (-not $setting.pc) { $setting.pc = New-CogesPcId }
    foreach ($signal in $script:CogesSupportSignals) {
        $setting.adresses[$signal] = Read-CogesAnswer -Question ('Adresse de ping « {0} » (https://hc-ping.com/…)' -f $signal) -Parameter 'Support' -Value '' `
            -Validate { param($v) Test-CogesPingUrl $v } -Rule 'une adresse https://hc-ping.com/<uuid>, copiée depuis Healthchecks.io.'
    }
    $setting.telephone_coges = Read-CogesAnswer -Question 'Numéro de CoGes affiché par « Aide CoGes »' -Parameter 'Support' -Value '' -Optional `
        -Validate { param($v) $v -match '^[0-9 +().-]{6,25}$' } -Rule 'chiffres, espaces, + ( ) . -'
    $setting.remontee = $true
    if ($script:CogesState.Simulation) { Write-CogesLine '[simulation] support.json écrit (adresses, numéro)'; return }
    Write-CogesSupportSetting -Paths $Paths -Setting $setting
    Write-CogesLine 'Adresses posées. Essai : -Action TesterSupport.' -Kind Ok
}

function Initialize-CogesSupportLog {
    param([Parameter(Mandatory)] $Paths)
    if ($script:CogesState.Simulation) { return }
    New-Item -ItemType Directory -Force -Path $Paths.Journaux | Out-Null
    $script:CogesState.LogPath = Join-Path $Paths.Journaux ('support-{0}.log' -f (Get-Date).ToString('yyyyMMdd'))
}

function Send-CogesUpdateWaitPing {
    <# Une version prête attend depuis plus de 3 jours : /fail « mise-a-jour », une fois par jour. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [datetime] $Now)
    $state = Read-CogesSupportState $Paths
    $today = $Now.ToString('yyyy-MM-dd')
    if ($state['derniere_attente_signalee'] -eq $today) { return $false }
    $sent = Send-CogesPing -Paths $Paths -Signal 'mise-a-jour' -Failure -Reason 'attente-3-jours'
    if ($sent) { Write-CogesSupportState -Paths $Paths -Changes @{ derniere_attente_signalee = $today } }
    return $sent
}

function Show-CogesSupportState {
    <# Les lignes du lot 6 dans Etat : jamais une adresse. #>
    param([Parameter(Mandatory)] $Paths)
    $setting = Read-CogesSupportSetting $Paths
    $state = Read-CogesSupportState $Paths
    $last = ConvertTo-CogesStateDate $state['dernier_envoi']
    $lastText = 'jamais'
    if ($last) { $lastText = '{0} ({1}, {2})' -f $last.ToString('dd/MM/yyyy HH:mm'), $state['dernier_signal'], $state['dernier_resultat'] }
    if ($setting.remontee) { Write-CogesLine ('  Remontée vers CoGes : active ({0} adresse(s)), dernier envoi le {1}' -f $setting.adresses.Count, $lastText) -Kind Ok }
    else { Write-CogesLine '  Remontée vers CoGes : inactive (-Action Reparer -Support <fichier.json>)' -Kind Attention }
    $failed = ConvertTo-CogesStateDate $state['dernier_echec_envoi']
    if ($setting.remontee -and $failed -and (-not $last -or $failed -gt $last)) {
        Write-CogesLine ('  Dernier envoi raté : {0} (Internet coupé ?)' -f $failed.ToString('dd/MM/yyyy HH:mm')) -Kind Attention
    }
    $size = 0
    $files = @(Get-ChildItem -LiteralPath $Paths.Journaux -File -ErrorAction SilentlyContinue)
    foreach ($file in $files) { $size += $file.Length }
    Write-CogesLine ('  Journaux          : {0:N1} Mo en {1} fichier(s) ({2} ; 60 jours et 200 Mo au plus)' -f ($size / 1MB), $files.Count, $Paths.Journaux)
}

# ---------------------------------------------------------------------------- bloc E : journaux bornés

function Invoke-CogesLogRotation {
    <# Fichiers de plus de 60 jours supprimés, puis total plafonné à 200 Mo, les plus anciens
       d'abord. Jamais un fichier du jour. Rend le nombre de fichiers supprimés ; n'échoue jamais. #>
    param([Parameter(Mandatory)] [string] $Folder, [Nullable[datetime]] $Now = $null, [long] $MaxBytes = $script:CogesLogMaxBytes, [int] $KeepDays = $script:CogesLogKeepDays)
    if ($null -eq $Now) { $Now = Get-Date }
    $removed = 0
    try {
        $today = $Now.Date
        $files = @(Get-ChildItem -LiteralPath $Folder -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime)
        $kept = New-Object System.Collections.Generic.List[object]
        foreach ($file in $files) {
            $isToday = ($file.LastWriteTime.Date -ge $today) -or ($file.Name -match ('-' + $Now.ToString('yyyyMMdd')))
            if (-not $isToday -and $file.LastWriteTime -lt $Now.AddDays(-$KeepDays)) {
                Remove-Item -LiteralPath $file.FullName -Force
                $removed++
            }
            else { $kept.Add([pscustomobject]@{ File = $file; Today = $isToday }) }
        }
        $total = 0
        foreach ($item in $kept) { $total += $item.File.Length }
        foreach ($item in $kept) {
            if ($total -le $MaxBytes) { break }
            if ($item.Today) { continue }
            $total -= $item.File.Length
            Remove-Item -LiteralPath $item.File.FullName -Force
            $removed++
        }
        if ($removed -gt 0) { Write-Log -Message ('journaux : {0} fichier(s) ancien(s) supprimé(s)' -f $removed) }
    }
    catch { Write-Log -Message ('rotation des journaux : ' + $_.Exception.Message) -Level ATTENTION }
    return $removed
}

# ---------------------------------------------------------------------------- bloc C : diagnostic

function ConvertTo-CogesEnvNameList {
    <# coges.env réduit aux NOMS des variables : jamais une valeur. #>
    param([AllowEmptyString()] [string] $Text)
    return @(($Text -split "`r?`n") | Where-Object { $_ -match '^\s*([A-Z][A-Z0-9_]*)\s*=' } | ForEach-Object { ($_ -replace '^\s*([A-Z][A-Z0-9_]*)\s*=.*$', '$1') })
}

function Write-CogesMaskedFile {
    param([Parameter(Mandatory)] [string] $Path, [AllowEmptyCollection()] [AllowNull()] [string[]] $Lines)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    $masked = @(@($Lines) | ForEach-Object { Mask-Secrets $_ })
    [IO.File]::WriteAllText($Path, (($masked -join "`n") + "`n"), (New-Object Text.UTF8Encoding $false))
}

function Get-CogesTaskReport {
    if (-not (Test-CogesWindows)) { return @('(tâches planifiées : Windows seulement)') }
    $lines = @()
    foreach ($name in @($script:CogesTaskName, $script:CogesBackupTaskName, $script:CogesUpdateTaskName)) {
        try {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
            $info = $task | Get-ScheduledTaskInfo
            $lines += ('{0} : {1}, dernier passage {2}, résultat {3}, prochain {4}' -f $name, $task.State, $info.LastRunTime, $info.LastTaskResult, $info.NextRunTime)
        }
        catch { $lines += ('{0} : absente' -f $name) }
    }
    return $lines
}

function Get-CogesCommandLine {
    <# Les lignes d'une commande docker, pour le diagnostic (jamais une exception). #>
    param([Parameter(Mandatory)] [string] $Title, [Parameter(Mandatory)] [scriptblock] $Command)
    $lines = @(('== ' + $Title))
    try {
        $result = & $Command
        $lines += @($result.Output)
        if ($result.ExitCode -ne 0) { $lines += ('(code {0})' -f $result.ExitCode) }
    }
    catch { $lines += ('(impossible : ' + $_.Exception.Message + ')') }
    return $lines
}

function New-CogesDiagnosticFolder {
    <# Le contenu du diagnostic, dans un dossier : $Tail dernières lignes par service. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [string] $Folder, [Parameter(Mandatory)] [int] $Tail, [Parameter(Mandatory)] [string[]] $StateLines,
        [Parameter(Mandatory)] [string] $Summary, [Parameter(Mandatory)] [datetime] $Now)
    if (Test-Path -LiteralPath $Folder) { Remove-Item -LiteralPath $Folder -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $Folder | Out-Null
    Write-CogesMaskedFile -Path (Join-Path $Folder 'etat.txt') -Lines $StateLines
    Write-CogesMaskedFile -Path (Join-Path $Folder 'resume.txt') -Lines @($Summary -split "`n")
    $engine = Get-CogesDockerEngineProblem
    $docker = @()
    if ($null -eq $engine) {
        $docker += Get-CogesCommandLine 'coges ps' { Invoke-CogesCompose -Paths $Paths -Arguments @('ps', '-a') }
        $docker += Get-CogesCommandLine 'docker version' { Invoke-Docker -Arguments @('version') }
        $docker += Get-CogesCommandLine 'docker info (abrégé)' { Invoke-Docker -Arguments @('info', '--format', 'Serveur {{.ServerVersion}} | {{.OperatingSystem}} | {{.NCPU}} processeurs | {{.MemTotal}} octets | conteneurs {{.ContainersRunning}}/{{.Containers}} | images {{.Images}} | pilote {{.Driver}}') }
        foreach ($service in $script:CogesServices) {
            $logs = Invoke-CogesCompose -Paths $Paths -Arguments @('logs', '--no-color', '--timestamps', '--tail', [string]$Tail, $service)
            Write-CogesMaskedFile -Path (Join-Path $Folder ('services\{0}.log' -f $service)) -Lines @($logs.Output)
        }
    }
    else { $docker += ('Docker : ' + $script:CogesDockerStoppedText) }
    $docker += ('== wsl --version : ' + (Get-CogesWslVersion))
    $docker += ('== système : {0} ; PowerShell {1}' -f [Environment]::OSVersion.VersionString, $PSVersionTable.PSVersion)
    Write-CogesMaskedFile -Path (Join-Path $Folder 'docker.txt') -Lines $docker
    # Journaux de CoGes des 7 derniers jours (déjà masqués, et masqués encore), raccourcis comme les services.
    $since = $Now.AddDays(-$script:CogesDiagnosticLogDays)
    foreach ($file in @(Get-ChildItem -LiteralPath $Paths.Journaux -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $since })) {
        $lines = @([IO.File]::ReadAllLines($file.FullName))
        $keep = $Tail * 10
        if ($lines.Count -gt $keep) { $lines = @(('(… {0} lignes plus anciennes retirées)' -f ($lines.Count - $keep))) + @($lines[($lines.Count - $keep)..($lines.Count - 1)]) }
        Write-CogesMaskedFile -Path (Join-Path $Folder ('journaux\' + $file.Name)) -Lines $lines
    }
    $settings = @('== coges.env (noms seulement, jamais les valeurs)')
    if (Test-Path -LiteralPath $Paths.EnvFile) { $settings += ConvertTo-CogesEnvNameList ([IO.File]::ReadAllText($Paths.EnvFile)) }
    $support = Read-CogesSupportSetting $Paths
    $settings += ('== support.json : pc {0}, remontée {1}, {2} adresse(s) (non recopiées)' -f $support.pc, $(if ($support.remontee) { 'active' } else { 'inactive' }), $support.adresses.Count)
    $update = (Get-CogesUpdatePath $Paths).Reglage
    if (Test-Path -LiteralPath $update) { $settings += '== mise-a-jour.json'; $settings += @([IO.File]::ReadAllLines($update)) }
    Write-CogesMaskedFile -Path (Join-Path $Folder 'reglages.txt') -Lines $settings
    $backups = @('== C:\CoGes\sauvegardes (noms, tailles, dates ; pas les fichiers)')
    $backupFolder = (Get-CogesBackupPath $Paths).Dossier
    foreach ($file in @(Get-ChildItem -LiteralPath $backupFolder -File -ErrorAction SilentlyContinue | Sort-Object Name)) {
        $backups += ('{0}  {1:N0} o  {2}' -f $file.Name, $file.Length, $file.LastWriteTime.ToString('dd/MM/yyyy HH:mm'))
    }
    Write-CogesMaskedFile -Path (Join-Path $Folder 'sauvegardes.txt') -Lines $backups
    $system = @()
    try {
        $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Paths.Racine)))
        $system += ('Disque {0} : {1:N1} Go libres sur {2:N1} Go' -f $drive.Name, ($drive.AvailableFreeSpace / 1GB), ($drive.TotalSize / 1GB))
    }
    catch { $system += 'Disque : illisible' }
    $system += ('Mémoire : {0} Go' -f (Get-CogesMemoryGo))
    $system += '== Tâches planifiées de CoGes'
    $system += Get-CogesTaskReport
    Write-CogesMaskedFile -Path (Join-Path $Folder 'systeme.txt') -Lines $system
}

function New-CogesDiagnostic {
    <# Le zip du diagnostic (Bureau, ou -Destination) : sans secret, sans donnée commerciale,
       10 Mo au plus (journaux raccourcis sinon). Rend le chemin du zip. #>
    param([Parameter(Mandatory)] $Paths, [string] $Destination = '', [Nullable[datetime]] $Now = $null)
    if ($null -eq $Now) { $Now = Get-Date }
    if (-not $Destination) { $Destination = Get-CogesDesktopPath }
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # Etat, sans question : sa sortie est gardée telle qu'elle s'affiche.
    $before = $script:CogesState.Output.Count
    $interactive = $script:CogesState.NonInteractif
    $script:CogesState.NonInteractif = $true
    try { Show-CogesState -Paths $Paths -Options @{ CodeBoutique = '' } }
    catch { $script:CogesState.Output.Add('Etat : ' + $_.Exception.Message) }
    finally { $script:CogesState.NonInteractif = $interactive }
    $stateLines = @($script:CogesState.Output | Select-Object -Skip $before)
    $setting = Read-CogesSupportSetting $Paths
    $summary = '(identifiant du PC absent : résumé non calculé)'
    $fields = Get-CogesFieldList $Paths
    if ($setting.pc -and $fields) {
        try { $summary = Format-CogesReport (Get-CogesReport -Facts (Read-CogesReportFact -Paths $Paths -Pc $setting.pc -Signal 'test' -Now $Now) -Fields $fields) }
        catch { $summary = '(résumé impossible : ' + $_.Exception.Message + ')' }
    }
    $zip = Join-Path $Destination ('CoGes-diagnostic-{0}.zip' -f $Now.ToString('yyyyMMdd-HHmm'))
    $work = Join-Path ([IO.Path]::GetTempPath()) ('coges-diagnostic-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    try {
        foreach ($tail in $script:CogesDiagnosticTails) {
            New-CogesDiagnosticFolder -Paths $Paths -Folder $work -Tail $tail -StateLines $stateLines -Summary $summary -Now $Now
            if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
            [IO.Compression.ZipFile]::CreateFromDirectory($work, $zip, [IO.Compression.CompressionLevel]::Optimal, $false)
            if ((Get-Item -LiteralPath $zip).Length -le $script:CogesDiagnosticMaxBytes) { break }
            Write-Log -Message ('diagnostic de plus de 10 Mo avec {0} lignes par service : raccourci' -f $tail) -Level ATTENTION
        }
        if ((Get-Item -LiteralPath $zip).Length -gt $script:CogesDiagnosticMaxBytes) {
            Remove-Item -LiteralPath $zip -Force
            Stop-CogesStep -Probleme 'Le diagnostic dépasse 10 Mo même raccourci.' -QuoiFaire 'Appelez CoGes : la prise en main à distance (« Aide CoGes ») permet de regarder directement.'
        }
    }
    finally { if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force } }
    return $zip
}

function Invoke-CogesDiagnosticAction {
    <# -Action Diagnostic (et le raccourci « Diagnostic CoGes ») : le zip, où il est, à qui l'envoyer. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if ($script:CogesState.Simulation) {
        foreach ($step in @('Etat et résumé', 'coges ps, docker version, docker info (abrégé), wsl, Windows', 'journaux des 7 derniers jours (masqués)',
                '300 dernières lignes par service (masquées)', 'coges.env : noms seulement', 'liste des sauvegardes', 'disque, mémoire, tâches planifiées',
                'zip de 10 Mo au plus sur le Bureau')) { Write-CogesLine ('[simulation] ' + $step) }
        return
    }
    Initialize-CogesSupportLog $Paths
    Write-CogesLine 'Préparation du fichier de diagnostic (une minute environ)…' -Kind Titre
    $zip = New-CogesDiagnostic -Paths $Paths
    $size = (Get-Item -LiteralPath $zip).Length
    Write-CogesLine ''
    Write-CogesLine ('Le fichier est prêt sur le Bureau : {0} ({1:N1} Mo).' -f (Split-Path -Leaf $zip), ($size / 1MB)) -Kind Ok
    Write-CogesLine 'Envoyez-le à CoGes par WhatsApp ou par e-mail. Il ne contient ni mot de passe, ni vente, ni client.' -Kind Ok
    $phone = (Read-CogesSupportSetting $Paths).telephone_coges
    if ($phone) { Write-CogesLine ('Numéro de CoGes : {0}' -f $phone) -Kind Ok }
    if ($Options.Bureau -and (Test-CogesWindows)) {
        try { Start-Process -FilePath 'explorer.exe' -ArgumentList ('/select,"{0}"' -f $zip) } catch { Write-Log -Message ('explorateur : ' + $_.Exception.Message) -Level ATTENTION }
    }
}

# ---------------------------------------------------------------------------- bloc D : aide à distance (Assistance rapide)

function Get-CogesHelpText {
    <# La marche à suivre de « Aide CoGes », en trois phrases. #>
    param([AllowEmptyString()] [string] $Phone)
    $call = 'Appelez CoGes.'
    if ($Phone) { $call = 'Appelez CoGes au {0}.' -f $Phone }
    return @($call, 'Donnez le code affiché par l''Assistance rapide.', 'Acceptez quand CoGes demande à prendre la main : vous voyez tout, et vous pouvez arrêter à tout moment.')
}

function Test-CogesQuickAssist {
    if (-not (Test-CogesWindows)) { return $false }
    try { return [bool](Get-AppxPackage -Name $script:CogesQuickAssistPackage -ErrorAction Stop) } catch { return $false }
}

function Invoke-CogesHelpAction {
    <# -Action Aide (raccourci « Aide CoGes ») : ouvre l'Assistance rapide de Windows, affiche le
       numéro de CoGes. N'installe rien, ne laisse rien ouvert : chaque séance se fait avec un
       code donné par le commerçant, qu'il accepte. #>
    param([Parameter(Mandatory)] $Paths)
    $phone = (Read-CogesSupportSetting $Paths).telephone_coges
    Write-CogesLine 'Aide CoGes' -Kind Titre
    foreach ($line in (Get-CogesHelpText $phone)) { Write-CogesLine ('  ' + $line) -Kind Ok }
    if ($script:CogesState.Simulation) { Write-CogesLine '[simulation] ouverture de l''Assistance rapide'; return }
    if (Test-CogesQuickAssist) {
        try { Start-Process 'ms-quick-assist:'; return } catch { Write-Log -Message ('Assistance rapide : ' + $_.Exception.Message) -Level ATTENTION }
    }
    Write-CogesLine ''
    Write-CogesLine 'L''Assistance rapide n''est pas sur ce PC. Pour l''installer : ouvrez le Microsoft Store, cherchez « Assistance rapide » (Quick Assist), cliquez sur Obtenir, puis relancez « Aide CoGes ».' -Kind Attention
    if (Test-CogesWindows) { try { Start-Process $script:CogesQuickAssistStore } catch { Write-Log -Message ('Store : ' + $_.Exception.Message) -Level ATTENTION } }
}

function New-CogesSupportShortcutText {
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [ValidateSet('Aide', 'Diagnostic')] [string] $Action)
    $script = Join-Path $Paths.Programme 'windows\installer.ps1'
    return ("@echo off`r`nrem CoGes : {0} (ADR 0129).`r`n" -f $Action) +
    ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Action {1} -Bureau -Racine "{2}"' -f $script, $Action, $Paths.Racine) + "`r`n"
}

function Install-CogesSupportShortcut {
    <# « Aide CoGes » et « Diagnostic CoGes » sur le Bureau. #>
    [Diagnostics.CodeAnalysis.SuppressMessageAttribute('PSReviewUnusedParameter', '',
        Justification = 'Lus dans le bloc de l''étape (Invoke-CogesStep), que l''analyse ne suit pas.')]
    param([Parameter(Mandatory)] $Paths)
    Invoke-CogesStep -Title 'Raccourcis « Aide CoGes » et « Diagnostic CoGes » sur le Bureau' -Action {
        $desktop = Get-CogesDesktopPath
        New-Item -ItemType Directory -Force -Path $desktop | Out-Null
        [IO.File]::WriteAllText((Join-Path $desktop $script:CogesHelpShortcut), (New-CogesSupportShortcutText -Paths $Paths -Action 'Aide'), [Text.Encoding]::ASCII)
        [IO.File]::WriteAllText((Join-Path $desktop $script:CogesDiagnosticShortcut), (New-CogesSupportShortcutText -Paths $Paths -Action 'Diagnostic'), [Text.Encoding]::ASCII)
    }
}

function Remove-CogesSupportShortcut {
    Invoke-CogesStep -Title 'Raccourcis « Aide CoGes » et « Diagnostic CoGes » retirés (support.json gardé)' -Action {
        $desktop = Get-CogesDesktopPath
        foreach ($name in @($script:CogesHelpShortcut, $script:CogesDiagnosticShortcut)) {
            $file = Join-Path $desktop $name
            if (Test-Path -LiteralPath $file) { Remove-Item -LiteralPath $file -Force }
        }
    }
}
