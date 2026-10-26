# CCL CAD Converter v0.3 candidate

Bounded isolated `DWG -> DXF` converter for `CCL-SYS-CAD-BRIDGE-001`.

## Contract

- Source DWG is read-only input. Conversion writes only to a separate derived-artifact result area.
- One request converts one explicitly selected DWG. There is no default whole-repository batch conversion.
- Derived artifact identity is bound to source SHA-256, so a new DWG revision cannot silently reuse an old DXF.
- `manifest.json` records source filename / Drive file ID / revision or path when provided / source SHA, LibreDWG ref + binary version, output SHA, size, parse verification, layer/entity inventory and finite extents.
- `ezdxf` must parse the produced DXF. Non-empty entity/layer inventory and finite reasonable model-space extents are required for PASS.
- Optional gate sentinels can require a known layer and handle.
- Format/geometry verification does **not** infer GFA, outer boundary or exclusion semantics.
- A file failure is local to that conversion call. Batch orchestration, when used later, must continue other files independently.

## API

`POST /convert` multipart field `file=<drawing.dwg>`.

Optional provenance headers:

- `X-CCL-Source-Id`
- `X-CCL-Source-Revision`
- `X-CCL-Source-Path`
- `X-CCL-Expected-SHA256`
- `X-CCL-Token` when `CCL_CAD_TOKEN` is configured

Response is a ZIP containing the SHA-bound DXF, `manifest.json`, and `converter.log`.

## Single-file gate

For commissioning only, set `CCL_GATE_FIXTURE_URL` plus source metadata environment variables. On service startup the converter runs exactly that one file and exposes `/gate` with `PASS` or `FAIL`. This gate is technical evidence only and does not imply Operational Readiness.
