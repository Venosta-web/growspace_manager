# Switch off a supplemental light before releasing control

Disabling or deleting a Supplemental Light, or assigning its schedule to another device, can remove Growspace Manager's ability to switch off the old device. While automation has control, Growspace Manager sends the old device an off command before releasing it. If the device is unreachable, the off command fails, or a Lights Manual Override prevents the command, the grower sees the reason and must explicitly choose to release the old device anyway.
