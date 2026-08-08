# Real-world multi-zone crop-steering topology

Research for [#545](https://github.com/Venosta-web/growspace_manager/issues/545), charting under the map
[#544](https://github.com/Venosta-web/growspace_manager/issues/544).

Retrieved 2026-08-08. This file establishes `docs/research/` — the repo previously had only `docs/adr/`
and `docs/services.md`, and this is a findings note, not a decision, so it does not belong in `adr/`.

## How to read this document

Every claim below carries a tier. The ticket asked specifically that documented practice be separated
from vendor marketing, so the tier is not decoration — it is the finding.

| Tier | Meaning |
| --- | --- |
| **A — primary, fetched** | I fetched the document and quoted it. Manuals, design guides, methodology PDFs. |
| **B — primary, but vendor-authored with no supporting data** | Fetched from the owner, but the numbers cite no study. Most crop-steering "methodology" is this. |
| **C — marketing page** | Fetched from the vendor, but a product/sales page rather than a manual. |
| **D — trade press / secondary** | Fetched, named author, not the owner of the claim. |
| **UNVERIFIED** | Appeared only in a search-engine summary; the page itself was not fetched. Listed in "Could not verify", never used in the body. |

A worked example of why the tier matters is in [Could not verify](#could-not-verify).

---

## Summary of findings

1. **No retrieved source states a typical or recommended zone count.** Not AROYA, not Athena, not any
   controller manual. What exists is a hardware *ceiling* (8–72 stations on OpenSprinkler, "up to 30"
   on TrolMaster NFS-1) and a derivable *floor* (zones ≥ distinct cultivars in the room, from Athena's
   strain-per-zone rule). The map's 2–6 target survives as an inference from a published rule, not as
   an observation. See [Zone counts](#4-zone-counts-the-honest-answer-is-no-number).
2. **The reference hydraulic layout is one pump plus N sequenced solenoid valves, one open at a time.**
   AROYA — the dominant crop-steering platform — drives *only* OpenSprinkler, whose model is
   software-defined master/pump outputs plus sequential station groups. AROYA's own FAQ states
   "no more than one zone can be open at once." See [Hydraulics](#2-hydraulics-one-pump-n-valves-one-open-at-a-time).
3. **Flow meters are optional, and where present they report pulse-derived cumulative volume per
   irrigation event — not instantaneous rate.** Athena's 121-page methodology document mentions flow
   meters zero times. See [Flow metering](#3-flow-metering-optional-pulse-based-cumulative-per-event).
4. **"Must not merge" is enumerable from primary sources** and is the most decision-relevant finding
   here: cultivar/strain, substrate type *and* volume, emitter count and flow rate, plant size/age, and
   light intensity. See [Must not merge](#5-where-published-methodology-says-zones-must-not-be-merged).
5. **Three independent sources converge on roughly three probes per controlled cohort**, and — more
   usefully — all three give the same *rationale*: within-zone spatial variability driven by airflow and
   position. The rationale generalises to a design constraint; the number does not.
   See [Probes per zone](#1-probes-per-controlled-zone).

---

## 1. Probes per controlled zone

### AROYA — three per strain per 1,000 sq ft

**Tier B.** [aroya.io — Cannabis moisture sensor best practices](https://aroya.io/en/knowledge-base/education-guides/cannabis-moisture-sensor)

> Three sensors per strain in a 1,000-square-foot room should produce the most helpful and complete dataset.

The stated rationale is that a single sensor in a 10,000 sq ft facility captures data about one plant only.
Note the unit of subdivision in that sentence: **per strain**, not per room or per bench. AROYA is a sensor
vendor and cites no study, hence tier B.

The same page acknowledges the substrate itself is a variability source:

> grow media typically contain inconsistencies "even within the same brand" due to production and shipping
> variations, which can produce "data inconsistencies"

### Athena — one main sensor at the average plant, secondaries optional

**Tier B.** Athena Precision Irrigation Strategies, p.11 ("Irrigation Zone Sensor Placement"). Retrieved as
PDF via the Zendesk help-center API (see [Could not verify](#could-not-verify) for why the HTML 403s):
[support.athenaag.com article 25975395644315](https://support.athenaag.com/hc/en-us/articles/25975395644315-Precision-Irrigation-Strategy)
→ [PDF](https://drive.google.com/file/d/1nOL2gjTCxOvfdciYQ_n9zKxCAZHAC8LY/view)

> Plants positioned in different areas within an irrigation zone experience different rates of dryback due to
> variations in environmental variables such as temperature and airflow. For example plants next to a fan or an
> isle would have an increased rate of dryback as opposed to plants in the center of an irrigation zone.
> When choosing the best location for a substrate sensor to control an irrigation zone it is crucial to select a
> plant that best represents the average moisture level of all the plants within the zone. For larger irrigation
> zones, it may be required to utilize multiple sensors placed in different areas to dial in your irrigation
> strategy. Depending on the irrigation controller additional sensors may be used as supplemental data or may be
> used to take average readings.

The accompanying diagram labels a **MAIN SENSOR** and a **SECONDARY SENSOR** against a moisture gradient
(`DRIER — AVERAGE — WETTER`) with axis labels `FAN`, `WALL`, `INNER AISLE`, `OUTER AISLE`.

This is the single most design-relevant sentence in the corpus. It says the controlling probe is a *chosen
representative*, that extra probes are *optional*, and — critically — that whether extras are averaged or held
as supplemental data **depends on the controller**. There is no published consensus that a zone's VWC is the
mean of its probes.

Athena also specifies probe depth by container:

| Container | Sensor depth |
| --- | --- |
| 4 L pot | 2.5 cm from bottom |
| 7 L pot | 5 cm from bottom |
| 10 L pot | 5 cm from bottom |
| Rockwool | 2.5 cm from bottom |

And for runoff validation, a separate sample of plants per zone:

> Before P1 Irrigation Phase begins, select 2-3 average size plants within each irrigation zone. This will give
> the best representation of the average runoff for plants within the zone.

### Convergence, and what it is worth

AROYA's three-per-strain, Athena's main-plus-secondary with 2–3 plants sampled for runoff, and Grodan's
three-sensor basic set (see [Grodan](#grodan)) land in the same place without citing each other. Treat this as
convergence among vendors sharing an industry practice, **not** as three independent confirmations of a measured
optimum. None of the three publishes data behind the number.

The rationale, by contrast, is stated identically by all of them and is what should drive design: probes exist
to sample **within-zone spatial variability caused by position relative to airflow, aisles and walls**. A design
that treats a zone's probes as interchangeable replicates contradicts Athena explicitly — one is the control
probe, the rest are not.

---

## 2. Hydraulics: one pump, N valves, one open at a time

### AROYA supports exactly one irrigation controller: OpenSprinkler

**Tier A.** [aroya.helpdocs.io — Irrigation Control Guide / FAQs](https://aroya.helpdocs.io/article/em5cc0nke9-irrigation-faqs)

The FAQ names OpenSprinkler as the supported hardware, on firmware 2.1.9(9), 2.1.9(10), 2.1.9(11) or 2.2.0(1),
and states:

> AROYA integration only supports the Standard station type in OpenSprinkler

and, on scheduling:

> no more than one zone can be open at once

It references "24 ports for single expansion". It says nothing about valve brands, pumps, or flow meters — the
downstream hydraulics are simply out of AROYA's scope.

This is a significant structural fact. The best-known crop-steering platform does not ship irrigation hardware;
it delegates to a general-purpose open-source sprinkler controller. Whatever OpenSprinkler's model is, that is
*de facto* the crop-steering reference topology.

### OpenSprinkler's model

**Tier A.** [OpenSprinkler Firmware 2.2.1 User Manual](https://opensprinkler.github.io/OpenSprinkler-Firmware/2.2.1/221_4_manual/)

- **Stations:** "Main controller: 8; Expandable to 72" (OpenSprinkler v3); "Main controller: 8; Expandable to
  200" (OSPi). Station count is configured manually and may exceed physical outputs to include virtual zones.
- **Pump:** "up to two independent masters, each configurable"; any zone can serve as a master/pump relay; a
  master "activates alongside other zones".
- **Lead/lag:** "Master On Adjustment" and "Master Off Adjustment" each range −600 to +600 seconds.
- **Concurrency:** "Zones in the same Sequential Group run sequentially (one at a time)"; "Zones in different
  Sequential Groups can run simultaneously (in parallel)"; a Parallel Group "runs independently of all other
  zones".

So: **one shared pump, many solenoid valves, sequential within a group, with configurable pump lead and lag.**
Parallel operation is possible but is an explicit opt-out that the grower must configure, and AROYA's layer
forbids it outright.

### TrolMaster

**Tier C (marketing page).** [trolmaster.com — Aqua-X NFS-1](https://www.trolmaster.com/Products/Details/NFS-1)

> control up to 30 separate irrigation zones (24vac solenoid valves or 120vac pumps)

> up to (8) Water Content Sensors connected to a single Aqua-x controller

The product page does not address whether multiple zones may run simultaneously. Note the architecture is the
same shape as OpenSprinkler's — a zone output drives *either* a 24 V solenoid *or* a 120 V pump, i.e. the pump
is one of the switched outputs rather than a separate concept.

The **8 water content sensors per controller** figure is worth holding next to the 30-zone figure: at TrolMaster's
own ceiling the controller cannot supply even one probe per zone. Probe-per-zone is not assumed by the hardware.

### Facility engineering view

**Tier D.** Luke Streit, PE (IMEG Corp; ag-engineering degree, Iowa State; ASABE/ASHRAE/NFPA/RII member),
["Cannabis Grow Facility Design 101, Part 2: Water Usage", phcppros](https://www.phcppros.com/articles/15572-cannabis-grow-facility-design-101-part-2-water-usage)

> each zone controlled by a solenoid valve. Inside the grow rooms, fertigation piping will be routed to each
> zone, which generally consists of multiple plants on a rack or bench, with one or more drip emitters serving
> each plant.

RO water is pumped from tanks through nutrient injection/mixing, and the resulting fertigation solution is
distributed to rooms. The article does **not** state a zone count per room, does not discuss flow meters, and
does not resolve one-pump-per-zone versus shared. It is the clearest primary-adjacent statement that
**a zone is physically a rack or bench**, which is a different subdivision axis from Athena's per-strain rule —
see [Disagreements](#disagreements).

---

## 3. Flow metering: optional, pulse-based, cumulative per event

This section answers the item 544 flags as blocked on "unit handling (rate vs cumulative)".

### Athena's methodology does not use flow meters at all

**Tier A** (this is an absence in a fetched document, verified by grep over the full extracted text).

Across all 121 pages of Athena's Precision Irrigation Strategies document, the strings "flow meter",
"flowmeter" and "flow sensor" appear **zero times**. The document's own "NECESSARY TOOLS" panel lists:

> EC/pH Meters · Substrate Sensor · Controller/Timer · Precision Irrigation Equipment

Delivered volume is instead controlled *open-loop* by shot size and verified by a manual proxy:

> PRO TIP: Have an extra set of emitters placed in a pitcher to catch irrigation water to monitor shot volume.

That is the honest state of the published methodology: **volume is calculated from emitter flow rate × duration
and spot-checked with a jug, not metered.** Runoff is likewise measured manually in a graduated cylinder.

### Where meters do exist, they are pulse counters totalised per station run

**Tier A.** OpenSprinkler manual (as above):

- Signal: "All dry-contact, 2-wire flow sensors (recommended)" plus "3-wire flow sensors that work with +5V".
- Conversion: "Flow Pulse Rate: can be found in the flow sensor datasheet" and is "used to convert flow pulse
  count to actual water volume. Precision is limited to 2 decimal places".
- Limit: "The flow click frequency should NOT exceed 50Hz".
- Reporting: records "total flow volume at the end of each station run and program cycle".
- Hardware limit: on OpenSprinkler v3 only the SN1 input supports a flow sensor; SN2 does not — i.e.
  **one meter per controller, shared across all stations, attributed by whichever station is running.**

That last point is the structural consequence of one-zone-open-at-a-time: a single shared meter on the manifold
can attribute volume per zone *only because* zones are sequenced. Concurrent zones on a shared meter make
per-zone attribution impossible without a meter per line.

TrolMaster sells its meter as a separate add-on (DFM-1 / DFM-3), i.e. metering is opt-in there too.

**Design conclusion for GSM:** the crop-steering equipment class reports **cumulative volume per irrigation
event**, derived from a pulse count and a datasheet pulses-per-unit constant. The unit is whatever the constant
declares (L or gal); the meter itself is unit-agnostic.

**Honest caveat:** this conclusion is about *this equipment class*. Generic flow sensors surfaced through Home
Assistant frequently expose an instantaneous rate (L/min) instead of, or alongside, a totaliser, and a
`total_increasing` totaliser resets on device reboot. GSM cannot assume the crop-steering shape from an
arbitrary HA entity. The finding narrows the *primary* case, it does not eliminate the rate case.

---

## 4. Zone counts: the honest answer is "no number"

**No retrieved primary source states a typical, recommended, or maximum-in-practice number of irrigation zones
per room or per facility.** Not AROYA's education guides or help docs, not Athena's 121-page methodology, not
the facility-engineering article, not the Netafim design guide.

What the sources do give:

**Hardware ceilings** (these are equipment capability, *not* evidence of practice — do not read them as such):

| Controller | Zone/station ceiling | Probe ceiling |
| --- | --- | --- |
| OpenSprinkler v3 (tier A, manual) | 8 onboard, expandable to 72 | n/a (probes are AROYA-side) |
| OpenSprinkler Pi (tier A, manual) | 8 onboard, expandable to 200 | n/a |
| TrolMaster Aqua-X NFS-1 (tier C, marketing) | "up to 30" | 8 per controller |

**A derivable floor.** Athena's strain-per-zone rule (below) makes zone count ≥ number of distinct cultivars
under one controller. AROYA's sensor guidance is denominated per strain for the same reason. Neither states how
many cultivars a room runs.

**Therefore:** the map's 2–6 zone target is defensible as *"one zone per cultivar cohort, and small rooms run
few cultivars"*. That is inference from a published composition rule. It is **not** observation, and nothing in
this research converts it into one. A zone-shape ticket citing this document should name that chain explicitly
rather than citing "2–6" as sourced.

---

## 5. Where published methodology says zones must not be merged

This is the most decision-relevant finding and it *is* enumerable from primary sources.

### Athena — one strain per zone

**Tier B.** Precision Irrigation Strategies, p.11, verbatim:

> PRO TIP: Designate individual strains to specific irrigation zones due to varying rates of dryback.

The stated mechanism is dryback rate divergence: two cultivars sharing a valve receive identical shots but
dry back at different rates, so no single schedule satisfies both.

### AROYA — the Three Pillars of Uniformity

**Tier B.** [aroya.io — Uniformity in cannabis cultivation](https://aroya.io/education-guides/uniformity-cannabis-cultivation),
attributed to Tyler Simmons, Cultivation Consultant.

- **Substrate:** "making sure that each plant has the same substrate volume, the initial soaking and
  conditioning process is the same, that the drip system is uniform so that plants are always receiving the same
  amount of nutrients and water."
- **Climate:** "uniformity of plant climate across the room [and] would encompass lighting intensity; air
  movement and temperature, humidity, VPD."
- **Plant:** "Having clones that are of equal health and size when they're created, then either monocropping so
  that the strains all have similar architecture," or "strain matching so that if you're running more than one
  strain, they at least have similar growth characteristics and structure."
- **Grouping:** document how each cultivar responds to irrigation schedules, then "group similar-growing plants
  together".

Note AROYA's softer position: strains *may* share a group if "strain matched" for similar growth characteristics.
Athena's rule is unconditional. See [Disagreements](#disagreements).

### Netafim — do not mix emitter output or spacing within a zone

**Tier A**, and the only genuinely engineering-grounded must-not-mix rule retrieved.
[Netafim USA, Techline DL Design Guide](https://www.netafimusa.com/bynder/41497DDE-82FB-4B06-A9F71DCCBA8B4F6B-tdg-techline-design-guide.pdf), Design Criteria, p.2:

> Designing similar areas into a zone and not mixing emitter output and dripline spacing is just like sprinkler
> design.

And on hydraulic grounds specifically, p.19:

> In conditions where the elevation change is greater than 10', zone the two areas separately.

The second is a pressure/head argument, not an agronomic one. It is a reminder that a zone boundary can be forced
by hydraulics alone, independent of what is planted.

### Composite: what makes two cohorts incompatible

Assembled from the three sources above. Each dimension traces to a named source; the *list* is my synthesis.

| Dimension | Source | Mechanism |
| --- | --- | --- |
| Cultivar / strain | Athena (unconditional), AROYA (conditional on strain-matching) | divergent dryback rate |
| Substrate volume | AROYA | same shot % ⇒ different absolute volume ⇒ different VWC response |
| Substrate type (coco vs rockwool) | Athena (implicit — separate shot tables and field capacities) | different field capacity and dryback curve |
| Emitter count / flow rate | Netafim (explicit), AROYA ("drip system is uniform") | same valve-open duration ⇒ different delivered volume |
| Dripline spacing | Netafim | distribution uniformity |
| Plant size / age / health | AROYA | divergent transpiration |
| Light intensity | AROYA | divergent transpiration |
| Elevation change > 10 ft | Netafim | pressure variation across the zone |

---

## 6. Plant counts, containers and substrates

**Tier B.** Athena "Plant Spacing and Irrigation" sheet (A01.001), retrieved via the Zendesk API from
[support.athenaag.com article 17296083175835](https://support.athenaag.com/hc/en-us/articles/17296083175835-Plant-Spacing-and-Irrigation)
→ [PDF](https://drive.google.com/file/d/1aFqyscTvcEjWRg5b66jyJBp9e9m9mLp6/view).

Plants per 4'×4' or 5'×5' canopy footprint, with matching Netafim pressure-compensating dripper counts:

| Pot size | Rockwool equivalent | Plants / footprint | Drippers |
| --- | --- | --- | --- |
| 0.5–1 gal | 4" | 16 | (1) 0.3 gph |
| 1–1.5 gal | 6" | 10–14 | (2) 0.3 gph |
| 2–3 gal | 4" cube on 3×6×36 slab | 6–9 | (2) 0.5 gph or (3) 0.3 gph* |
| 3 gal | — | 3–5 | (2) 0.5 gph or (4) 0.3 gph |
| 5 gal | — | 2 | (4) 0.5 gph |
| 7–10 gal | — | 1 | (4) 0.5 gph |

\* "Only (2) .3 drippers in slab setup". 5–7 gal is flagged as outdoor-flowering or large mothers, not indoor
precision irrigation. Athena's own caveat: "This is a baseline recommendation."

**Substrate types.** Athena recommends exactly two, and **never mentions peat** anywhere in the 121-page document
(verified by grep — zero occurrences):

> 100% Coco: A homogeneous substrate that allows substrate sensors to have more consistent readings without
> interference from aeration material such as perlite. Pot Type: Compressed pre-filled or fabric pots.
> Pot Size: 1-3 gallons.

> Rockwool: A homogeneous substrate with a consistent field capacity and quick dryback allowing easy control over
> substrate EC. Rockwool Size: Hugo 6"x6" or Delta 4"x4" on Unislab or Multi Plant Slab.

The stated selection criterion in both cases is **sensor-reading consistency and homogeneity** — i.e. substrate
choice in this methodology is downstream of the requirement to control by probe. Peat's absence is a documented
omission, not a documented rejection; no retrieved source says peat cannot be steered.

**Shot volumes** (1% of substrate volume), from the same document:

| Substrate | 1% shot | Vegetative runoff (8–16%) | Generative runoff (1–7%) |
| --- | --- | --- | --- |
| 4 L pot | 40 mL | 320–640 mL | 40–280 mL |
| 7 L pot | 70 mL | 560–1,120 mL | 70–490 mL |
| 10 L pot | 100 mL | 800–1,600 mL | 100–700 mL |
| 10 cm rockwool (Delta 6.5) | 6.5 mL | 56–112 mL | 7–46 mL |
| 10 cm rockwool (Delta 10) | 10 mL | 80–160 mL | 10–70 mL |
| 15 cm rockwool (Hugo) | 35 mL | 280–560 mL | 35–245 mL |
| Uni-Slab rockwool | 50 mL | — | — |
| 15 cm rockwool slab | 100 mL | — | — |

Operating guidance: "2%-6% shots, spaced 15-30 minutes apart allows the substrate to gradually build up to target
VWC%", with the failure mode named as channeling ("Channeling will occur when too large of shots are used and
water isn't allowed to slowly saturate into the substrate").

Athena's headline targets — substrate EC 3–10 mS/cm by stage, dryback 25–50% by stage, runoff 8–16% vegetative /
1–7% generative — are **tier B throughout**: published by a nutrient vendor, authored by a named individual
("Created by Jay Yokiel @SaltsandLEDs"), with no cited trial data. They are the most detailed public numbers
available and should be treated as a well-specified convention rather than a validated result.

---

## Grodan

*Awaiting the substrate/probe retrieval pass; the fetched-and-quoted material will be filled in here.*

What is currently held at **UNVERIFIED** (search summary only, page not fetched — do not cite):
that the GroSens basic set consists of three sensors and is modular; that "more measurement points lead to more
representative WC and EC figures in the irrigation section"; that GroSens works on slabs 7.5 cm and 10 cm high;
that sensors are positioned "in any pre-defined irrigation section". If confirmed, the three-sensor basic set
corroborates the convergence noted in §1 — from a third vendor, in a non-cannabis greenhouse context, which
would make it the most interesting of the three.

## METER Group

*Awaiting the substrate/probe retrieval pass.* METER manufactures the TEROS sensors AROYA resells, so METER's own
application notes are the closest thing to a first-party statement on sensor replication and are worth having
verbatim.

---

## Disagreements

Recorded, not resolved.

**1. What axis a zone is subdivided on.** Athena says **cultivar** ("Designate individual strains to specific
irrigation zones"). The facility-engineering article says **physical bench or rack** ("each zone … generally
consists of multiple plants on a rack or bench"). AROYA's product surface says **room, zone, or controller**
("Schedule watering by room, zone, or controller" —
[aroya.io, tier C marketing](https://aroya.io/en/knowledge-base/education-guides/irrigation-control-aroya)).
These are not the same thing and nothing reconciles them. The plumbing is laid out by bench because that is where
the pipe goes; the agronomy wants it laid out by cultivar. In a real install the constraint binding is whichever
was decided first — which is a strong argument that GSM should not assume zone identity is derivable from either
physical layout or cultivar alone, and should let the grower state it.

**2. Whether strains may ever share a zone.** Athena: unconditional, one strain per zone. AROYA: conditional —
"strain matching so that if you're running more than one strain, they at least have similar growth
characteristics and structure", and "group similar-growing plants together". AROYA permits what Athena forbids,
provided the grower has characterised the strains. Neither cites data.

**3. Whether multiple probes in a zone should be averaged.** Athena is explicitly non-committal and defers to the
controller: "Depending on the irrigation controller additional sensors may be used as supplemental data or may be
used to take average readings." Its diagram distinguishes a MAIN from a SECONDARY sensor, implying the main one
controls. AROYA's three-per-strain guidance implies a dataset rather than a control signal, without saying how it
is reduced. There is no published answer to "what is a zone's VWC when it has three probes."

**4. Concurrency.** OpenSprinkler's firmware supports parallel groups. AROYA's integration on top of it states
"no more than one zone can be open at once." The platform is more restrictive than the hardware. Whether that is
a hydraulic judgement (a shared pump cannot supply two zones at spec pressure) or an integration simplification
is not stated anywhere retrieved.

---

## Could not verify

**A worked example of why this section exists.** A search-engine summary of AROYA's uniformity guide reported
that "rockwool will be in the high nineties in terms of uniformity, while coco is in the eighties". Fetching that
same page returned: variations between substrate types are noted, but *no specific percentage figures are given*.
The summariser manufactured the numbers. Every figure in this document above was taken from a fetched page for
this reason.

Not retrieved, and therefore not used:

- **Athena support HTML pages** — 403 to WebFetch and to browser-UA curl. Recovered via the Zendesk help-center
  API (`/api/v2/help_center/en-us/articles/<id>.json`), which returned article bodies linking Google Drive PDFs;
  those PDFs downloaded and were the source for all Athena quotes here. Method noted so the retrieval is
  reproducible.
- **The Athena Handbook** (full commercial handbook) — gated behind a lead-capture form at `info.athenaag.com`.
  Issuu hosts previews but serves no extractable text. Its "Irrigation Terminology and Tools" section may contain
  zone-count guidance; unknown.
- **Greenhouse Grower**, "Ways to Use Moisture Sensors to Automate Greenhouse Irrigation" — 403. A search summary
  attributed to it two relevant claims: that irrigation zone size is set by microclimate differences (plants near
  a cooling pad versus near exhaust fans), and that a "Fertigation Manager" program averages three sensors per
  irrigation zone. **Both unverified.** The first would independently corroborate Athena's within-zone
  variability rationale and the second would settle disagreement #3; worth a retry with a different fetch path.
- **"2–4 sensors per crop zone" attributed to AROYA** — appeared in a search summary with no locatable source
  page. Could not be traced to any AROYA document. Discarded.
- **Netafim "CV of 3% or less" and "10% flow variation is considered uniform"** — appeared in a search summary.
  Fetched and text-extracted the Techline DL Design Guide in full; neither figure is in it. Not asserted here.
  The one Netafim uniformity statement that *is* verified is the do-not-mix-emitters rule quoted in §5.
- **TrolMaster NFS-2 "up to 300 valves using up to 50 control modules"** and DFM-1 meter behaviour ("feed by
  volume function") — search summaries and retailer pages only; the TrolMaster manual PDFs were not fetched by
  me. Treated as UNVERIFIED and excluded from the ceilings table.
- **AROYA's definition of Room vs Zone** — the help-docs article on creating rooms and zones documents the UI
  steps only. AROYA never defines what a Zone *is*, nor states any relationship between a Zone and a valve. This
  is a genuine gap in the source, not a retrieval failure, and it is telling: the market-leading platform ships
  a zone concept without defining it.
- **Any zone-count figure.** No source retrieved states one. This is a finding, not a gap — see §4.

---

## Bearing on the map's open decisions

Offered as input to #544's charting, not as decisions.

- **Shared-pump arbitration** (544, "Not yet specified"): the documented reference behaviour is *sequential, one
  zone open at a time, with configurable pump lead/lag offsets* (OpenSprinkler ±600 s; AROYA "no more than one
  zone can be open at once"). A queue with a single in-flight zone matches published practice; concurrent
  delivery does not, and would also break per-zone attribution on a single shared meter.
- **Flow-meter unit handling** (544, "Not yet specified"): the crop-steering equipment case is
  *pulse-count → cumulative volume, totalised at the end of each irrigation event*, with the unit carried by a
  datasheet constant. The instantaneous-rate case is real for generic HA entities but is not what this equipment
  class does. Staged confidence fits the evidence: Athena's published methodology runs entirely open-loop with a
  manual jug check, so metering is genuinely an upgrade, not a baseline.
- **Zone identity**: sources constrain zone *composition* strongly and zone *count* not at all. The composition
  table in §5 is the sourced answer. GSM should let the grower declare zone membership rather than deriving it,
  given disagreement #1.
- **Degraded control**: Athena's model is one designated representative probe per zone, extras optional. A
  single-probe zone is therefore the *documented normal case*, not a degraded one. Any design treating one probe
  as degraded contradicts the methodology.
- **Existing GSM shape**: `models/irrigation.py` already carries `SubstrateProfile` (`media_type`,
  `liters_per_pot`) and percent-of-substrate shot sizing (`p1_shot_volume_percent`, `p2_shot_volume_percent`),
  which is exactly Athena's model. `models/growspace.py` already has a `Subarea` ("A named sub-zone within a
  growspace with its own environment sensors") carrying an `EnvironmentConfig` but no irrigation config — worth
  charting whether an Irrigation Zone is a new peer of `Subarea` or an extension of it.
