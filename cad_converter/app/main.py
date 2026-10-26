from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

import ezdxf
from ezdxf import bbox
from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

APP_VERSION = "0.3.0"
MAX_UPLOAD_MB = int(os.getenv("CCL_MAX_UPLOAD_MB", "80"))
CONVERT_TIMEOUT = int(os.getenv("CCL_CONVERT_TIMEOUT", "180"))
CCL_TOKEN = os.getenv("CCL_CAD_TOKEN", "").strip()
LIBREDWG_REF = os.getenv("CCL_LIBREDWG_REF", "unknown").strip() or "unknown"
RESULT_ROOT = Path(os.getenv("CCL_RESULT_DIR", "/tmp/ccl_cad_results")).resolve()
RESULT_ROOT.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="CCL CAD Converter", version=APP_VERSION)
GATE_RESULT: dict = {"status": "NOT_RUN"}


def _auth(x_ccl_token: str | None) -> None:
    if CCL_TOKEN and x_ccl_token != CCL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid CCL token")


def _run(cmd: list[str], timeout: int = CONVERT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
        env={**os.environ, "LC_ALL": "C.UTF-8", "LANG": "C.UTF-8"},
    )


def _tool_version() -> str:
    try:
        cp = _run(["dwg2dxf", "--version"], timeout=10)
        return (cp.stdout or "").strip().splitlines()[0][:300]
    except Exception as exc:
        return f"unavailable: {type(exc).__name__}"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_text(entity) -> str | None:
    try:
        if entity.dxftype() == "TEXT":
            return entity.dxf.text
        if entity.dxftype() == "MTEXT":
            return entity.plain_text()
        if entity.dxftype() == "ATTRIB":
            return entity.dxf.text
    except Exception:
        return None
    return None


def _bbox_summary(msp) -> dict:
    try:
        box = bbox.extents(msp, fast=True)
        if not box.has_data:
            return {"available": False, "finite": False, "reasonable": False}
        lo = [float(box.extmin.x), float(box.extmin.y), float(box.extmin.z)]
        hi = [float(box.extmax.x), float(box.extmax.y), float(box.extmax.z)]
        vals = lo + hi
        finite = all(math.isfinite(v) for v in vals)
        span = [hi[i] - lo[i] for i in range(3)]
        reasonable = finite and all(s >= 0 for s in span) and max(abs(v) for v in vals) < 1e12 and max(span) > 0
        return {
            "available": True,
            "min": lo,
            "max": hi,
            "span": span,
            "finite": finite,
            "reasonable": reasonable,
        }
    except Exception as exc:
        return {
            "available": False,
            "finite": False,
            "reasonable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _summarize_dxf(path: Path) -> tuple[dict, object]:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    entity_types: Counter[str] = Counter()
    layers: Counter[str] = Counter()
    texts: list[dict] = []
    closed_polylines = 0
    inserts = 0

    for ent in msp:
        etype = ent.dxftype()
        entity_types[etype] += 1
        layer = getattr(ent.dxf, "layer", "") or ""
        layers[layer] += 1
        if etype == "INSERT":
            inserts += 1
        if etype == "LWPOLYLINE":
            try:
                if ent.closed:
                    closed_polylines += 1
            except Exception:
                pass
        if len(texts) < 5000:
            text = _safe_text(ent)
            if text:
                try:
                    insert = getattr(ent.dxf, "insert", None)
                    xyz = list(insert) if insert is not None else None
                except Exception:
                    xyz = None
                texts.append({"type": etype, "layer": layer, "text": text, "insert": xyz})

    block_names = []
    for block in doc.blocks:
        try:
            block_names.append(block.name)
        except Exception:
            pass

    layouts = []
    for layout in doc.layouts:
        try:
            layouts.append(layout.name)
        except Exception:
            pass

    summary = {
        "dxf_version": doc.dxfversion,
        "encoding": getattr(doc, "encoding", None),
        "modelspace_entity_count": sum(entity_types.values()),
        "entity_types": dict(entity_types.most_common()),
        "layer_usage": dict(layers.most_common()),
        "layer_table": [layer.dxf.name for layer in doc.layers],
        "layout_names": layouts,
        "block_names": block_names,
        "insert_count": inserts,
        "closed_lwpolyline_count": closed_polylines,
        "text_sample_count": len(texts),
        "texts": texts,
        "extents": _bbox_summary(msp),
    }
    return summary, doc


def _verify_summary(summary: dict, doc, expected_layer: str = "", expected_handle: str = "") -> dict:
    entity_count = int(summary.get("modelspace_entity_count") or 0)
    layer_count = len(summary.get("layer_table") or [])
    extents = summary.get("extents") or {}
    checks = {
        "nonzero_entities": entity_count > 0,
        "nonzero_layers": layer_count > 0,
        "finite_reasonable_extents": bool(extents.get("reasonable")),
    }
    sentinel = None
    if expected_layer:
        checks["expected_layer_present"] = expected_layer in (summary.get("layer_table") or [])
    if expected_handle:
        try:
            ent = doc.entitydb.get(expected_handle.upper()) or doc.entitydb.get(expected_handle)
        except Exception:
            ent = None
        sentinel = {
            "handle": expected_handle,
            "found": ent is not None,
            "type": ent.dxftype() if ent is not None else None,
            "layer": getattr(ent.dxf, "layer", None) if ent is not None else None,
        }
        checks["expected_handle_present"] = ent is not None
        if expected_layer:
            checks["expected_handle_layer_match"] = ent is not None and getattr(ent.dxf, "layer", None) == expected_layer
    return {"pass": all(checks.values()), "checks": checks, "sentinel": sentinel}


def _convert_file(
    input_path: Path,
    source_filename: str,
    source_meta: dict,
    expected_sha256: str = "",
    expected_layer: str = "",
    expected_handle: str = "",
) -> tuple[Path, dict]:
    source_sha = _sha256(input_path)
    if expected_sha256 and source_sha.lower() != expected_sha256.lower():
        raise ValueError(f"SOURCE_SHA256_MISMATCH expected={expected_sha256} actual={source_sha}")

    source_size = input_path.stat().st_size
    magic = input_path.read_bytes()[:6]
    if not magic.startswith(b"AC10"):
        raise ValueError("Input does not look like an AutoCAD DWG")

    artifact_key = source_sha[:16]
    result_dir = RESULT_ROOT / artifact_key
    result_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(source_filename).stem
    output_path = result_dir / f"{stem}__{artifact_key}.dxf"
    report_path = result_dir / "manifest.json"
    log_path = result_dir / "converter.log"
    zip_path = result_dir / f"{stem}__{artifact_key}__CCL_CAD.zip"

    for p in (output_path, report_path, log_path, zip_path):
        if p.exists():
            p.unlink()

    started = time.time()
    cp = _run(["dwg2dxf", "--as", "r2018", "-y", "-o", str(output_path), str(input_path)])
    log_path.write_text(cp.stdout or "", encoding="utf-8", errors="replace")
    if cp.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"CONVERSION_FAILED rc={cp.returncode} log_tail={(cp.stdout or '')[-1200:]}")

    dxf_summary, doc = _summarize_dxf(output_path)
    verification = _verify_summary(dxf_summary, doc, expected_layer=expected_layer, expected_handle=expected_handle)
    if not verification["pass"]:
        raise RuntimeError(f"DXF_VERIFICATION_FAILED {json.dumps(verification, ensure_ascii=False)}")

    manifest = {
        "schema": "CCL_CAD_DERIVED_ARTIFACT_PROVENANCE_v1",
        "service": "CCL CAD Converter",
        "service_version": APP_VERSION,
        "source": {
            "filename": source_filename,
            "size_bytes": source_size,
            "magic": magic.decode("ascii", errors="replace"),
            "sha256": source_sha,
            "drive_file_id": source_meta.get("drive_file_id") or None,
            "revision": source_meta.get("revision") or None,
            "project_path": source_meta.get("project_path") or None,
            "read_only_contract": True,
        },
        "converter": {
            "engine": "LibreDWG dwg2dxf",
            "binary_version": _tool_version(),
            "libredwg_ref": LIBREDWG_REF,
            "target_dxf_version": "r2018",
        },
        "output": {
            "filename": output_path.name,
            "sha256": _sha256(output_path),
            "size_bytes": output_path.stat().st_size,
            "artifact_key": artifact_key,
            "result_area": str(result_dir),
        },
        "elapsed_seconds": round(time.time() - started, 3),
        "verification": verification,
        "dxf_summary": dxf_summary,
        "semantic_boundary": "GEOMETRY/FORMAT VERIFICATION ONLY; no GFA/outer/exclusion semantic inference",
    }
    report_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(output_path, arcname=output_path.name)
        zf.write(report_path, arcname="manifest.json")
        zf.write(log_path, arcname="converter.log")

    return zip_path, manifest


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "service": "CCL CAD Converter",
        "app_version": APP_VERSION,
        "dwg2dxf": _tool_version(),
        "libredwg_ref": LIBREDWG_REF,
        "result_root": str(RESULT_ROOT),
        "gate_status": GATE_RESULT.get("status"),
    }


@app.get("/gate")
def gate() -> dict:
    return GATE_RESULT


@app.post("/convert")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    x_ccl_token: str | None = Header(default=None),
    x_ccl_source_id: str | None = Header(default=None),
    x_ccl_source_revision: str | None = Header(default=None),
    x_ccl_source_path: str | None = Header(default=None),
    x_ccl_expected_sha256: str | None = Header(default=None),
):
    _auth(x_ccl_token)
    filename = Path(file.filename or "input.dwg").name
    if not filename.lower().endswith(".dwg"):
        raise HTTPException(status_code=400, detail="Only .dwg input is accepted")

    td = Path(tempfile.mkdtemp(prefix="cclcad_source_"))
    background_tasks.add_task(shutil.rmtree, td, True)
    input_path = td / "source.dwg"

    size = 0
    with input_path.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                raise HTTPException(status_code=413, detail=f"DWG exceeds {MAX_UPLOAD_MB} MB")
            out.write(chunk)

    try:
        zip_path, _ = _convert_file(
            input_path,
            filename,
            {
                "drive_file_id": x_ccl_source_id,
                "revision": x_ccl_source_revision,
                "project_path": x_ccl_source_path,
            },
            expected_sha256=x_ccl_expected_sha256 or "",
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="DWG conversion timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="dwg2dxf engine is unavailable")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"{type(exc).__name__}: {exc}")

    return FileResponse(zip_path, media_type="application/zip", filename=zip_path.name)


@app.on_event("startup")
def startup_gate() -> None:
    global GATE_RESULT
    url = os.getenv("CCL_GATE_FIXTURE_URL", "").strip()
    if not url:
        GATE_RESULT = {"status": "NOT_RUN", "reason": "CCL_GATE_FIXTURE_URL not set"}
        return

    td = Path(tempfile.mkdtemp(prefix="cclcad_gate_source_"))
    input_path = td / "source.dwg"
    try:
        with urllib.request.urlopen(url, timeout=60) as r, input_path.open("wb") as out:
            shutil.copyfileobj(r, out, length=1024 * 1024)
        filename = os.getenv("CCL_GATE_FIXTURE_NAME", "gate.dwg")
        zip_path, manifest = _convert_file(
            input_path,
            filename,
            {
                "drive_file_id": os.getenv("CCL_GATE_FIXTURE_DRIVE_ID", ""),
                "revision": os.getenv("CCL_GATE_FIXTURE_REVISION", ""),
                "project_path": os.getenv("CCL_GATE_FIXTURE_PATH", ""),
            },
            expected_sha256=os.getenv("CCL_GATE_FIXTURE_SHA256", ""),
            expected_layer=os.getenv("CCL_GATE_EXPECT_LAYER", ""),
            expected_handle=os.getenv("CCL_GATE_EXPECT_HANDLE", ""),
        )
        GATE_RESULT = {"status": "PASS", "zip_path": str(zip_path), "manifest": manifest}
        print("CCL_DXF_GATE_PASS " + json.dumps({
            "source_sha256": manifest["source"]["sha256"],
            "output_sha256": manifest["output"]["sha256"],
            "output_size_bytes": manifest["output"]["size_bytes"],
            "entities": manifest["dxf_summary"]["modelspace_entity_count"],
            "layers": len(manifest["dxf_summary"]["layer_table"]),
            "extents": manifest["dxf_summary"]["extents"],
            "sentinel": manifest["verification"].get("sentinel"),
        }, ensure_ascii=False), flush=True)
    except Exception as exc:
        GATE_RESULT = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}
        print("CCL_DXF_GATE_FAIL " + json.dumps(GATE_RESULT, ensure_ascii=False), flush=True)
    finally:
        shutil.rmtree(td, ignore_errors=True)
