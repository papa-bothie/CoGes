<#
.SYNOPSIS
    Tâche planifiée « CoGes - démarrage » (ADR 0126) : filet de sécurité à l'ouverture de session.

.DESCRIPTION
    Le vrai démarrage reste « Start Docker Desktop when you sign in » (Docker relance les
    conteneurs). Ce script attend que le moteur Docker réponde (5 minutes au plus) puis lance
    « docker compose up -d ». Il ne pose aucune question et n'affiche rien ; il écrit dans
    C:\CoGes\journaux\demarrage-AAAAMMJJ.log.
#>
[CmdletBinding()]
param([string] $Racine = 'C:\CoGes')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'CoGes.Install.ps1')

try { exit (Start-CogesAtLogon -Racine $Racine) }
catch {
    Write-Log -Message ('échec du démarrage : ' + $_.Exception.Message) -Level ECHEC
    exit 1
}
