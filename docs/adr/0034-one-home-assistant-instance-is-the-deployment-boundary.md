# One Home Assistant instance is the deployment boundary

One Home Assistant instance contains the complete Organization and all Facilities, Growspaces, Irrigation Zones, and Delivery Groups. There is no cross-instance federation, organization cloud service, or remote facility-control protocol; all operational access remains within Home Assistant and the Growspace Manager integration. This makes the Home Assistant host a shared organizational failure domain, but preserves a single local authority and avoids imposing distributed-system complexity on either hobby or facility growers.
