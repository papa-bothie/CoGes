# Analyse du script d'installation Windows (ADR 0126), jouée par le workflow « Sur site ».
# Erreurs et avertissements bloquants ; chaque règle écartée l'est pour une raison écrite.
@{
    Severity     = @('Error', 'Warning')
    ExcludeRules = @(
        # Un script pour un technicien devant la console : Write-Host est la sortie voulue
        # (couleurs, rien dans le pipeline qui deviendrait un code de sortie).
        'PSAvoidUsingWriteHost',
        # -WhatIf/-Confirm : le script a son propre mode -Simulation, qui couvre TOUTES les
        # étapes (y compris docker), et ses confirmations tapées (OUI, COPIE-FAITE, EFFACER).
        'PSUseShouldProcessForStateChangingFunctions'
    )
    Rules        = @{
        # Écrit pour Windows PowerShell 5.1 (Windows 11) : toute syntaxe de PowerShell 7
        # seulement (??, ternaire, &&) est refusée.
        PSUseCompatibleSyntax = @{
            Enable         = $true
            TargetVersions = @('5.1', '7.4')
        }
    }
}
