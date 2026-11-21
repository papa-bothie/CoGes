<#
.SYNOPSIS
    Installe CoGes sur le PC d'un client, en une commande (ADR 0126).

.DESCRIPTION
    Enchaîne les étapes 1 à 11 du guide docs/runbooks/sur-site.md : contrôle du PC, pose du
    programme, réglages, images, base, démarrage, société, licence, raccourcis.

    À lancer dans une fenêtre PowerShell (pas dans un éditeur), avec le compte Windows qui a
    Docker Desktop. Les droits d'administrateur ne sont pas nécessaires.

        Invoke-WebRequest https://raw.githubusercontent.com/papa-bothie/CoGes/vX.Y.Z/deploy/onprem/windows/installer.ps1 -OutFile $env:TEMP\coges-install.ps1 -UseBasicParsing
        powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\coges-install.ps1 -Version vX.Y.Z

    Une fois installé, le script est aussi dans C:\CoGes\programme\windows\installer.ps1.

.PARAMETER Action
    Installer (défaut), Reparer, Etat, Desinstaller ; sauvegarde (ADR 0127) : Sauvegarder,
    Restaurer, PreparerDisque, NettoyerAncienneBase.
.PARAMETER Version
    La version de CoGes, vX.Y.Z (obligatoire pour Installer ; Reparer garde celle des réglages si absente).
.PARAMETER Simulation
    Annonce chaque étape sans rien écrire ni lancer.
.PARAMETER Racine
    Dossier de CoGes (C:\CoGes par défaut).
.PARAMETER Port
    Port de CoGes sur ce PC (sinon 80, ou 8080 si 80 est pris).
.PARAMETER NonInteractif
    Ne pose aucune question : toute réponse manquante est un échec (tests).
.PARAMETER CopieFaite
    En -NonInteractif : confirme que coges.env est copié dans le gestionnaire de mots de passe.
.PARAMETER EffacerLesDonnees
    Avec Desinstaller : efface aussi les volumes (données), après une sauvegarde de moins d'une
    heure. Demande le code de la boutique.
.PARAMETER Fichier
    Avec Restaurer : la sauvegarde (coges-….coges, avec ses .sha256 et .manifest.json à côté).
    Sans lui, la liste des sauvegardes du PC et de la clé CoGes branchée est proposée.
.PARAMETER Cle
    Avec Restaurer : le fichier de la clé PRIVÉE du client (lue, jamais copiée sur le PC).
.PARAMETER Lecteur
    Avec PreparerDisque (et Installer) : la clé USB ou le disque de sauvegarde, par ex. E:.
.PARAMETER ClePublique
    Installer, Reparer : le fichier de la clé publique de sauvegarde tirée chez CoGes.
.PARAMETER LecteurCle
    Installer, Reparer sans -ClePublique : le disque amovible où écrire la clé privée tirée ici.
.PARAMETER CleCopiee
    En -NonInteractif : confirme que la clé privée est rangée chez CoGes.
.PARAMETER ConfirmerRestauration
    En -NonInteractif : confirme RESTAURER.
.PARAMETER RestaurerQuandMeme
    En -NonInteractif : confirme RESTAURER-QUAND-MEME (sauvegarde sans vente, ou avec moins de
    ventes que la base actuelle).
.PARAMETER Essai
    Avec Sauvegarder : fait aussi la restauration d'essai.
.PARAMETER SansNotification
    Aucune notification Windows (essais).
#>
[CmdletBinding()]
param(
    [ValidateSet('Installer', 'Reparer', 'Etat', 'Desinstaller', 'Sauvegarder', 'Restaurer', 'PreparerDisque', 'NettoyerAncienneBase')] [string] $Action = 'Installer',
    [string] $Version = '',
    [switch] $Simulation,
    [string] $Racine = 'C:\CoGes',
    [int] $Port = 0,
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
    [switch] $SansNotification
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Les fonctions : à côté de ce fichier (C:\CoGes\programme\windows\, ou le dépôt) ; sinon,
# lancé seul depuis %TEMP%, celles de la même version, sur le même dépôt public.
$library = Join-Path $PSScriptRoot 'CoGes.Install.ps1'
if (-not (Test-Path -LiteralPath $library)) {
    if ($Version -notmatch '^v[0-9]+\.[0-9]+\.[0-9]+$') {
        Write-Host 'ÉCHEC — il manque la version (-Version vX.Y.Z), au format vX.Y.Z, jamais « latest ».' -ForegroundColor Red
        Write-Host 'Quoi faire : relancez avec -Version suivie de la version donnée par CoGes, ou lancez C:\CoGes\programme\windows\installer.ps1.' -ForegroundColor Red
        exit 1
    }
    $folder = Join-Path ([IO.Path]::GetTempPath()) ('coges-install-' + $Version)
    New-Item -ItemType Directory -Force -Path $folder | Out-Null
    $library = Join-Path $folder 'CoGes.Install.ps1'
    $source = 'https://raw.githubusercontent.com/papa-bothie/CoGes/{0}/deploy/onprem/windows/CoGes.Install.ps1' -f $Version
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = 'SilentlyContinue'
    try {
        Invoke-WebRequest -Uri $source -OutFile $library -UseBasicParsing -TimeoutSec 120
    }
    catch {
        Write-Host ('ÉCHEC — les fonctions de la version {0} ne se téléchargent pas ({1}).' -f $Version, $source) -ForegroundColor Red
        Write-Host 'Quoi faire : vérifiez la version et la connexion Internet, puis relancez.' -ForegroundColor Red
        exit 1
    }
}
. $library

$code = Invoke-CogesMain @PSBoundParameters
exit $code
