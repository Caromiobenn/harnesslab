# Image-derived task controls

The native controls for `chess-best-move` and `gcode-to-text` capture the task's
`/app` workspace. Each task runs an empty submission and the reference solution
under both public and offline network conditions, for eight checks in total.

Both arms receive the same accepted public APT and Python installer archives.
The actor installs its own dependencies. The official verifier is provisioned
only after actor submission, and the original assertions remain unchanged.

The installer preparation completed in CPU job `1208292`: both offline import
probes passed and both temporary instances were verified deleted. Wheel archive
SHA-256 values are:

- Chess: `0642dfab7951858ad56f35ff7a05562c0dbf6736df4db866383d89bd6605ba48`
- G-code: `9d82cecbe22b39434161f885b01ea0135ef055b46fc7b24759a1e27a47675ecc`

These preparation results establish installer availability. The subsequent
empty/reference outcomes determine task readiness and are retained separately.
