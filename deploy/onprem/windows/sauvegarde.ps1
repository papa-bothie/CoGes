<#
.SYNOPSIS
    Tâche planifiée « CoGes - sauvegarde » (ADR 0127) : 13 h 00, 20 h 30 et à l'ouverture de session.

.DESCRIPTION
    Sauvegarde si une heure prévue est passée depuis la dernière bonne, ou si elle a plus de
    20 h (PC éteint la nuit) ; restauration d'essai une fois par semaine (le dimanche, ou au
    premier passage après) ; copie sur la clé CoGes si elle est branchée ; notification
    Windows seulement quand il faut agir. Aucune question, aucune fenêtre ; ne fait rien si
    Docker ne répond pas. Journal : C:\CoGes\journaux\sauvegarde-AAAAMMJJ.log.
#>
[CmdletBinding()]
param([string] $Racine = 'C:\CoGes')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'CoGes.Install.ps1')

try { exit (Invoke-CogesScheduledBackup -Racine $Racine) }
catch {
    Write-Log -Message ('échec de la sauvegarde planifiée : ' + $_.Exception.Message) -Level ECHEC
    exit 1
}
