"""Seed a dedicated load database with synthetic customer/contract data only."""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'scripts'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--customers', type=int, default=500)
    parser.add_argument('--role-profile', choices=('owner', 'mixed'), default='owner')
    parser.add_argument('--private-dir', type=Path, required=True)
    args = parser.parse_args()
    # Never accept the live database or credentials. The orchestration creates it.
    if os.environ.get('VOLT_LOAD_TEST_DATABASE') != 'true':
        raise SystemExit('Explicit isolated load database marker required')
    from sqlalchemy.engine import make_url
    url = make_url(os.environ['DATABASE_URL'])
    if not (url.database or '').startswith('hardening_load'):
        raise SystemExit('Refusing to seed a non-load database')
    from app import db, migrate, landing
    from bench_scale import lease_block
    customers = []
    for i in range(args.customers):
        customers.append({'volt_id': 'VL%07d' % (9000000+i), 'customer_no': 'LOAD%06d' % i,
                          'name_roman': 'Synthetic Customer %06d' % i,
                          'name_th': 'ลูกค้าทดสอบ %06d' % i, 'epc': 'LOAD%06d' % i,
                          'product': 'LEASE', 'sales_lead': 'load_owner',
                          'phone_masked': 'TEST-REDACTED', 'email_masked': 'synthetic@example.test'})
    with db.connect() as conn, conn.begin():
        migrate.apply(conn)
        if conn.exec_driver_sql('select count(*) from landing.customer').scalar():
            raise SystemExit('Load database must be empty; create a fresh database')
        run = landing.start_run(conn, 'SHEET', 'synthetic-k6')
        landing.write_customers(conn, run, 'SHEET', customers)
        # Production now requires explicit live Won CRM evidence. Keep the
        # historical contractual SHEET fixture unchanged and add its synthetic
        # identity/proof observations rather than disabling the production rule.
        proof = landing.start_run(conn, 'ODOO', 'synthetic-k6-won-proof')
        landing.write_customers(conn, proof, 'ODOO', customers)
        orders = [(customer['volt_id'], {
            'no': index + 1, 'crm_id': index + 1,
            'order_status': 'Order - Done', 'crm_status': 'Won',
            'epc_start_date': '2023-09-14', 'epc_end_date': '2023-09-20',
        }) for index, customer in enumerate(customers)]
        landing.write_orders(conn, proof, 'ODOO', orders)
        landing.finish_run(conn, proof, 'OK', row_counts={'customers': len(customers), 'orders': len(orders)}, reconciled=True)
        landing.write_orders(conn, run, 'SHEET', orders)
        for i, customer in enumerate(customers):
            block = lease_block(i)
            block['first_payment_date'] = '2024-01-10'
            landing.write_block(conn, run, 'SHEET', customer['volt_id'], 'leasing', block)
        landing.finish_run(conn, run, 'OK', row_counts={'customers': len(customers)}, reconciled=True)
        conn.exec_driver_sql("insert into app.data_epoch(kind,run_id) values ('synthetic-load', %s)", (run,))
    from app import book
    built, _report = book.build()
    args.private_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    dataset = {'synthetic': True, 'customers': len(built),
               'contracts': len(built), 'instalments_per_contract': 96, 'synthetic_won_proof': True,
               'customer_uids': [c.uid for c in built]}
    if not dataset['customer_uids']: raise SystemExit('Synthetic data did not create a served book')
    (args.private_dir / 'dataset.json').write_text(json.dumps(dataset))
    from app import auth, tab_sessions
    auth.set_config(auth.load_config())
    roles = ('OWNER', 'MANAGER', 'SUPERVISOR', 'OFFICER', 'OPS')
    officers = {'OWNER': 'owner', 'MANAGER': 'settasak', 'SUPERVISOR': 'settasak', 'OFFICER': 'ploy', 'OPS': 'ops'}
    users = []
    for i in range(25):
        subject = 'vu%d@load.example.test' % i
        role = roles[i % len(roles)] if args.role_profile == 'mixed' else 'OWNER'
        officer = officers[role]
        allowed = auth.current_config().allowlist.get(subject)
        if not allowed or allowed['role'] != role or allowed['officer'] != officer:
            raise SystemExit('Synthetic role fixture must match the explicitly configured allowlist')
        users.append({'subject': subject, 'role': role, 'officer': officer,
                      'token': tab_sessions.issue(auth.new_session(subject, 'GOOGLE', role, officer, False))})
    dataset['role_profile'] = args.role_profile
    (args.private_dir / 'dataset.json').write_text(json.dumps(dataset))
    path = args.private_dir / 'tokens.json'
    path.write_text(json.dumps(users)); path.chmod(0o600)
    print(json.dumps({k:v for k,v in dataset.items() if k != 'customer_uids'}))


if __name__ == '__main__': main()
