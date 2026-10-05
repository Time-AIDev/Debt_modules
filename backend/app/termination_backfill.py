"""Run after migration: python -m app.termination_backfill.

Read existing account/browser stores without changing them. Restrict legacy pickle
classes, serialize output as JSON, refuse unreadable evidence rather than guess.
"""
import importlib
import io
import pickle
from sqlalchemy import text
from . import db, session, termination_archive as archive


class LegacyReader(pickle.Unpickler):
    def find_class(self, module, name):
        allowed = (module == 'builtins' and name in ('dict', 'list', 'tuple', 'set', 'frozenset')) or module in ('datetime', 'decimal') or module.startswith('app.')
        if not allowed:
            raise ValueError('Unsupported legacy state class')
        obj = getattr(importlib.import_module(module), name)
        if not isinstance(obj, type):
            raise ValueError('Legacy state must contain data classes only')
        return obj


def run():
    from . import main  # initialize the served imported book before capture
    count = 0
    principals = []
    if db.configured():
        with db.connect() as conn:
            principals = list(conn.execute(text("select principal_key as principal, key, payload, codec from app.user_state where key in ('cases.state','cases.fee_state','journey.state') union all select session_id as principal, key, payload, codec from app.session_state where key in ('cases.state','cases.fee_state','journey.state') order by principal")).mappings())
    grouped = {}
    for row in principals:
        if row['codec'] != 'pickle-v1':
            raise ValueError('Unsupported state codec during backfill')
        grouped.setdefault(row['principal'], {})[row['key']] = LegacyReader(io.BytesIO(row['payload'])).load()
    # Collect all available termination evidence before projecting shared facts.
    # Otherwise an empty imported record in the first account could suppress a
    # complete reason recorded in a later account forever.
    archive.save(best_facts(grouped, main.CUSTOMERS), [])
    preferred = {}
    for principal, values in grouped.items():
        state = values.get('cases.state')
        if state is None:
            continue
        for uid, case in state.cases.items():
            score = len([e for e in state.events if e.get('case_uid') == case['uid']])
            score += len([r for r in state.contact_log if r.get('customer_uid') == uid])
            if uid not in preferred or score > preferred[uid][0]:
                preferred[uid] = (score, principal)
    for customer in main.CUSTOMERS:
        principal = preferred.get(customer.uid, (0, 'termination-backfill-import'))[1]
        values = grouped.get(principal, {})
        token = session.CURRENT.set(principal)
        read_token = archive._CACHE.set({})
        try:
            for store in session.REGISTRY:
                if store.key in values:
                    store._by_session[principal] = values[store.key]
            row = archive.capture(customer, 'BACKFILL')
            if row:
                archive.save([], [row])
                count += 1
        finally:
            archive._CACHE.reset(read_token)
            session.CURRENT.reset(token)
    return count


def evidence_score(fact):
    term = fact.get('termination') or {}
    return (bool(term.get('reason') or term.get('reason_th') or term.get('reason_en')),
            sum(bool(term.get(k)) for k in ('on', 'by', 'cause', 'instrument', 'origin')),
            str(term.get('on') or ''))


def best_facts(grouped, customers):
    from . import cases
    candidates = []
    by_contract = {k.uid: customer.uid for customer in customers for k in customer.contracts}
    for customer in customers:
        for contract in customer.contracts:
            candidates.append({'contract_uid': contract.uid, 'customer_uid': customer.uid,
                               'status': getattr(contract, 'status', None),
                               'termination': getattr(contract, 'termination', None) or {}})
    for values in grouped.values():
        state = values.get('cases.state')
        for uid, slot in values.get('cases.fee_state', {}).items():
            if uid not in by_contract:
                continue
            term = slot.get('termination')
            if not term and state:
                # A case-level record is usable only with an explicit contract
                # event identifying the same contract; never infer a missing link.
                event = next((e for e in state.events if e.get('kind') == 'CONTRACT_TERMINATED' and e.get('contract_uid') == uid), None)
                case = state.cases.get(by_contract[uid])
                if event and case:
                    term = case.get('termination')
            candidates.append({'contract_uid': uid, 'customer_uid': by_contract[uid],
                               'status': slot.get('status'), 'termination': term or {}})
    chosen = {}
    for fact in candidates:
        if fact['status'] not in cases.ENDED_CONTRACT_STATUSES or fact['status'] == 'CLOSED':
            continue
        previous = chosen.get(fact['contract_uid'])
        if previous is None or evidence_score(fact) > evidence_score(previous):
            chosen[fact['contract_uid']] = fact
    return list(chosen.values())



if __name__ == '__main__':
    print('Archived %d terminated customer cases' % run())
