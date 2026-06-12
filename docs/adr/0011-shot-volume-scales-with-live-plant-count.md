# Shot volume scales with live plant count (per-plant dosing)

In Volume Mode, total substrate volume — the basis for percent-of-volume shot sizing — is *liters per pot × the growspace's live plant count*, not a statically configured pot count or total. This makes shot sizing a **constant per-plant dose**: harvesting 6 of 12 plants halves the total shot volume automatically while each remaining plant keeps receiving the same dose.

This is deliberately surprising: total irrigation output changes without any config edit. Two mitigations are part of the decision: (1) any live-count change that alters computed shot volume writes a logbook entry ("shot volume 480→240 ml: plant count 12→6") so the change is auditable; (2) at zero plants the growspace has no irrigation demand — steering suspends shots (loop alive, phase reports idle) rather than firing 0 ml no-ops or falling back to seconds and watering an empty tent.

The rejected alternative — explicit pot count config — never drifts silently but goes stale in the opposite direction: nobody updates the count at harvest, so the remaining plants get underdosed exactly when generative steering matters most. The live count also assumes every tracked plant sits on the irrigation line; growspaces where that doesn't hold should use Seconds Mode.
