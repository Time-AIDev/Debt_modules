"""Publish the exact commit fence of a reviewed preview, never a later poll head."""
import json

from sqlalchemy import text

from .durable_runs import WORKER_RUN

PREVIEW_KINDS = frozenset({'master-sheet', 'peak-report', 'peak-receipt'})


def require(conn, reviewed, supplied=None):
    if reviewed is None:
        return  # Legacy staged runs retain their existing source/epoch checks.
    from .production_unit import ProductionUnitMiddleware
    current = conn.execute(text('select version from app.business_version where singleton')).scalar_one()
    if str(current) != str(reviewed) or supplied is not None and str(supplied) != str(reviewed):
        raise ProductionUnitMiddleware.problem('preview_stale', 409)


def restamp(conn, run_id, source):
    """Re-bind a staged (not yet applied) landing run to the version that stands now.

    A `state_conflict`/`preview_stale` answer means data moved after the review;
    the honest repair is to LOOK at the run again, not to re-upload the same bytes
    (the duplicate refusal already says the staged run is the one to use). The
    recheck route reloads the run's rows/conflicts and calls this, so the fence
    follows the version the reviewer just saw. Returns the new fence, or None
    when the run is not a staged one worth re-checking. Landing metadata only —
    never the mutable book, never the version itself."""
    current = conn.execute(text('select version from app.business_version where singleton')).scalar_one()
    stamped = conn.execute(text(
        "update landing.import_run set meta = meta || jsonb_build_object("
        "'review_state_version', cast(:v as text), "
        "'review_state_version_at', to_char(now() at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US')) "
        "where id = :r and source_system = :s and status = 'OK' and not (meta ? 'applied') "
        "returning id"), {'v': str(current), 'r': int(run_id), 's': source}).scalar()
    return str(current) if stamped is not None else None


def publish(conn, unit, scope, messages):
    version = str(unit['version'])
    for uid in unit.get('review_jobs', []):
        forced = conn.execute(text("select payload->>'force_state_change' from app.task_outbox where uid=:u"),
                              {'u': uid}).scalar()
        if forced == 'true':
            # A manager's forced confirm carries no fence of its own — the force
            # IS the decision that the version it reviewed no longer stands.
            continue
        conn.execute(text("update app.task_outbox set payload=payload || "
                          "jsonb_build_object('expected_state_version',cast(:v as text)) where uid=:u"),
                     {'v': version, 'u': uid})
    uid = WORKER_RUN.get()
    if not uid:
        return
    row = conn.execute(text('select payload from app.operation_run where uid=:u'), {'u': uid}).scalar()
    if not row or row.get('state') != 'done' or row.get('kind') not in PREVIEW_KINDS:
        return
    result = row.get('result') if row['kind'] == 'master-sheet' else row
    if not isinstance(result, dict) or result.get('installed'):
        return
    result['review_state_version'] = version
    preview = result.get('preview')
    if preview:
        preview['review_state_version'] = version
        conn.execute(text("update records.debt_import_preview set payload=payload || "
                          "jsonb_build_object('review_state_version',cast(:v as text)) where uid=:u"),
                     {'v': version, 'u': preview['uid']})
    if row['kind'] in ('peak-report', 'peak-receipt') and row.get('run_id'):
        # The stamp carries `_at` as well, so the run's changes read has the exact
        # fence moment as its watermark (not an earlier inner-commit timestamp).
        conn.execute(text("update landing.import_run set meta=meta || "
                          "jsonb_build_object('review_state_version',cast(:v as text), "
                          "'review_state_version_at', to_char(now() at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS.US')) where id=:r"),
                     {'v': version, 'r': row['run_id']})
    conn.execute(text('update app.operation_run set payload=cast(:p as jsonb) where uid=:u'),
                 {'u': uid, 'p': json.dumps(row)})
    # Responses may already be compressed by inner middleware. The public
    # operation poll reads this committed row; never decode/rewrite wire bytes.
