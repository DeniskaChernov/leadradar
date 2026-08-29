# Lead Intelligence Challenge V1

## Purpose

This is a fixed, reviewable offline challenge set for the local lead classifier. It contains 36
distinct RU, Uzbek Latin and Uzbek Cyrillic phrases (12 per language) with explicit lead, intent
and buyer-role labels. It does not call OpenAI, Instagram or the database.

The set is synthetic and was used to diagnose and fix deterministic rule failures in this stage.
It is therefore a calibration/challenge corpus, not an unseen production sample and not evidence
of production accuracy.

## First frozen baseline

- lead precision: 83.9%;
- lead recall: 100%;
- intent accuracy: 80.6%;
- buyer-role accuracy: 80.6%;
- HOT false-positive rate among negative cases: 50%;
- mismatches: 8.

The failures exposed negated purchase phrases, job questions, Uzbek Cyrillic morphology, Latin
`ta` quantity parsing, `restoranga` B2B context and the false `rang` match inside `restoranga`.

## Result after evidence-backed fixes

- lead precision: 100%;
- lead recall: 100%;
- intent accuracy: 97.2%;
- buyer-role accuracy: 100%;
- HOT false-positive rate: 0%;
- B2B precision: 100%;
- remaining mismatches: 1.

The remaining mismatch is deliberately visible on `/system`; the gate does not require a
misleading 100% score. The phrase `Где это можно купить?` is still classified as BUY rather than
LOCATION because the explicit purchase verb wins. Both labels are commercially actionable, but
the disagreement remains visible instead of being silently relabelled.

## Safety boundary

The report is calculated in memory from the fixture. It performs zero network requests, persists
nothing and never changes production scores. Re-scoring saved leads and any paid live validation
remain separate, explicitly controlled operations.
