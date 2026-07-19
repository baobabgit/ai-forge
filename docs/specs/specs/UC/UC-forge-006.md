---
id: UC-forge-006
type: UC
parent: null
library: ai-forge
status: DONE
gates:
  auto: []
  ai_judged:
  - Toutes les FEAT enfants sont GO
  - Le scénario de bout en bout du UC est exécuté et validé par une IA n'ayant pas
    développé
---

# UC-forge-006 — Générer l'architecture et les spécifications du projet cible

## Description
Phases 1 et 2 : à partir d'un CDC Markdown, produire le document d'architecture (librairies, trajectoires de versions SemVer, jalons d'intégration) puis les specs UC/FEAT/BL de chaque librairie, chaque lot étant produit par une IA et contre-relu par une autre avant commit.

## Acteurs
- Orchestrateur
- Provider rôle ARCHITECT
- Provider rôle SPEC
- Provider contre-relecteur

## Préconditions
- CDC du projet cible au format Markdown fourni à forge init
- Phase précédente validée le cas échéant

## Scénario nominal
1. ARCHITECT produit : liste des librairies, CDC complet par librairie, trajectoires de versions, jalons inter-librairies (milestones.md).
2. Un second provider contre-relit (dépendances circulaires, redondances, versions incohérentes) ; en cas d'anomalie l'ARCHITECT est relancé avec le rapport (3 itérations max, puis remontée humaine).
3. SPEC génère les UC (un fichier par UC, frontmatter valide), puis en dérive FEAT et BL avec gates GO/NO-GO à chaque niveau.
4. Un provider différent contre-relit les specs : complétude, testabilité des critères, cohérence des dépendances ; puis commit.

## Scénarios alternatifs et d'erreur
- 3 itérations d'architecture sans convergence : arrêt et remontée à l'humain avec le dernier rapport.
- Spec générée au frontmatter invalide : rejetée par le parser, renvoyée au SPEC avec l'erreur exacte.

## Postconditions
- Chaque librairie dispose de specs committées, machine-readable, aux critères testables.

## Exigences non fonctionnelles applicables
- EXG-ARC-01..05
- EXG-SPE-01..08

## Critères GO/NO-GO (niveau UC — EXG-SPE-07)
- GO si toutes les FEAT enfants sont GO **et** le scénario de bout en bout est exécuté et validé.