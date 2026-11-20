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
    'windows/sauvegarde.ps1'
)
#: Lus par un conteneur Linux : un « \r » les casserait.
$script:CogesLfFiles = @('Caddyfile', 'postgres-init/01-roles.sql', 'sauvegarde/pg.sh')

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
    $text = [IO.File]::ReadAllText($Path)
    $newline = "`n"
    if ($text.Contains("`r`n")) { $newline = "`r`n" }
    $pending = @{}
    foreach ($key in $Values.Keys) { $pending[$key] = $true }
    $lines = foreach ($raw in ($text -split "`r?`n")) {
        if ($raw -match '^\s*([A-Z0-9_]+)\s*=' -and $Values.Contains($Matches[1])) {
            $pending.Remove($Matches[1])
            $Matches[1] + '=' + $Values[$Matches[1]]
        }
        else { $raw }
    }
    $result = ($lines -join $newline).TrimEnd("`r", "`n") + $newline
    foreach ($key in $pending.Keys) { $result += $key + '=' + $Values[$key] + $newline }
    [IO.File]::WriteAllText($Path, $result, (New-Object Text.UTF8Encoding $false))
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

function Install-Programme {
    <# Pose deploy/onprem/ de l'archive dans <Racine>\programme, en REMPLAÇANT le dossier en
       entier. Ne touche jamais à reglages\ ni aux données. Réutilisable par le lot 5. #>
    param(
        [Parameter(Mandatory)] [string] $Archive,
        [Parameter(Mandatory)] [string] $Racine,
        [Parameter(Mandatory)] [string] $Version
    )
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $paths = Get-CogesPath $Racine
    $staging = Join-Path $Racine ('programme.nouveau-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    $previous = $paths.Programme + '.ancien'
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    try {
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
        [IO.File]::WriteAllText((Join-Path $staging '.version'), $Version + "`n", (New-Object Text.UTF8Encoding $false))
        if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
        if (Test-Path -LiteralPath $paths.Programme) { Rename-Item -LiteralPath $paths.Programme -NewName (Split-Path -Leaf $previous) }
        Rename-Item -LiteralPath $staging -NewName 'programme'
        if (Test-Path -LiteralPath $previous) { Remove-Item -LiteralPath $previous -Recurse -Force }
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
    $script:CogesState.MaskValues = Get-CogesMaskValue $values
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
                return 1
            }
            try {
                $up = Invoke-CogesCompose -Paths $paths -Arguments @('up', '-d')
                Write-Log -Message ('up -d : code {0}' -f $up.ExitCode)
                return $up.ExitCode
            }
            finally { Exit-CogesLock $lock }
        }
        Start-Sleep -Seconds 10
    }
    Write-Log -Message 'Le moteur Docker n''a pas répondu en 5 minutes : rien lancé.' -Level ECHEC
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

$script:CogesBackupPattern = '^coges-(?<slug>[a-z0-9]+(?:-[a-z0-9]+)*)-(?<date>\d{8})-(?<time>\d{4}(?:\d{2})?)-(?<version>[A-Za-z0-9][A-Za-z0-9.-]*)\.coges$'

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
    <# coges-<code-boutique>-AAAAMMJJ-HHMM-<version>.coges #>
    param(
        [Parameter(Mandatory)] [string] $Slug,
        [Parameter(Mandatory)] [datetime] $Date,
        [Parameter(Mandatory)] [string] $Version,
        [switch] $WithSeconds
    )
    $format = 'yyyyMMdd-HHmm'
    if ($WithSeconds) { $format = 'yyyyMMdd-HHmmss' }
    return ('coges-{0}-{1}-{2}.coges' -f $Slug, $Date.ToString($format, [Globalization.CultureInfo]::InvariantCulture), $Version)
}

function ConvertFrom-CogesBackupName {
    <# Le code, la date et la version d'un nom de sauvegarde ; $null pour tout autre nom. #>
    param([AllowEmptyString()] [string] $Name)
    if ($Name -cnotmatch $script:CogesBackupPattern) { return $null }
    $stamp = $Matches['date'] + $Matches['time'].PadRight(6, '0')
    $date = [datetime]::ParseExact($stamp, 'yyyyMMddHHmmss', [Globalization.CultureInfo]::InvariantCulture)
    return [pscustomobject]@{ Name = $Name; Slug = $Matches['slug']; Date = $date; Version = $Matches['version'] }
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
        [Nullable[datetime]] $Now = $null
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
        $name = Get-CogesBackupName -Slug $slug -Date $Now -Version $version
        if (Test-Path -LiteralPath (Join-Path $backup.Dossier $name)) { $name = Get-CogesBackupName -Slug $slug -Date $Now -Version $version -WithSeconds }
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
            $made = New-CogesBackup -Paths $Paths -Trial:$trial
            Write-CogesLine ('  {0} ({1:N1} Mo), chiffrée et relue.' -f $made.Path, ($made.Size / 1MB)) -Kind Ok
            if (@($made.Offsite).Count -eq 0) { Write-CogesLine '  Aucune clé CoGes branchée : pas de copie hors du PC cette fois.' -Kind Attention }
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
    $code = 0
    $lock = $null
    try {
        $summary = Get-CogesBackupSummary $paths
        $due = Test-CogesBackupDue -Now $Now -LastGood $summary.LastGood
        $trial = Test-CogesTrialDue -Now $Now -LastSuccess $summary.LastTrialGood
        if (-not $due -and -not $trial) { Write-Log -Message 'Rien à faire : la dernière sauvegarde est récente.' }
        elseif ((Invoke-Docker -Arguments @('version', '--format', '{{.Server.Os}}')).ExitCode -ne 0) {
            Write-Log -Message 'Docker ne répond pas : pas de sauvegarde cette fois.' -Level ATTENTION
        }
        else {
            $lock = Enter-CogesLock -Paths $paths -Action 'Sauvegarde planifiée' -WaitSeconds $LockWaitSeconds -IntervalSeconds 30
            $made = New-CogesBackup -Paths $paths -Trial:$trial
            Write-Log -Message ('sauvegarde bonne : {0}' -f $made.Name) -Level OK
        }
    }
    catch {
        Write-Log -Message ('sauvegarde en échec : ' + $_.Exception.Message) -Level ECHEC
        $code = 1
    }
    finally { Exit-CogesLock $lock }
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

function Restore-CogesBackup {
    <# -Action Restaurer -Fichier <chemin> -Cle <chemin> : chaque étape s'arrête au premier
       problème sans avoir rien changé ; après la bascule, un échec ramène l'ancienne base. #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    if (-not $Options.Fichier) { Stop-CogesStep -Probleme 'Il manque la sauvegarde à restaurer.' -QuoiFaire 'Relancez avec -Fichier <chemin du .coges> et -Cle <fichier de la clé privée>.' }
    if (-not $Options.Cle) { Stop-CogesStep -Probleme 'Il manque la clé privée.' -QuoiFaire 'Relancez avec -Cle <fichier de la clé privée de ce client> (gestionnaire de mots de passe de CoGes).' }
    if ($script:CogesState.Simulation) {
        foreach ($step in @('1. empreinte et manifeste, puis RESTAURER', '2. version', '3. sauvegarde de la base actuelle', '4. restauration à côté (coges_restauration) et contrôles',
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
        # 1. Fichier, empreinte, manifeste, clé : rien n'est changé.
        $source = [IO.Path]::GetFullPath($Options.Fichier)
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
        Confirm-CogesWord -Word 'RESTAURER' -Prompt 'Remplacer les données de ce PC par cette sauvegarde ?' -Given $Options.ConfirmerRestauration -Parameter 'ConfirmerRestauration'

        # 2. Version : la révision doit être connue du programme installé.
        $revisions = Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Révisions du programme installé' -Arguments @('base.py', 'revisions')).Stdout
        if (-not (Test-CogesRevisionKnown -Revision ([string]$manifest.alembic_revision) -Known @($revisions.connues))) {
            Stop-CogesStep -Probleme ('Cette sauvegarde vient de CoGes {0}, plus récent que la version installée ({1}).' -f $manifest.coges_version, $settings['COGES_IMAGE_TAG']) `
                -QuoiFaire ('Installez d''abord la version {0} (-Action Reparer -Version {0}), puis relancez la restauration. Rien n''a changé.' -f $manifest.coges_version)
        }
        $migrate = ([string]$manifest.alembic_revision -ne [string]$revisions.tete)
        Write-CogesLine ('  Version : révision {0} connue de {1}{2}.' -f $manifest.alembic_revision, $settings['COGES_IMAGE_TAG'], $(if ($migrate) { ', la base sera mise à jour après' } else { '' })) -Kind Ok

        # 3. La base actuelle d'abord, si elle existe et n'est pas vide.
        $current = Get-CogesLastJson (Invoke-CogesTool -Paths $Paths -Service 'sauvegarde-py' -What 'Lecture de la base actuelle' -Arguments @('base.py', 'etat')).Stdout
        if ($current.existe -and [int]$current.societes -gt 0) {
            Write-CogesLine '» Sauvegarde de la base actuelle avant tout changement' -Kind Titre
            $before = New-CogesBackup -Paths $Paths
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
            $made = New-CogesBackup -Paths $Paths -Trial
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
    try { return (New-CogesBackup -Paths $Paths).Path }
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
    Install-CogesBackupSetup -Paths $Paths -Options $Options -Slug $answers.CodeBoutique -FirstBackup
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
    Install-CogesBackupSetup -Paths $Paths -Options $Options -Slug $slug
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
    $drive = New-Object IO.DriveInfo ([IO.Path]::GetPathRoot($Paths.Racine))
    Write-CogesLine ('  Disque libre     : {0:N1} Go sur {1}' -f ($drive.AvailableFreeSpace / 1GB), $drive.Name)
    $last = Get-ChildItem -LiteralPath $Paths.Journaux -Filter 'installation-*.log' -ErrorAction SilentlyContinue | Sort-Object Name | Select-Object -Last 1
    if ($last) { Write-CogesLine ('  Dernier journal  : {0}' -f $last.FullName) }
    Show-CogesBackupState $Paths
}

function Invoke-CogesUninstall {
    <# Conteneurs, tâche, raccourci, bin\ et PATH. Réglages et données gardés, sauf
       -EffacerLesDonnees (code de la boutique retapé, puis EFFACER). Jamais « down -v ». #>
    param([Parameter(Mandatory)] $Paths, [Parameter(Mandatory)] [hashtable] $Options)
    $erase = [bool]$Options.EffacerLesDonnees
    if ($erase -and $script:CogesState.NonInteractif) {
        Stop-CogesStep -Probleme 'L''effacement des données exige une personne devant le PC.' -QuoiFaire 'Relancez sans -NonInteractif.'
    }
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
        [ValidateSet('Installer', 'Reparer', 'Etat', 'Desinstaller', 'Sauvegarder', 'Restaurer', 'PreparerDisque', 'NettoyerAncienneBase')] [string] $Action = 'Installer',
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
        [switch] $Essai,
        [switch] $SansNotification
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
        CleCopiee = [bool]$CleCopiee; ConfirmerRestauration = [bool]$ConfirmerRestauration; Essai = [bool]$Essai
    }
    try {
        if ($Port -and ($Port -lt 1 -or $Port -gt 65535)) {
            Stop-CogesStep -Probleme ('-Port {0} n''est pas un numéro de port.' -f $Port) -QuoiFaire 'Donnez un port entre 1 et 65535 (80, 8080…).'
        }
        if ($Action -eq 'Installer') { Assert-CogesVersion $Version }
        Initialize-CogesSession -Paths $paths -Simulation $Simulation -NonInteractif $NonInteractif -WriteLog ($Action -ne 'Etat')
        Write-CogesLine ('CoGes sur site — {0}' -f $Action) -Kind Titre
        if ($Simulation) { Write-CogesLine 'Mode simulation : chaque étape est annoncée, rien n''est écrit ni lancé.' }
        switch ($Action) {
            'Installer' { Invoke-CogesInstall -Paths $paths -Options $options }
            'Reparer' { Invoke-CogesRepair -Paths $paths -Options $options }
            'Etat' { Show-CogesState -Paths $paths -Options $options }
            'Desinstaller' { Invoke-CogesUninstall -Paths $paths -Options $options }
            'Sauvegarder' { Invoke-CogesBackupAction -Paths $paths -Options $options }
            'Restaurer' { Restore-CogesBackup -Paths $paths -Options $options }
            'PreparerDisque' { Invoke-CogesPrepareDisk -Paths $paths -Options $options }
            'NettoyerAncienneBase' { Invoke-CogesCleanOldDatabase -Paths $paths -Options $options }
        }
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
        return 1
    }
}
