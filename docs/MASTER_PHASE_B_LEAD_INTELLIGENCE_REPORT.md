# Master Phase B — Lead Intelligence V3 Report

## Decision

The existing evidence-first scorer was retained. Building a second scoring engine would have
created conflicting scores and more maintenance without helping the owner. Work focused on a
real evaluation gap and the concrete failures it exposed.

## Baseline found

The prior 540-case replay looked large but its lead portion was 30 semantic roots transformed by
case, whitespace, punctuation and emoji. Against the new 200-phrase semantic benchmark, the first
run produced:

- lead precision: 97.83%;
- lead recall: 88.82%;
- intent accuracy: 79.50%;
- buyer-role accuracy: 88.00%;
- HOT false-positive rate: 6.25%;
- B2B precision: 100%.

## Root causes and changes

Generic tokens such as `есть?`, `bormi` and `qancha` were selected before the actual object of a
question. As a result, “delivery bormi” could become availability and “o'lchami qancha” could
become price. Primary intent now follows semantic specificity: delivery, dimensions, color,
catalog and contact evidence outrank generic availability/price question words.

Job-seeking and unrelated media questions were separated instead of being handled by one broad
non-commercial block. Quantity detection now precedes generic “need/kerak” BUY markers while an
explicit order phrase remains BUY. HoReCa, designer, negation and reaction variants were expanded
for observed RU/UZ gaps.

## Verified internal result

On the fixed, reviewable 200-phrase benchmark:

- lead precision: 100%;
- lead recall: 100%;
- intent accuracy: 100%;
- buyer-role accuracy: 100%;
- HOT false-positive rate: 0%;
- B2B precision: 100%.

This is an internal calibration result, not a production-accuracy claim. The fixture influenced
the fixes, so an unseen offline sample remains required before controlled live preparation.

No external network request or paid AI token is used by this evaluation.
