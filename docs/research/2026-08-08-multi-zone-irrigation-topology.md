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

1. **No source *recommends* a zone count**, and exactly one *observes* one. Hardware ceilings run from 4
   (Autogrow) to hundreds; the derivable floor is "zones ≥ distinct cultivars". The single observed
   install is a 2-acre container nursery with **54 valves grouped into 8 control zones** — which also
   shows that zone and valve are not 1:1. The map's 2–6 target survives as inference from a published
   composition rule, not as observation. See [Zone counts](#4-zone-counts-the-honest-answer-is-no-number).
2. **The reference hydraulic layout is one shared pump plus N solenoid valves, run sequentially.**
   Five vendors' manuals independently describe the same shape — OpenSprinkler (master/pump outputs +
   sequential station groups), Autogrow IntelliDose ("a single irrigation pump with each station being
   watered by opening a solenoid valve"), Galcon (12 valves + one master valve), TrolMaster NFS-2
   ("Master Pump Link"), and AROYA on top of OpenSprinkler ("no more than one zone can be open at once").
   Pump-per-zone is not the documented pattern anywhere.
   See [Hydraulics](#2-hydraulics-one-pump-n-valves-run-sequentially).
3. **Flow meters are optional, and vendors disagree on what a meter reports.** Athena's 121-page
   methodology document mentions flow meters zero times, and two of five controllers have no flow input
   at all. Among those that do: OpenSprinkler totalises pulses per station run, Galcon reports an
   instantaneous rate in m³/hr, TrolMaster's DFM-1 reports both. **GSM must handle both shapes; there is
   no single documented convention.** See [Flow metering](#3-flow-metering-optional-and-vendors-disagree-on-units).
4. **"Must not merge" is enumerable from primary sources** and is the most decision-relevant finding
   here: cultivar/strain, substrate type *and* volume, emitter count and flow rate, plant size/age, and
   light intensity. See [Must not merge](#5-where-published-methodology-says-zones-must-not-be-merged).
5. **Three independent sources converge on roughly three probes per controlled cohort**, and — more
   usefully — all give the same *rationale*: within-zone spatial variability driven by airflow and
   position, corroborated independently in peer-reviewed container research. The rationale generalises
   to a design constraint; the number does not. METER, who make the sensors AROYA resells, answer the
   count question with "**No single answer captures all scenarios**" and note that **irrigation
   scheduling specifically needs fewer sensors** than estimating a true mean.
   See [Probes per zone](#1-probes-per-controlled-zone).
6. **How to reduce several probes to one number is genuinely unsettled** — Grodan averages (in hardware),
   Athena elects the average-moisture plant, UF/IFAS elects the driest zone, AROYA is silent. This is a
   decision #544 has not yet listed and it needs an ADR.

---

## 1. Probes per controlled zone

### AROYA — three per strain per 1,000 sq ft

**Tier B.** [aroya.io — Cannabis moisture sensor best practices](https://aroya.io/en/knowledge-base/education-guides/cannabis-moisture-sensor)

> Three sensors per strain in a 1,000-square-foot room should produce the most helpful and complete dataset.

The surrounding rationale, recovered verbatim on a second pass:

> Incorporating one cannabis moisture sensor into a 10,000-square-foot facility will only yield data about a
> single plant. It takes multiple sensors to collect a cross-section of data about your plants overall.

Note the unit of subdivision: **per strain**, not per room or per bench. AROYA is a sensor vendor and cites no
study, hence tier B. The same page on substrate variability:

> Growers using the most precise cannabis moisture sensor on the market must still watch for inconsistencies
> within the substrate. After all, any affordably priced grow medium likely has variances, even within the same
> brand.

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

### METER Group — the manufacturer's answer is "it depends", and that is the finding

**Tier A (application note).** METER publishes a note asking exactly the ticket's question.
["Soil moisture sensors — how many do you need?" (PDF)](https://publications.metergroup.com/Sales%20and%20Support/METER%20Environment/Website%20Articles/how-many-soil-moisture-sensors-needed.pdf)

> How many sensors will produce the most complete soil moisture picture? **No single answer captures all
> scenarios.** Study objectives, accuracy requirements, scale, and site-specific characteristics all influence the
> number of sensors required. In addition, soil moisture is variable both spatially and temporally.

And, decisively for GSM's use case:

> If the objective is to determine the "true" mean soil water content for a study area, then the sampling scheme
> needs to account for the sources of variability described above. […] If instead, the study site is fairly
> homogenous **or the researcher is only interested in the temporal pattern of soil water content (e.g., for
> irrigation scheduling), then fewer soil moisture sensors may be required** due to temporal autocorrelation in
> the data (Brocca et al. 2010; Loescher et al., 2014).

This is the most important sentence in the probe-count question and it comes from the manufacturer of the sensors
AROYA resells, citing literature. **Irrigation scheduling is explicitly the low-sensor-count case.** Estimating a
zone's true mean VWC is a *harder* problem than deciding when to fire the next shot, and crop steering is the
latter. A design that demands many probes before it will steer is solving the wrong problem.

METER's companion article on interpreting the data
([measurement insights](https://metergroup.com/measurement-insights/how-to-analyze-soil-moisture-data/), tier A)
adds a warning that bears directly on any averaging logic:

> Soil water content has a high spatial variability. Multiple sensors installed throughout the same field should
> show variation. **If there is no variability whatsoever, that is a sign to be concerned.**

> each spot will have its own baseline, so it's important to compare soil water content measurements to previous
> measurements in the same spot and not expect identical readings from one location to the next, no matter how
> close they are.

The second quote is a direct argument for **trend-relative rather than absolute-threshold** logic per probe, and
against naively averaging probes with different baselines.

The [TEROS 11/12 manual](https://publications.metergroup.com/Manuals/20587_TEROS11-12_Manual_Web.pdf) (tier A)
contains **no** sensors-per-zone figure and no dripper-relative placement rule. It does carry **separate mineral-soil
and "SOILLESS MEDIA" calibrations** — which partially confirms the substrate-calibration concern noted under
[Could not verify](#could-not-verify): substrate type changes how a raw reading becomes VWC.

### Extension and peer-reviewed sources — the only non-vendor evidence in this corpus

Everything above is vendor-authored. These are not.

**A zone is defined by a solenoid valve, and one sensor may control several.**
Tier A, UF/IFAS EDIS AE437,
["Smart Irrigation Controllers: How Do Soil Moisture Sensor (SMS) Systems Work?"](https://edis.ifas.ufl.edu/publication/AE437)
(turf/landscape context, not containers):

> A single sensor can be used to control the irrigation for many zones (**where an irrigation zone is defined by a
> solenoid valve**) or multiple sensors can be used to irrigate individual zones. In the case of one sensor for
> several zones, **the zone that is normally the driest, or most in need of irrigation, is selected for placement
> of the sensor** to ensure adequate irrigation in all zones.

> Soil in the area of burial should be representative of the entire irrigated area.

> Sensors should also be located at least 5 feet from irrigation heads and toward the center of an irrigation zone.

Two things here are new. First, an **independent, non-commercial definition of "irrigation zone" as the solenoid
valve** — which is the cleanest definition retrieved from any source, vendor or otherwise. Second, a documented
topology GSM has not been considering: **one probe governing several valves**, with the probe sited in the
*driest* zone so no zone is under-watered. That is a conservative fallback pattern with a published rationale,
and it is directly relevant to 544's open "fallback behavior when control is degraded" item.

Note it inverts Athena's placement rule: Athena sites the probe at the *average* plant to steer one zone; UF/IFAS
sites it at the *driest* zone to safely cover many. Different objectives, different placement — recorded under
[Disagreements](#disagreements).

**Container-crop research reports sensor counts only as study design, never as recommendation.**
Chappell et al., "Implementation of Sensor-based Automated Irrigation in Commercial Floriculture", *HortTechnology*
([PDF](https://www.publicgardens.org/wp-content/uploads/2019/03/19437714-horttechnology-implementation-sensor-based-automated-irrigation-commercial-floriculture.pdf)):

> Five soil moisture sensors (GS3; Decagon Devices, Pullman, WA) were distributed randomly throughout each crop

And, with an explicit replication rationale, "Greenhouse cucumber production using sensor-based irrigation" (2017),
Irrigation Association technical paper
([PDF](https://www.irrigation.org//IA/FileUploads/IA/Resources/TechnicalPapers/2017/GreenhouseCucumberProductionUsingSensor-basedIrrigation.pdf)):

> Irrigation was performed on-demand using **one substrate moisture sensor per experimental unit formed by four
> pots.**

> Replication differences are expected, and explained by the use of independent experimental units, variations in
> moisture caused by **container positioning in the greenhouse**, sensor installation, and the natural variability
> between plants

The container-positioning mechanism is the same one Athena names (fans, aisles), arrived at independently in a
peer-reviewed setting. That is the strongest corroboration in this document of *why* probe siting matters — and
notably it corroborates the **rationale**, while no peer-reviewed or extension source recommends a
sensors-per-zone *number* for containerised crops at all.

### Convergence, and what it is worth

AROYA's three-per-strain, Athena's main-plus-secondary with 2–3 plants sampled for runoff, and Grodan's
three-sensor standard set (see [Grodan](#grodan-grosens--the-one-source-that-says-how-to-reduce-multiple-probes))
land in the same place without citing each other. Treat this as
convergence among vendors sharing an industry practice, **not** as three independent confirmations of a measured
optimum. None of the three publishes data behind the number.

The rationale, by contrast, is stated identically by all of them and is what should drive design: probes exist
to sample **within-zone spatial variability caused by position relative to airflow, aisles and walls**. A design
that treats a zone's probes as interchangeable replicates contradicts Athena explicitly — one is the control
probe, the rest are not.

---

## 2. Hydraulics: one pump, N valves, run sequentially

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

### TrolMaster Aqua-X — a split bus, and a marketing page its own manual contradicts

**Tier A (manual).** [Aqua-X NFS-1 Instructions (PDF)](https://s3-us-west-2.amazonaws.com/trolmasterfilese/ManualFiles/Aqua-X+Irrigation+Controller(NFS-1)_Instructions.pdf)

> Each set of Aqua-X Irrigation Controller can connect up to 30 outputs (24V or 110V) and monitor the pH value,
> EC value and water temperature of nutrient.

> There are two RJ12 ports for the Control Board. One is for 24V Control Board (6 individually controlled 24V
> outputs for solenoid valves), the other is 110V Control Board (6 individually controlled 110V outputs for
> water pumps). The maximum number of connections to the Aqua-X is 5 pieces for either 24V Control Board or
> 110V Control Board.

This is a **split-bus** architecture: a 24 V bus for solenoids and a separate 110 V bus for pumps, 6 outputs per
board, max 5 boards, 30 outputs total. It is neither one-pump-per-zone nor a single master-pump abstraction —
NFS-1 has no master-pump linkage at all.

**Tier A (spec sheet).** [NFS-2 Aqua-X Pro Tech Sheet (PDF)](https://trolmasterfilese.s3.us-west-2.amazonaws.com/ManualFiles/Aqua-X+system/Main+Controllers/Aqua-X+Pro/NFS-2+Tech+Sheet.pdf)

> There are 2 control lines in NFS-2, Pump Line & Valve Line

> Master Pump Link functions by allowing users to employ multiple pumps, linked together with multiple groups of
> solenoids. The improved Master Pump Link function on the Aqua-X Pro will allow the user to control multiple
> water/booster pumps, with each pump assigned to only run with a selected group of solenoids.

That is the most explicit statement retrieved of the **general** topology: *N pumps, each bound to a group of
solenoids*. One-pump-many-valves is the degenerate single-pump case of it. If GSM ever models more than one pump,
this is the documented shape to match — a pump owns a group of zones, not a zone.

**⚠️ Marketing contradicts the manual.** The NFS-1 product page (tier C) claims
"up to (8) Water Content Sensors connected to a single Aqua-x controller"
([trolmaster.com/Products/Details/NFS-1](https://www.trolmaster.com/Products/Details/NFS-1)). The NFS-1 manual's
exhaustive specifications page lists **no substrate moisture input** — only WD-1 water detectors, an AMP-2 sensor
board, and nutrient-solution pH/EC/temp probes — and TrolMaster's own
[Aqua-X comparison chart](https://trolmasterfilese.s3.us-west-2.amazonaws.com/ManualFiles/Aqua-X+system/Main+Controllers/AUQA-X_NFS-1-2_Comparison.pdf)
marks the WCS and DFM rows "-" for NFS-1. The comparison chart lists "Crop Steering (with WCS-1/2)" as an
**NFS-2-only** feature. The earlier controller in this product line cannot do substrate crop steering at all.
This is the cleanest documented-practice-versus-marketing divergence in the corpus, and it is *within one vendor*.

### Autogrow / Bluelab IntelliDose — the small-scale case

**Tier A (manual).** [IntelliDose Controller Manual (PDF, BL_ENG_Manual_BCTIND01)](https://files.plytix.com/api/v1.1/file/public_files/pim/assets/89/90/94/62/629490895d155f1bc7e496a7/texts/85/ef/53/65/6553ef858005720eaf2dc0cd/BL_ENG_Manual_BCTIND01_IntelliDose-Controller.pdf)

> IntelliDose provides the ability to control up to 4 irrigation stations with an optional master pump.

> If a master pump is selected, this output will run each time any of the station outputs is set to run, to
> accommodate having a single irrigation pump with each station being watered by opening a solenoid valve.

> Sequential - where each station is run in turn (one after the other) all being triggered by a single trigger
> (day/night interval or time of day)

> Independent – where each station is completely independent, each having its own trigger (day/night interval or
> time of day).

This is the most GSM-relevant controller in the set: **four zones, one shared pump, and an explicit
sequential-versus-independent scheduling choice.** It also confirms the shared-pump semantics precisely — the
master output runs whenever *any* station runs. Irrigation is purely time-based; there is no flow input and no
substrate moisture input.

### Galcon G.S.I DC

**Tier A (manual).** [Galcon G.S.I DC Controller (PDF)](https://www.galconc.com/wp-content/uploads/2020/09/AT1272.pdf)

> The G.S.I DC Controller has the following output connectors: 12 irrigation valves / Master valve

Same shape again: N zone valves plus one master. Inputs are exactly rain sensor, water meter, fertilizer meter —
no substrate moisture.

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

## 3. Flow metering: optional, and vendors disagree on units

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

### Two of five controllers have no flow input at all

**Tier A**, from the manuals cited in §2. Autogrow IntelliDose: no flow or water meter input exists across the
41-page manual; irrigation is specified only as "Irrigate every" / "Irrigate time", i.e. purely time-based.
TrolMaster NFS-1: no flow meter in its exhaustive specifications list, and "-" in the DFM row of TrolMaster's own
comparison chart. Metering is an **upgrade tier**, not a baseline, in this equipment class — which independently
corroborates Athena's methodology running entirely without one.

### Where meters do exist, the reported unit is not consistent

This is the part that must not be simplified. Three vendors, three answers.

**OpenSprinkler — pulse in, cumulative volume out.** Tier A, manual (as above):

- Signal: "All dry-contact, 2-wire flow sensors (recommended)" plus "3-wire flow sensors that work with +5V".
- Conversion: "Flow Pulse Rate: can be found in the flow sensor datasheet" and is "used to convert flow pulse
  count to actual water volume. Precision is limited to 2 decimal places".
- Limit: "The flow click frequency should NOT exceed 50Hz".
- Reporting: records "total flow volume at the end of each station run and program cycle".
- Hardware limit: on OpenSprinkler v3 only the SN1 input supports a flow sensor; SN2 does not — i.e.
  **one meter per controller, shared across all stations, attributed by whichever station is running.**

That last point is the structural consequence of one-zone-open-at-a-time: a single shared meter on the manifold
can attribute volume per zone *only because* zones are sequenced. Concurrent zones on a shared meter make
per-zone attribution impossible without a meter per line. **This is the strongest hydraulic argument in the
corpus for serialising a shared-pump group** — it is not merely a pressure constraint, it is what makes metered
accounting possible at all.

**Galcon — pulse in, instantaneous rate out.** Tier A,
[G.S.I DC manual](https://www.galconc.com/wp-content/uploads/2020/09/AT1272.pdf):

> The GSI unit supports the following input devices: Rain sensor / Flow meter (pulse type) / Fertilizer meter

> Flow value currently detected by the flow sensor (in m 3/hr).

Same physical pulse sensor, but the controller surfaces a **rate in m³/hr** on its main screen, not a totaliser.

**TrolMaster DFM-1 — both, over a proprietary digital bus.** Tier A,
[DFM-1 Tech Sheet (PDF)](https://trolmasterfilese.s3.us-west-2.amazonaws.com/ManualFiles/Aqua-X+system/Water+monitoring/DFM-1/DFM-1+Tech+sheet.pdf):

> Rated Flow Rate: 0.53-15.85 Gallon/Min (2-60 L/min)

> Users can monitor the flow speed as well as the total flow volume.

> When using Feed By Volume, the DFM-1 will accurately measure and allow a precise and desired volume of nutrient
> solution to be used during each scheduled irrigation cycle.

Note the signal type differs too: the DFM-1's output connector is an "RJ12 Male Connector" on TrolMaster's
daisy-chain module bus. There is no K-factor or pulse-scaling for the user to configure — the meter reports
engineering units over the bus. So "pulse sensor + datasheet constant" is *not* universal either.

**Cross-vendor summary:**

| Product | Signal into controller | Unit surfaced |
| --- | --- | --- |
| OpenSprinkler (tier A) | dry-contact 2-wire pulse, ≤50 Hz, user-entered pulse rate | **cumulative** volume, totalised per station run and per program cycle |
| Galcon G.S.I DC (tier A) | "Flow meter (pulse type)", dry-contact pair | **instantaneous rate**, m³/hr |
| TrolMaster DFM-1 (tier A) | digital module on proprietary RJ12 bus, no K-factor | **both** — rate (gal/min and L/min) and total volume |
| Autogrow IntelliDose (tier A) | none | — |
| TrolMaster NFS-1 (tier A) | none | — |

**Design conclusion for GSM:** there is **no single documented convention**. A metered-irrigation feature must
accept both an instantaneous-rate source and a cumulative-totaliser source, and must not infer one from the
other. The earlier hypothesis that this equipment class standardises on cumulative-per-event is **not supported**
— it holds for OpenSprinkler (and therefore for AROYA), but Galcon contradicts it outright and TrolMaster
straddles it.

The generic Home Assistant case only widens this: HA flow entities commonly expose `L/min` rate, and a
`total_increasing` totaliser resets on device reboot. Both hazards are already real in the vendor corpus.

---

## 4. Zone counts: the honest answer is "no number"

**No retrieved primary source states a typical, recommended, or maximum-in-practice number of irrigation zones
per room or per facility.** Not AROYA's education guides or help docs, not Athena's 121-page methodology, not
the facility-engineering article, not the Netafim design guide.

What the sources do give:

**Hardware ceilings** (these are equipment capability, *not* evidence of practice — do not read them as such):

| Controller | Zone/station ceiling | Substrate probe ceiling |
| --- | --- | --- |
| Autogrow / Bluelab IntelliDose (tier A, manual) | **4 stations** + optional master pump | none (solution EC/pH only) |
| OpenSprinkler v3 (tier A, manual) | 8 onboard, expandable to 72 | n/a (probes are AROYA-side) |
| OpenSprinkler Pi (tier A, manual) | 8 onboard, expandable to 200 | n/a |
| Galcon G.S.I DC (tier A, manual) | 12 valves + 1 master valve | none |
| TrolMaster Aqua-X NFS-1 (tier A, manual) | 30 outputs (6 per board × max 5 boards, 24 V and 110 V buses) | **none** — no WCS support |
| TrolMaster Aqua-X Pro NFS-2 (tier A, spec sheet) | vendor states 300 *and* 600 in the same document (see disagreements) | "Medium Sensors (WCS-2, WCS-1): Max 50 pc" |

The **IntelliDose's four stations** is the single most interesting number here: a mainstream, currently-sold
fertigation controller whose entire zone ceiling sits inside the map's 2–6 target. It is evidence that a
small-digit zone count is a real product category, though still a capability rather than an observation.

Note also that no controller in the set provides one substrate probe per zone at its own ceiling. TrolMaster
NFS-2 caps medium sensors at 50 against hundreds of valve outputs, and the 50 is a *shared address pool*
("Nutrient Sensors (AMP-3, DFM-1, WD-1): Max 50 pc"). Probe-per-zone is not an assumption the hardware makes.

**A derivable floor.** Athena's strain-per-zone rule (below) makes zone count ≥ number of distinct cultivars
under one controller. AROYA's sensor guidance is denominated per strain for the same reason. Neither states how
many cultivars a room runs.

**One observed installation.** The single retrieved source that reports an actual deployed zone count is
peer-reviewed and not from this industry — Chappell, Dove, van Iersel, Thomas & Ruter, "Implementation of Wireless
Sensor Networks for Irrigation Control in Three Container Nurseries", *HortTechnology* 23(6):747–753 (2013),
[journals.ashs.org](https://journals.ashs.org/horttech/view/journals/horttech/23/6/article-p747.xml) (tier A):

> The 2-acre coldframe at MNI has a total of **54 irrigation valves**… The coldframe was initially divided into
> **eight separate irrigation zones, with six to seven valves per zone.**

Read this carefully, because it is the only observation available and it is easy to over-read:

- It is a **container nursery**, not cannabis, and 2 acres — far larger than GSM's referent scale.
- Critically, it shows **a two-level hierarchy**: 54 physical valves grouped into 8 *control* zones. The
  controlled/steered unit is not the valve. This is real-world evidence that "zone" and "valve" are distinct
  concepts even in a working install, and it matches UF/IFAS's note that one sensor can govern several valves.
- **8 control zones** is the only observed figure in the corpus, and it sits just above the map's 2–6 range at
  roughly 30× the area.

None of this makes 2–6 observed. It does mean the map's range is not obviously wrong in order of magnitude, and
it flags that GSM may need to distinguish a *steered zone* from a *valve* rather than assuming 1:1.

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

### Grodan — the only *quantified* within-zone uniformity tolerance

**Tier A/B (co-branded best-practice guide).** Grodan & Priva, *Best Practice Guidelines for Greenhouse Water
Management* (© 2016), p.26
([PDF](https://hortamericas.com/wp-content/uploads/2018/09/grodan_best-practice-water-management.pdf)):

> Check the variation between individual drippers **within a valve section** during crop turn around.
> • A variation of 0 and 5% is good • A variation of 5 and 7% is acceptable • A variation of > 7 to 10% usually
> indicates that the drippers need cleaning or replacing.

And Grodan's measurement procedure sheet, *Cleaning and checking the irrigation system*
([PDF](https://www.grodan.com/syssiteassets/downloads/tools--services/english/ts-2-3-checking-irrigation-en.pdf)):

> Select 10 drippers from the first, middle and bottom irrigation line of a chosen irrigation section. […] Adding
> up the volume of these 30 drippers provides a good insight into the output per section.

> 5% variation is good, no action is required. / 5% to 10% variation is poor, it is recommended that action is
> taken to correct this. / **More than 10% variation is extremely poor and will result in uneven slab water
> contents and poor water management capabilities if action is not taken.**

This puts a **number** on Netafim's qualitative do-not-mix-emitters rule: within one valve section, >10 % dripper
output variation is stated to break water management. It also gives a hydraulic sizing figure —
"As a general rule the distribution system should be designed to deliver 1.2 - 1.5 l/m2/hr" — where the stated
determinants include "the number of irrigation zones within one valve/pump compartment".

**An important negative finding.** Across every Grodan document retrieved — GroSens brochure and installation
manual, the e-Gro Companion quick guide, the Cannabis Grow Guide chapter on Precision Irrigation, the Best
Practice Guidelines, and the 6-phase tomato brochure — **Grodan never states that a section must be uniform in
cultivar, plant age or stage, dripper flow rate, or light level.** What Grodan constrains per section is (a) the
**slab/media type**, which is a configuration field in its software ("Media type — Choose the correct slab type
for this section"), and (b) **dripper output variation**, quantified above. Do not infer a Grodan crop-uniformity
rule; there isn't one. The cultivar rule is Athena's alone, softened by AROYA.

### Composite: what makes two cohorts incompatible

Assembled from the three sources above. Each dimension traces to a named source; the *list* is my synthesis.

| Dimension | Source | Mechanism | Threshold given? |
| --- | --- | --- | --- |
| Cultivar / strain | Athena (unconditional), AROYA (conditional on strain-matching) | divergent dryback rate | no |
| Substrate volume | AROYA | same shot % ⇒ different absolute volume ⇒ different VWC response | no |
| Substrate type | Athena (implicit — separate shot tables and field capacities), Grodan (explicit config field), METER (separate soilless-media calibration) | different field capacity and dryback curve; **and different raw-to-VWC calibration** | no |
| Emitter output variation | **Grodan (quantified)**, Netafim (qualitative), AROYA ("drip system is uniform") | same valve-open duration ⇒ different delivered volume | **yes — >10 % breaks it** |
| Dripline spacing | Netafim | distribution uniformity | no |
| Plant size / age / health | AROYA | divergent transpiration | no |
| Light intensity | AROYA | divergent transpiration | no |
| Elevation change > 10 ft | Netafim | pressure variation across the zone | **yes — 10 ft** |

Only two dimensions carry a published threshold. The rest are directional rules. Note also that substrate type is
the one dimension that is not merely agronomic: because METER ships a distinct soilless-media calibration, mixing
substrates under one probe produces *wrong numbers*, not just suboptimal irrigation.

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

## Grodan GroSens — the one source that says how to reduce multiple probes

GroSens is a *measurement* system, not a controller: no zones, no valve or pump outputs, no flow metering. It
answers the probe question, and it is the only retrieved source that states what to do with several probes in one
zone.

**Tier A (installation manual).**
[Grodan GroSens MultiSensor Installation Manual (PDF)](https://www.grodan.com/siteassets/downloads/downloads-en/installation-guides-en/grodan-grosens-installation-manual-multisensor-a4-2020-en.pdf)

> The Sensors that are in the same irrigation section should be used to calculate the average of that section.

That is an unambiguous rule, and it **conflicts with Athena's main-plus-secondary model** — see
[Disagreements](#disagreements). It is not an isolated line: averaging is built into the product's data path.
The Smartbox "creates averages of GroSens Sensor data over the chosen sections of the greenhouse according to the
grower's wishes", the analogue converter's outputs are specified as "0-5V output representing **average** water
content of the section" (likewise EC and temperature), and the e-Gro app shows "exact measurement values (**always
average of all sensors**)" per section. Grodan has committed to averaging at the hardware interface.

Grodan also ships three sensors as the standard set (component list: "3x" Sensors, 1× Receiver, 1× Reader,
1× Smartbox, 1× Converter), with a 50 m sensor-to-receiver range and a 3-minute data refresh, and describes the
set's purpose precisely:

> The GroSens Basic Set has been designed to guarantee reliable, representative WC and EC figures for **one
> watering section**.

So Grodan's three sensors are explicitly scoped to *one* section — the same denominator as AROYA's three-per-strain.

Placement is dripper- and drain-relative, the only such rule retrieved from any manufacturer:

> Place sensor 8 – 10 cm left from the 2nd block from the drain hole. […] In case, sensor over the width is on a
> slope, place sensor at the lowest site of the slab.

Measurement envelope, verbatim:

| Quantity | Range | Accuracy | Resolution |
| --- | --- | --- | --- |
| Water Content | 0–100 % V/v | 5 % V/V | 0.1 % V/V |
| Electrical Conductivity | 0–10 mS/cm | 0.5 mS/cm | 0.01 mS/cm |
| Temperature | 0–50 °C | 1 °C | 0.05 °C |

> The accuracy decreases slowly towards the borders of the respective ranges and is not guaranteed outside them.

**The ±5 % V/V water-content accuracy deserves attention.** Athena's maintenance-shot logic operates on dryback
deltas of a few percent VWC and GSM's own default `maintenance_dryback_percent` is 2.0. A single probe's absolute
accuracy is wider than the signal being steered on. This is the strongest published argument for averaging or for
trend-relative rather than absolute-threshold logic — and Grodan is the manufacturer stating it about its own
sensor, so it is not a competitor's criticism.

Integration is analogue, not digital:

> 3 free analogue connections to the climate computer. The GroSens System will communicate 3 separate signals:
> WC, EC and Temperature. These signals are 0-5 Volt signals.

**Tier C (brochure).**
[GroSens MultiSensor brochure (PDF)](https://www.grodan.com/siteassets/downloads/downloads-en/brochures-grodan-en/Grodan-Brochure-GroSens-Multisensor.pdf)

> The GroSens system starts with 3 sensors. However, the more sensors you install, the more accurate your insight
> into the WC and EC situation in the greenhouse will be.

This confirms the three-sensor convergence noted in §1 from a third vendor, in a non-cannabis greenhouse context
— which makes it the most interesting of the three, since it cannot be explained by cannabis-industry copying.
But note it is a brochure making an unquantified accuracy claim ("the more sensors … the more accurate"), with no
stated function relating count to error. Treat the *direction* as sound and the absence of a stopping rule as a
real gap: no source says when adding probes stops paying.

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

**3. Whether multiple probes in a zone should be averaged. This is a direct contradiction, and it matters most.**

- **Grodan (tier A, manual): average.** "The Sensors that are in the same irrigation section should be used to
  calculate the average of that section" — and averaging is wired into the Smartbox and the 0–5 V converter
  outputs, so this is a product commitment, not advice.
- **Athena (tier B): elect a representative.** Distinguishes a MAIN from a SECONDARY sensor, sites the main one
  at "a plant that best represents the average moisture level", then explicitly refuses to generalise:
  "Depending on the irrigation controller additional sensors may be used as supplemental data or may be used to
  take average readings."
- **UF/IFAS AE437 (tier A, extension): elect the driest.** "the zone that is normally the driest, or most in need
  of irrigation, is selected for placement of the sensor to ensure adequate irrigation in all zones."
- **AROYA (tier B): silent.** Three per strain framed as "the most helpful and complete dataset" — a dataset, not
  a control signal. Never says how it is reduced.
- **METER (tier A, application note): depends on the objective.** Estimating a true mean needs a sampling scheme;
  "if… the researcher is only interested in the temporal pattern of soil water content (e.g., for irrigation
  scheduling), then fewer soil moisture sensors may be required."

Four sources, three different reduction rules, and a manufacturer saying the right answer depends on what you are
computing. Note also that the two "elect a representative" rules **disagree with each other on which plant**:
Athena picks the *average* plant (objective: steer this zone accurately), UF/IFAS picks the *driest* zone
(objective: never under-water any zone it covers). Placement follows objective, not convention.

Context worth holding: the sources differ in setting. Grodan is rockwool slabs in glasshouse sections
(physically uniform, high measurement homogeneity, and its own ±5 % V/V sensor accuracy argues for averaging);
Athena is pots on benches beside fans and aisles, where its whole point is that position *creates* divergence and
METER warns that each spot has its own baseline. The conflict may be a substrate/layout artefact rather than a
conflict of principle — but no retrieved source says so, so it is recorded as a conflict.

Design consequence: **"what is a zone's VWC when it has three probes" has no single published answer, so GSM
should not silently pick one.** Whichever it picks is a decision requiring an ADR, not an implementation detail.

**4. Concurrency.** OpenSprinkler's firmware supports parallel groups. AROYA's integration on top of it states
"no more than one zone can be open at once." The platform is more restrictive than the hardware. Autogrow offers
the choice explicitly as a user setting (Sequential versus Independent). Whether serialisation is a hydraulic
judgement (a shared pump cannot supply two zones at spec pressure) or an integration simplification is not stated
anywhere retrieved — though §3 supplies a second, independent reason to serialise: a single shared flow meter can
only attribute volume per zone if zones do not overlap.

**5. TrolMaster's marketing versus TrolMaster's manual.** The NFS-1 product page advertises 8 water content
sensors; the NFS-1 manual and the vendor's own comparison chart show the model has no substrate moisture input,
and list crop steering as NFS-2-only. Recorded here rather than resolved, but for practical purposes the manual
and comparison chart agree with each other and the product page does not.

**6. TrolMaster's spec sheet versus itself.** The NFS-2 tech sheet states "Max. Up to 300 Valves in Total", "Max.
600 Pumps & Valves", and "up to 600 valves or pumps can be controlled by a single NFS-2" — on one document.
Separately, the NFS-2 quick-start manual prints "Flow Range 0-60mL/min" while the DFM-1 tech sheet rates the same
device at "2-60 L/min", a 1000× discrepancy. Neither is resolvable from the documents. The lesson for GSM is not
which number is right but that **vendor-published capability figures are unreliable enough that a design should
not be pinned to one.**

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
- **TrolMaster "AQS-1" / "AQS-2"** — the model numbers named in the ticket do not exist. The Aqua-X irrigation
  controllers are NFS-1, NFS-1+ and NFS-2. Recorded so the ticket's premise is corrected rather than silently
  reinterpreted.
- **The unit in which an NFS-2 "Feed By Volume" target is entered** (gallons versus litres), and whether the
  NFS-2 offers a unit toggle. This lives in the full NFS-2 instruction manual, which 403s on every mirror tried
  (`device.report`, `manuals.plus`); only the 7-page quick-start was obtainable. **This is the one sub-question of
  the units request left open**, and it is the one that would tell GSM what unit a grower expects to type.
- **DFM-1 accuracy, pulse constant / K-factor, and update interval** — absent from the DFM-1 tech sheet.
- **Whether a TrolMaster WCS binds 1:1 to an irrigation output** (Feed-on-Demand cardinality — one sensor per
  zone, or averaged across a group). Not stated in any TrolMaster document retrieved. This would have been a
  fourth data point on disagreement #3.
- **Hunter ACC2 / ICC2 flow documentation** — 403 on all four URLs attempted; Hunter appears to block automated
  fetching entirely. **Argus, Priva, Netafim NetBeat, Rain Bird commercial** — documentation dealer-gated, not
  attempted. Galcon was substituted.
- **Grodan e-Gro** (the irrigation-strategy software layer above GroSens) — not retrieved. This is the most
  significant remaining gap: e-Gro is where Grodan's *zoning* guidance would live, as opposed to GroSens'
  sensor-hardware guidance.
- **METER Group HTML pages** — `metergroup.com` sits behind a Cloudflare JavaScript interstitial; 403 to
  WebFetch and to browser-UA curl, and the `www` host fails TLS verification. **Method note:** the two METER
  articles quoted in §1 were recovered through the `r.jina.ai` text proxy of the primary METER URLs; the PDFs
  (application note, TEROS 11/12 manual) came directly from `publications.metergroup.com` and were text-extracted
  locally. Proxy-recovered text is one step removed from a direct fetch — treated as tier A because the proxy
  returns the page's own text rather than a summary, but flagged here.
- **TEROS 21 manual** — URL not located; product page 403.
- **A confirmed coir-specific calibration document.** Partially addressed: the TEROS 11/12 manual does carry a
  distinct "SOILLESS MEDIA" calibration alongside the mineral-soil one, which establishes the principle used in
  §5. A dedicated *coir-specific* calibration article was seen only in a search summary and is **not** cited.
- **TEROS 12 "1 L volume of influence versus ~200 mL typical"** — search summary only, not fetched. Not cited.
  If true it bears on how much within-zone variability a single probe already integrates.
- **AROYA's "Uniformity" crash course** — a second retrieval pass found `/knowledge-base/crash-courses/uniformity`
  and `/resources/uniformity` resolving to index or 404 pages. The quotes used in §5 come from
  `aroya.io/education-guides/uniformity-cannabis-cultivation`, which *did* fetch successfully in this session.
  AROYA's knowledge base appears to have several dead or duplicated slugs; the education-guides path is the live one.
- **Grodan plants-per-slab / plants-per-block figures** — block and slab dimensions, volumes, drip-stakes-per-block
  and 6,000 slabs/ha were retrieved, but no plants-per-slab figure appears in any Grodan document fetched.
- **A peer-reviewed or extension publication that *recommends* a sensors-per-zone number for containerised crops**
  — none found. The container papers state counts only as experimental design; the extension sources that do give
  guidance (UF/IFAS, UMN) are turf/landscape and field-crop contexts. This is a real absence in the literature,
  not a retrieval failure.
- **Grodan e-Gro** irrigation-strategy software documentation beyond the Companion App quick guide, and the
  **GroSens HandHeld** documentation.
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
  zone can be open at once"; Autogrow's Sequential mode; Galcon and IntelliDose both wiring one master to N
  zone valves). A queue with a single in-flight zone matches published practice on every controller retrieved.
  Two independent reasons support it: shared-pump capacity, and the fact that a single shared flow meter can
  attribute volume per zone *only* if zones do not overlap. If GSM ever models multiple pumps, TrolMaster's
  Master Pump Link is the documented shape — **a pump owns a group of zones**, so arbitration is per pump-group,
  not global.
- **Flow-meter unit handling** (544, "Not yet specified"): **there is no single convention to adopt.**
  OpenSprinkler totalises pulses into cumulative volume per station run; Galcon surfaces an instantaneous rate in
  m³/hr from the same class of pulse sensor; TrolMaster's DFM-1 reports both over a digital bus with no
  user-visible pulse constant. A metered-irrigation feature must accept rate and totaliser sources as distinct
  configured shapes and must not infer one from the other. The staged-confidence framing survives intact and is
  reinforced: Athena's published methodology runs entirely open-loop with a manual jug check, and two of five
  controllers have no flow input at all, so metering is genuinely an upgrade tier rather than a baseline.
- **Probe reduction** (a decision 544 has not yet listed, and should): sources directly contradict each other on
  whether a zone's probes are averaged (Grodan) or elect a representative (Athena). GSM cannot pick silently;
  this warrants its own ADR. Grodan's own ±5 % V/V accuracy figure against Athena's few-percent dryback deltas
  is the substantive argument in the averaging direction.
- **Zone identity**: sources constrain zone *composition* strongly and zone *count* not at all. The composition
  table in §5 is the sourced answer. GSM should let the grower declare zone membership rather than deriving it,
  given disagreement #1.
- **Degraded control**: Athena's model is one designated representative probe per zone, extras optional, and
  METER states outright that irrigation scheduling needs fewer sensors than estimating a true mean. A
  single-probe zone is therefore the *documented normal case*, not a degraded one. Any design treating one probe
  as degraded contradicts both. UF/IFAS additionally documents a graceful-degradation pattern GSM has not
  considered: **one probe governing several valves, sited in the driest zone** so no zone is under-watered. That
  is a published fallback for "we have fewer probes than zones", which is the likely real-world state.
- **Zone vs valve**: the one observed install groups 54 valves into 8 control zones, and UF/IFAS defines a zone
  *as* a solenoid valve while describing one sensor covering several. GSM should not assume steered-zone and
  valve are 1:1 — deciding that mapping is itself a charting question.
- **Existing GSM shape**: `models/irrigation.py` already carries `SubstrateProfile` (`media_type`,
  `liters_per_pot`) and percent-of-substrate shot sizing (`p1_shot_volume_percent`, `p2_shot_volume_percent`),
  which is exactly Athena's model. `models/growspace.py` already has a `Subarea` ("A named sub-zone within a
  growspace with its own environment sensors") carrying an `EnvironmentConfig` but no irrigation config — worth
  charting whether an Irrigation Zone is a new peer of `Subarea` or an extension of it.
