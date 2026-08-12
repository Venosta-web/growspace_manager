# Plants stay outside the device registry

Plants, Catalogued Strains, and Ancestor Strains are Growspace Manager records, not Home Assistant devices. Growspaces remain devices, while one dedicated Strain Library device owns the Strain Library and Seed Inventory entities; general overview and VPD entities remain on the Growspace Manager Service device. This avoids one empty, strain-named device per Plant and keeps lineage imports from affecting the integration's device overview.

Legacy Plant devices are removed idempotently during setup when their config entry, manufacturer, and `Plant` model fingerprint match. We accept the loss of any user-assigned names or areas on those obsolete devices in exchange for a clean registry and a stable boundary. The Strain Library sensor counts Catalogued Strains as its state and exposes ancestor and total counts as diagnostic attributes; individual strains never become devices.
