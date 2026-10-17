# E-cycle frozen before results

## E1 trigger
Unchanged. E1-donchian-20. Prior 20 completed bars. No parameter change.

## E1 executable completion
Entry: next bar open after the trigger close.
Exit: first later close beyond the opposite 20-bar band, or 20 bars, whichever comes first.
Size: 1 unit return. No leverage.
Repeat while open: ignore.
Costs: base 10 bps fee + 1 bps half-spread per fill. Stress 10 + 5.
Shorts included. Funding is not modeled. That is a limitation, not zero proof.
Ambiguous same-bar exit: exit at the close that crosses the opposite band.

## E2-sma20
Independent. Not a Donchian variant.
Long only when close crosses above the 20-bar SMA from below.
Exit when close crosses below that SMA, or after 40 bars.
Entry: next open.
Same costs. No shorts, so no funding assumption.
