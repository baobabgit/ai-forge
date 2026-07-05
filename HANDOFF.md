# HANDOFF — session 2026-07-05

## Priorité immédiate : mise à plat documentaire (CDC v1.4)

Réalignement effectué :

- **CDC unique** : `docs/specs/cahier-des-charges-ai-forge-v1.4.md` (renommé depuis `.md.md`)
- **Planning** : `planning.json` + `planning.md` alignés sur CDC v1.4 §6
- **49 BL** : `target_version` réaffectés (v0.1.0 dry-run → v0.1.1 adaptateurs → v0.3 parallèle → v0.4 multi-repo → v0.5 specs auto)
- **Jalon v0.1.0** recentré : dry-run/mock, **pas** merge E2E par IA
- **Sujets repoussés** documentés : parallélisme, self-hosting, L2, rollback, multi-repo auto
- **Écart implémentation** : `docs/specs/MIGRATION-IMPL.md`

## État code (inchangé)

| Version spec | BL DONE | Contenu |
|--------------|---------|---------|
| v0.1.0 | 001–005, 009–011, 014, 015 | Socle + dry-run (015 spec recentrée) |
| v0.1.1 | 006–008, 012, 013 | Adaptateurs réels + DEV + git/gh |
| v0.2.0 | 016–019 | Gates, verdicts, TESTER, REVIEWER (PR #32) |

## Prochaines actions

1. Merger PR #32 (code v0.2) si pas encore fait.
2. Taguer **v0.1.0** : `forge run --dry-run --bl BL-demo-001` avec provider mock.
3. Poursuivre v0.2.0 (BL-020+) sans ouvrir parallélisme/multi-repo.

## Gap v0.1.0 comblé

- `src/providers/mock.py` — provider déterministe sans CLI externe
- `forge run` utilise **mock** par défaut ; adaptateurs réels via `--provider claude|codex|cursor`

## Métriques

- **197 tests**, couverture **≥ 95 %** sur `src/`.
