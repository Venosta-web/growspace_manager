# Degraded Control requires an explicit fallback

When required VWC evidence becomes stale or contradictory, an Irrigation Zone enters Degraded Control instead of silently choosing a probe or presenting normal steering. It stops self-tuning and follows a bounded Fallback Recipe that was selected in advance; Guided operation defaults to a conservative commissioned schedule, while Facility operation must explicitly choose and test either a fallback recipe or hold-for-intervention behavior. This preserves hobby continuity without letting facility automation fabricate confidence.
