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
    'postgres-init/01-roles.sql'
)
#: Lus par un conteneur Linux : un « \r » les casserait.
$script:CogesLfFiles = @('Caddyfile', 'postgres-init/01-roles.sql')

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
        [switch] $Interactive
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
            $lines = @(& docker @Arguments 2>&1)
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
    param([Parameter(Mandatory)] [string] $Racine, [int] $TimeoutSeconds = 300)
    $paths = Get-CogesPath $Racine
    $script:CogesState.LogPath = Join-Path $paths.Journaux ('demarrage-{0}.log' -f (Get-Date).ToString('yyyyMMdd'))
    New-Item -ItemType Directory -Force -Path $paths.Journaux | Out-Null
    [void](Get-CogesSetting $paths)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if ((Invoke-Docker -Arguments @('version', '--format', '{{.Server.Os}}')).ExitCode -eq 0) {
            $up = Invoke-CogesCompose -Paths $paths -Arguments @('up', '-d')
            Write-Log -Message ('up -d : code {0}' -f $up.ExitCode)
            return $up.ExitCode
        }
        Start-Sleep -Seconds 10
    }
    Write-Log -Message 'Le moteur Docker n''a pas répondu en 5 minutes : rien lancé.' -Level ECHEC
    return 1
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
        Write-CogesLine 'Il n''existe pas encore de sauvegarde sur site (lot 4) : rien ne ramènera ces données.' -Kind Echec
        Confirm-CogesWord -Word 'EFFACER' -Prompt ('Effacer pour toujours les données de {0} ?' -f $slug)
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
        [ValidateSet('Installer', 'Reparer', 'Etat', 'Desinstaller')] [string] $Action = 'Installer',
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
        [string] $NoteContrat = ''
    )
    $script:CogesState.Simulation = [bool]$Simulation
    $script:CogesState.NonInteractif = [bool]$NonInteractif
    $script:CogesState.LogPath = $null
    $script:CogesState.Output.Clear()
    $paths = Get-CogesPath $Racine
    $options = @{
        Version = $Version; Port = $Port; CopieFaite = [bool]$CopieFaite; EffacerLesDonnees = [bool]$EffacerLesDonnees
        NomBoutique = $NomBoutique; CodeBoutique = $CodeBoutique; NomGerant = $NomGerant
        TelephoneGerant = $TelephoneGerant; EmailGerant = $EmailGerant; Offre = $Offre; NoteContrat = $NoteContrat
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
