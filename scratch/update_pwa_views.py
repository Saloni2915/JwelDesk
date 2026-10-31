import os

with open('config/pwa_views.py', 'r', encoding='utf-8') as f:
    text = f.read()

target = """    if action in ('backfill_branch_data', 'backfill'):
        out = io.StringIO()
        try:
            call_command('backfill_branch_data', stdout=out)
            return JsonResponse({
                'status': 'success',
                'output': out.getvalue(),
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'exception': str(e)}, status=500)"""

replacement = """    if action in ('backfill_branch_data', 'backfill'):
        out = io.StringIO()
        try:
            call_command('backfill_branch_data', stdout=out)
            return JsonResponse({
                'status': 'success',
                'output': out.getvalue(),
            })
        except Exception as e:
            return JsonResponse({'status': 'error', 'exception': str(e)}, status=500)

    if action == 'inspect_db':
        with connection.cursor() as cursor:
            vendor = connection.vendor
            cursor.execute("SELECT app, name, applied FROM django_migrations WHERE app = 'super_admin' ORDER BY id;")
            migs = [{'app': r[0], 'name': r[1], 'applied': str(r[2])} for r in cursor.fetchall()]

            cols = []
            if vendor == 'postgresql':
                cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'super_admin_platformdemolead';")
                cols = [r[0] for r in cursor.fetchall()]

        return JsonResponse({
            'status': 'success',
            'vendor': vendor,
            'super_admin_migrations': migs,
            'platformdemolead_columns': cols,
        })

    if action == 'apply_crm_schema':
        results = []
        with connection.cursor() as cursor:
            if connection.vendor == 'postgresql':
                cursor.execute(\"\"\"
                    ALTER TABLE super_admin_platformdemolead 
                    ADD COLUMN IF NOT EXISTS lead_id varchar(40) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS whatsapp_number varchar(30) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS state varchar(100) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS deal_value numeric(12, 2) DEFAULT 0.00,
                    ADD COLUMN IF NOT EXISTS stage varchar(30) DEFAULT 'new',
                    ADD COLUMN IF NOT EXISTS lost_reason varchar(50) DEFAULT '',
                    ADD COLUMN IF NOT EXISTS lost_notes text DEFAULT '',
                    ADD COLUMN IF NOT EXISTS expected_close_date date;
                \"\"\")
                results.append("platformdemolead columns ensured")

                cursor.execute(\"\"\"
                    ALTER TABLE super_admin_platformproposal 
                    ADD COLUMN IF NOT EXISTS branches_count integer DEFAULT 1,
                    ADD COLUMN IF NOT EXISTS is_latest boolean DEFAULT true,
                    ADD COLUMN IF NOT EXISTS lead_id bigint,
                    ADD COLUMN IF NOT EXISTS parent_proposal_id bigint,
                    ADD COLUMN IF NOT EXISTS selected_modules jsonb DEFAULT '[]'::jsonb,
                    ADD COLUMN IF NOT EXISTS tax_amount numeric(12, 2) DEFAULT 0.00,
                    ADD COLUMN IF NOT EXISTS tax_percentage numeric(5, 2) DEFAULT 18.00,
                    ADD COLUMN IF NOT EXISTS users_count integer DEFAULT 3,
                    ADD COLUMN IF NOT EXISTS version_number integer DEFAULT 1;
                \"\"\")
                results.append("platformproposal columns ensured")

                cursor.execute(\"\"\"
                    CREATE TABLE IF NOT EXISTS super_admin_platformleadstagehistory (
                        id bigserial PRIMARY KEY,
                        from_stage varchar(30) NOT NULL,
                        to_stage varchar(30) NOT NULL,
                        reason text NOT NULL,
                        created_at timestamptz NOT NULL,
                        changed_by_id bigint,
                        lead_id bigint NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS super_admin_platformleadnegotiation (
                        id bigserial PRIMARY KEY,
                        target_plan varchar(30) NOT NULL,
                        required_modules jsonb NOT NULL,
                        branches_count integer NOT NULL,
                        users_count integer NOT NULL,
                        budget numeric(12, 2) NOT NULL,
                        expected_purchase_date date,
                        competitor_info varchar(200) NOT NULL,
                        discussion_summary text NOT NULL,
                        created_at timestamptz NOT NULL,
                        conducted_by_id bigint,
                        lead_id bigint NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS super_admin_platformleadactivity (
                        id bigserial PRIMARY KEY,
                        activity_type varchar(30) NOT NULL,
                        title varchar(200) NOT NULL,
                        scheduled_at timestamptz,
                        is_completed boolean NOT NULL,
                        completed_at timestamptz,
                        outcome_notes text NOT NULL,
                        next_follow_up_date date,
                        created_at timestamptz NOT NULL,
                        assigned_to_id bigint,
                        created_by_id bigint,
                        lead_id bigint NOT NULL
                    );
                \"\"\")
                results.append("CRM tables ensured")

                cursor.execute(\"\"\"
                    INSERT INTO django_migrations (app, name, applied)
                    SELECT 'super_admin', '0010_platformdemolead_deal_value_and_more', now()
                    WHERE NOT EXISTS (
                        SELECT 1 FROM django_migrations WHERE app = 'super_admin' AND name = '0010_platformdemolead_deal_value_and_more'
                    );
                \"\"\")
                results.append("Migration 0010 recorded in django_migrations")

        return JsonResponse({
            'status': 'success',
            'results': results,
        })"""

# Normalize line endings
text_normalized = text.replace('\r\n', '\n')
target_normalized = target.replace('\r\n', '\n')
replacement_normalized = replacement.replace('\r\n', '\n')

if target_normalized in text_normalized:
    new_text = text_normalized.replace(target_normalized, replacement_normalized, 1)
    with open('config/pwa_views.py', 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(new_text)
    print("SUCCESS: config/pwa_views.py updated.")
else:
    print("ERROR: Target not found.")
