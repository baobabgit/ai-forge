# Écart implémentation vs spec v0.1.0 (CDC v1.4)

Document de transition après réalignement documentaire du 2026-07-05.

## Contexte

Le CDC v1.4 redéfinit **v0.1.0** comme un jalon **dry-run/mock** (provider mock, worker unique,
event log exploitable) — **sans** merge réel ni adaptateurs CLI réels.

L'implémentation actuelle sur `main` **avance sur cette spec** :

| Capacité | Spec v0.1.0 | Implémentation actuelle | Version spec cible |
|----------|-------------|-------------------------|-------------------|
| `forge init` / `forge run` | v0.1.0 | ✅ Livré (BL-014) | v0.1.0 |
| Parsing BL + event log | v0.1.0 | ✅ Livré (BL-003, 009, 010) | v0.1.0 |
| Provider **mock** | v0.1.0 | ⚠️ Partiel — pas de mock dédié | v0.1.0 (gap) |
| Chaîne **dry-run** | v0.1.0 | ✅ `--dry-run` skip gates/tester/reviewer | v0.1.0 |
| Adaptateurs Claude/Codex/Cursor | v0.1.1 | ✅ Livré (BL-006..008) | v0.1.1 |
| PR réelle + merge | v0.1.1–v0.1.2 | ✅ Livré (BL-012, 013, 015) | v0.1.1 |
| Gates auto + diff-guard | v0.2.0 | ✅ Livré (BL-016) | v0.2.0 |
| TESTER / REVIEWER | v0.2.0 | ✅ Livré (BL-018, 019) | v0.2.0 |
| Verdicts IA structurés | v0.2.0 | ✅ Livré (BL-017) | v0.2.0 |

## Stratégie recommandée

1. **Ne pas rollback le code** — conserver les BL marqués DONE avec leur `target_version` réaligné.
2. **Combler le gap v0.1.0** — ajouter un provider `mock` explicite (BL-004) et valider le jalon
   dry-run comme critère de release v0.1.0 taguée.
3. **Taguer v0.1.0** quand le dry-run mock est démontrable de bout en bout, indépendamment du
   merge réel déjà fonctionnel.
4. **Repousser** parallélisme (v0.3), multi-repo (v0.4), génération de specs (v0.5) jusqu'à
   stabilisation v0.2.0.

## BL DONE — réaffectation version

| BL | Ancienne version | Nouvelle version |
|----|------------------|------------------|
| BL-001..005, 009..011, 014, 015 | 0.1.0 | 0.1.0 (015 recentré dry-run) |
| BL-006..008, 012, 013 | 0.1.0 | **0.1.1** |
| BL-016..019 | 0.2.0 | 0.2.0 (inchangé) |
