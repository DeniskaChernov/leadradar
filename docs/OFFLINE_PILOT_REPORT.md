# Lead Radar Offline Pilot Report

## Scope

Phase F runs entirely offline. It does not initialize an Instagram live provider,
Telegram delivery, or OpenAI client. The runner expands 60 manually curated root
examples into 600 deterministic robustness cases:

- 300 lead-intent cases from 30 multilingual golden roots;
- 300 artificial-rattan cases from 30 RU/UZ/EN golden and negative roots;
- 10 case, whitespace, punctuation and emoji variants per root.

This is a robustness replay, not 600 independently collected real-world examples.
It proves deterministic behavior around the current golden boundaries but does not
yet prove production precision on unseen traffic.

## Verified result

- corpus size: 600;
- lead precision: 100%;
- lead recall: 100%;
- lead intent accuracy: 100%;
- rattan precision: 100%;
- rattan recall: 100%;
- rattan layer accuracy: 100%;
- deterministic digest: `fdc07b981a00d50b9a29df529b329dc8bf803ce9e98b778f990631e16fad6206`;
- first ingestion: 600 Comment, 600 PublicSignal and 600 Evidence records;
- identical second ingestion: 0 new records;
- duplicate records after replay: 0.
- complete repository suite after Master Phase D hardening: 194 tests passed; Ruff and
  compileall clean.

The first pilot run exposed four false negatives for punctuation/emoji variants of
the explicit commercial CTA response `+`. The local rule was narrowed and repaired:
`+?`, `+!`, `+ 🙏` and `+...` are commercial only when the post explicitly asks the
user to leave a plus for a price, catalog or contact. A plus without that CTA remains
non-commercial.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -m scripts.run_offline_pilot
```

The process uses a temporary SQLite database and removes it after the run. A non-zero
exit code means at least one quality or idempotency threshold failed.

## Remaining pilot gates

1. Expand to 150–300 independently curated multilingual lead cases.
2. Add at least 100 independently labeled audience-membership cases.
3. Replay 500–1000 archived public signals that were not used to tune the rules.
4. Review every false positive and false negative before enabling live discovery.
5. Validate Telegram delivery separately with a controlled manager chat.
