"""Reviewable production release commands. Never use the active gcloud project."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra" / "production"
DIGEST = re.compile(r"^asia-southeast1-docker\.pkg\.dev/(volt-debt-prd[a-z0-9-]*)/debt/(api|web|scanner)@sha256:[a-f0-9]{64}$")


def run(arguments, capture=False):
    return subprocess.run(arguments, cwd=ROOT, check=True, text=True,
                          stdout=subprocess.PIPE if capture else None).stdout


def project(value):
    if not re.fullmatch(r"volt-debt-prd[a-z0-9-]*", value) or len(value) > 30:
        raise ValueError("a dedicated production project is required")
    return value


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_release(path):
    value = json.loads(Path(path).read_text())
    project(value["project"])
    if not re.fullmatch(r"[a-f0-9]{40}", value["revision"]): raise ValueError("pin a full Git commit")
    for name in ("api", "web", "scanner"):
        match = DIGEST.fullmatch(value["images"][name])
        if not match or match[1] != value["project"] or match[2] != name:
            raise ValueError("incorrect release image digest")
    return value


def verify_gates(path, release):
    path = Path(path)
    evidence = json.loads(path.read_text())
    if evidence.get("project") != release["project"] or evidence.get("images") != release["images"]:
        raise ValueError("evidence must cover these exact production images")
    for gate in ("backend", "frontend", "role_e2e", "session", "concurrency", "load", "restore", "rollback", "reconciliation", "alerts"):
        record = evidence.get(gate, {})
        proof = path.parent / record.get("artifact", "missing")
        if record.get("passed") is not True or not proof.is_file() or sha(proof) != record.get("sha256"):
            raise ValueError("missing or failed gate: " + gate)
    load = evidence["load"]
    if not (load.get("users", 0) >= 10 and load.get("duration_seconds", 0) >= 7200 and
            0 <= load.get("workbook_p95_seconds", -1) <= 2 and
            0 <= load.get("unexpected_5xx_rate", -1) < 0.005 and
            load.get("lost_writes") == 0 and load.get("duplicate_writes") == 0 and load.get("oom") is False):
        raise ValueError("load thresholds failed")
    restore = evidence["restore"]
    if not (0 <= restore.get("rpo_seconds", -1) <= 300 and 0 <= restore.get("rto_seconds", -1) <= 3600):
        raise ValueError("recovery targets unproven")
    if evidence["reconciliation"].get("unexplained_differences") != 0 or not evidence.get("data_approver"):
        raise ValueError("real data has not been approved")
    if not evidence.get("incident_owner") or not evidence.get("staging_writes_and_schedules_stopped"):
        raise ValueError("cutover ownership and staging freeze required")
    return evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    manifest = sub.add_parser("manifest")
    for name in ("project", "revision", "output"): manifest.add_argument("--" + name, required=True)
    manifest.add_argument("--region", default="asia-southeast1")
    plan = sub.add_parser("plan")
    plan.add_argument("--vars", required=True)
    plan.add_argument("--out", required=True)
    plan.add_argument("--terraform", default="terraform")
    apply = sub.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--reviewed-sha256", required=True)
    apply.add_argument("--terraform", default="terraform")
    apply.add_argument("--release")
    apply.add_argument("--evidence")
    migrate = sub.add_parser("migrate")
    migrate.add_argument("--project", required=True)
    migrate.add_argument("--region", default="asia-southeast1")
    gates = sub.add_parser("verify-gates")
    gates.add_argument("--release", required=True)
    gates.add_argument("--evidence", required=True)
    args = parser.parse_args()
    if args.command == "manifest":
        project(args.project)
        if args.region != "asia-southeast1" or not re.fullmatch(r"[a-f0-9]{40}", args.revision):
            raise ValueError("pin a full Git commit and the production region")
        images = {}
        for name in ("api", "web", "scanner"):
            image = f"{args.region}-docker.pkg.dev/{args.project}/debt/{name}"
            digest = run(["gcloud", "artifacts", "docker", "images", "describe", image + ":" + args.revision,
                          "--project", args.project, "--format=value(image_summary.digest)"], True).strip()
            images[name] = image + "@" + digest
        Path(args.output).write_text(json.dumps({"project": args.project, "revision": args.revision,
                                               "images": images}, indent=2) + "\n")
        load_release(args.output)
    elif args.command == "plan":
        run([args.terraform, "-chdir=" + str(INFRA), "plan", "-input=false", "-var-file=" + str(Path(args.vars).resolve()),
             "-out=" + str(Path(args.out).resolve())])
        print("Review the plan. SHA256:", sha(args.out))
    elif args.command == "apply":
        if sha(args.plan) != args.reviewed_sha256: raise ValueError("reviewed plan has changed")
        planned = json.loads(run([args.terraform, "-chdir=" + str(INFRA), "show", "-json", str(Path(args.plan).resolve())], True))
        project_id = project(planned["variables"]["project_id"]["value"])
        for change in planned.get("resource_changes", []):
            if "delete" in change["change"]["actions"]: raise ValueError("deletion or replacement requires a separate reviewed procedure")
        if planned["variables"].get("go_live", {}).get("value"):
            if not args.release or not args.evidence: raise ValueError("go live requires release and evidence")
            release = load_release(args.release)
            if release["project"] != project_id: raise ValueError("release project mismatch")
            verify_gates(args.evidence, release)
            for name in ("api", "web", "scanner"):
                if planned["variables"][name + "_image"]["value"] != release["images"][name]:
                    raise ValueError("plan image differs from tested image")
        run([args.terraform, "-chdir=" + str(INFRA), "apply", "-input=false", str(Path(args.plan).resolve())])
    elif args.command == "migrate":
        project(args.project)
        run(["gcloud", "run", "jobs", "execute", "debt-migrate", "--project", args.project,
             "--region", args.region, "--wait"])
    else:
        verify_gates(args.evidence, load_release(args.release))
        print("All release gates verified")


if __name__ == "__main__": main()
