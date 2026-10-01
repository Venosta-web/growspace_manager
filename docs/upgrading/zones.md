# Upgrading to irrigation zones

The version 2 store migrates each growspace into an implicit default zone,
behind an untouched `growspace_manager.v1` copy. Older builds refuse the new
store rather than dropping its zones.

Recipe stamps now record the recipe’s revision and a copy of its portable,
zone-owned values. Editing the library reports **Recipe Updated** separately
from drift; only changes to the zone’s stamped values count as hand tweaks.
An untweaked zone with Program Auto-advance follows a newer revision on its
next refresh. Without auto-advance, the revision is available for manual apply.
Deleting a recipe leaves its applied copy available for drift comparison.

A schedule-recipe stamp no longer writes drains, drain duration, daily volume
caps, cycle limits or the dark-period gate, even in a single-zone growspace.
Set these directly on the growspace. Crop-steering stamps likewise leave the
lights-on time and automatic light tracking alone. Recipes keep these shared
settings as provenance and warn on a mismatch, without changing them.

Migration gives existing recipes revision 1 and copies the current recipe’s
zone-owned values into existing stamps. A recipe edited before migration may
therefore already read as drifted. A stamp naming a deleted recipe has no copy.
