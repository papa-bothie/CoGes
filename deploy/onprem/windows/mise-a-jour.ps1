<#
.SYNOPSIS
    Tâche planifiée « CoGes - mise à jour » (ADR 0128) : 12 h, 18 h, ouverture de session, et l'heure du soir.

.DESCRIPTION
    Lit le canal (reglages\mise-a-jour.json : stable ou test) et télécharge une nouvelle version
    pendant que CoGes tourne ; à l'heure réglée (21 h 30 par défaut), l'applique si aucune vente
    depuis 30 minutes, jamais au démarrage du PC ; revient seul en arrière si quelque chose
    casse. Au bout de 3 jours d'attente : raccourci « Mettre CoGes à jour » sur le Bureau et un
    rappel par jour. Aucune question, aucune fenêtre ; ne fait rien si Docker ne répond pas.
    Journal : C:\CoGes\journaux\mise-a-jour-AAAAMMJJ.log.
#>
[CmdletBinding()]
param([string] $Racine = 'C:\CoGes')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'CoGes.Install.ps1')

try { exit (Invoke-CogesScheduledUpdate -Racine $Racine) }
catch {
    Write-Log -Message ('échec de la mise à jour planifiée : ' + $_.Exception.Message) -Level ECHEC
    exit 1
}
