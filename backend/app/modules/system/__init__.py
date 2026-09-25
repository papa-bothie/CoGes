"""Module System — santé du chemin asynchrone, pour le gérant.

Le seul module dont les chiffres ne parlent pas de commerce. Il répond à une question
d'exploitation : « est-ce que ce qui devait partir est parti ? »

Il existe parce que la file de rebut est **en base** et non dans Redis (ADR 0032). Un
événement qui a épuisé ses dix tentatives reste dans `business_events`, rejouable à la
main après correction ; encore faut-il savoir qu'il est là. Sans cet écran, un agrégat
silencieusement figé serait découvert par le gérant, pas par l'exploitant.

Permission `system:read`, gérant seul : ce n'est ni une information comptable, ni une
information de caisse.
"""
