# MEPdetect

Symbol detection and circuit tracing for MEP construction drawings.

MEPdetect reads a plan set — PDF, image or DXF — detects electrical symbols with
a YOLO11 model, and works out how those symbols are wired together. The result
is a netlist and a per-circuit device count, exportable as CSV, Excel, a DXF
overlay or a PDF report.

Licensed under [AGPL-3.0](LICENSE).

---

## What the tracer actually does

Most of the value is in the tracing, and it takes two paths depending on what
the sheet gives it.

**Vector PDFs** — the drawing states its own connectivity, so the pixels are
never consulted. Conductors are isolated by the pen they are plotted with,
because a drawing office gives branch wiring its own lineweight. Homerun
arrowheads are recognised by geometry (a small polygon with one vertex further
from the centre than the rest), conductor counts come from the hash marks behind
the arrow, and circuit tags are read as real text. Connectivity is computed on
the segments directly, so taps and small gaps survive at full precision.

**Scans and rasterised sheets** — the pixels are traced instead: binarize,
blank the symbol boxes, discard blob-like components, thin the remaining runs
for junction nodes, and read an arrowhead from the stroke thickness at a run's
end. Circuit tags that were converted to curves are recovered with OCR in a
window around each homerun.

Two drawing conventions are handled, because both turn up in the same plan set:
sheets that draw the conductor runs, and Revit-style sheets that draw no wiring
at all and annotate each device with its panel-circuit designation. A circuit
carrying the same tag on another sheet is followed across the matchline and
counted once.

## Other capabilities

- **Scale calibration** — give it two points a known distance apart and every
  traced length is reported in real feet or metres instead of pixels.
- **Rating mining** — kVA, voltage, kAIC, ampere and equipment-tag text is read
  off the sheet and attached to the panel detected next to it.
- **Reconciliation** — circuits, sheet text and detected symbol counts are
  cross-checked against each other and disagreements are reported as
  MATCH / MISMATCH / MISSING / INFO.
- **Training service** — fine-tune a YOLO11 model on your own symbol library.

## Services

The root `docker-compose.yml` brings up six containers.

| Service | Host port | Source |
|---|---|---|
| `landing-page` | 8090 | `mepdetect-frontend/` |
| `detection-api` | 8091 | `mepdetect-backend/` |
| `training-api` | 8092 | `mepdetect-training/` |
| `user-api` | 8093 | `mepdetect-user-api/` |
| `postgres` | internal | `postgres:15-alpine` |
| `redis` | internal | `redis:7-alpine` |

## Quick start

Requires Docker with the `compose` plugin, and `python3` on the host (the
compose wrapper uses it to derive the Postgres environment).

```bash
cp mepdetect-user-api/.env.example mepdetect-user-api/.env
```

Fill in at least `POSTGRES_PASSWORD` — it is the only variable with no default,
and Postgres will not start without it. Generate the session secrets with
`openssl rand -hex 32`. Then:

```bash
./deploy.sh
```

The landing page comes up on <http://localhost:8090>, and the detection API
documents itself at <http://localhost:8091/api/docs>.

For any other compose subcommand with the same environment:

```bash
./scripts/dcompose ps
```

## Detection API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/detect` | Upload one drawing, start a job |
| `POST` | `/api/detect/batch` | Up to 50 drawings in one job |
| `GET` | `/api/jobs/{job_id}` | Job status and results |
| `GET` | `/api/jobs/{job_id}/download/{file_type}` | Fetch an export |
| `GET` | `/api/models` | Available detection models |
| `GET` | `/health` | Health check |

Useful parameters on `/api/detect`:

| Parameter | Default | Meaning |
|---|---|---|
| `confidence` | `0.25` | Minimum detection confidence |
| `dpi` | `400` | Render resolution for PDF pages |
| `trace_circuits` | `false` | Run the circuit tracer |
| `export_formats` | `json,csv,excel` | Also `netlist`, `dxf`, `pdf` |
| `ref_points` | — | `x1,y1,x2,y2` in rendered pixels, for calibration |
| `real_distance` | — | Real distance between those points |
| `units` | `feet` | Unit the distance is stated in |

These are read from the multipart body or from the query string, whichever the
client finds convenient; if both carry the same setting, the form field wins. A
value that cannot be parsed is rejected with a 400 rather than quietly falling
back to its default.

Detect and trace a sheet, calibrated so lengths come back in feet:

```bash
curl -F file=@plan.pdf -F trace_circuits=true -F export_formats=netlist,dxf,pdf -F ref_points=100,200,1100,200 -F real_distance=50 http://localhost:8091/api/detect
```

## Tracing a sheet without the API

Useful for checking the tracer against a real drawing before a symbol model
exists for it — detections are optional, and the wiring, nodes and homeruns are
still traced without them.

```bash
python mepdetect-backend/tools/trace_pdf.py plan.pdf --page 1 --dpi 150 --out traced/
```

## Development

```bash
pip install -r mepdetect-backend/requirements.txt
```

```bash
python -m pytest mepdetect-backend/tests -q
```

## Scope and verification

MEPdetect produces a **takeoff aid**. Its counts, netlists and lengths are
derived from what the drawings contain and from a model's predictions, and they
carry the errors of both: a symbol the model misses is absent from the count, a
run the tracer cannot follow is absent from the netlist, and a length is only as
true as the calibration it was given. Every output is intended to be checked
against the drawings by a competent reviewer before it informs a bid, a
purchase or a design decision. Nothing here is a substitute for engineering
judgement, and no output is a sealed deliverable.

## Licence

Copyright (C) 2026 Alfonso Davila

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU Affero General Public License as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the [GNU Affero General Public License](LICENSE) for
more details.

AGPL-3.0 covers network use: if you run a modified version of MEPdetect as a
service that users interact with over a network, you must offer those users the
source of your modified version.
