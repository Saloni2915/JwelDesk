from django.db import migrations


def assign_existing_records_to_primary_tenant(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    Tenant = apps.get_model('accounts', 'Tenant')
    CompanySettings = apps.get_model('accounts', 'CompanySettings')
    Category = apps.get_model('inventory', 'Category')
    ItemSequence = apps.get_model('inventory', 'ItemSequence')
    JewelleryItem = apps.get_model('inventory', 'JewelleryItem')
    StockMovement = apps.get_model('inventory', 'StockMovement')
    MetalRate = apps.get_model('inventory', 'MetalRate')
    Customer = apps.get_model('customers', 'Customer')
    Sale = apps.get_model('sales', 'Sale')
    Payment = apps.get_model('sales', 'Payment')
    Enquiry = apps.get_model('sales', 'Enquiry')
    OldGoldTransaction = apps.get_model('sales', 'OldGoldTransaction')
    CustomOrder = apps.get_model('custom_orders', 'CustomOrder')
    Branch = apps.get_model('team', 'Branch')
    Employee = apps.get_model('team', 'Employee')
    EmployeeDocument = apps.get_model('team', 'EmployeeDocument')
    Karigar = apps.get_model('karigar', 'Karigar')
    KarigarWorkAssignment = apps.get_model('karigar', 'KarigarWorkAssignment')
    KarigarSettlement = apps.get_model('karigar', 'KarigarSettlement')

    # 1. Identify primary store owner
    primary_user = (
        User.objects.filter(email='salonisoni15dec2002@gmail.com').first()
        or User.objects.filter(username='salonisoni15dec2002@gmail.com').first()
        or User.objects.filter(is_superuser=True).first()
        or User.objects.first()
    )

    if not primary_user:
        return

    # 2. Get or create primary tenant
    primary_tenant, created = Tenant.objects.get_or_create(
        name='JwelDesk',
        defaults={
            'slug': 'jweldesk',
            'owner': primary_user,
            'is_active': True,
        }
    )

    # 3. Associate existing CompanySettings with primary tenant
    CompanySettings.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    if not CompanySettings.objects.filter(tenant=primary_tenant).exists():
        CompanySettings.objects.create(tenant=primary_tenant, company_name='JwelDesk')

    # 4. Associate existing domain records to the primary tenant
    Category.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    ItemSequence.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    JewelleryItem.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    StockMovement.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    MetalRate.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Customer.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Sale.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Payment.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Enquiry.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    OldGoldTransaction.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    CustomOrder.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Branch.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Employee.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    EmployeeDocument.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    Karigar.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    KarigarWorkAssignment.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)
    KarigarSettlement.objects.filter(tenant__isnull=True).update(tenant=primary_tenant)

    from django.utils.text import slugify

    # 5. For any other standalone users without an employee profile, give them their own isolated tenant
    for user in User.objects.all():
        if user.id == primary_user.id or user.is_superuser:
            continue
        emp = Employee.objects.filter(user=user).first()
        if not emp and not Tenant.objects.filter(owner=user).exists():
            shop_name = f"{user.first_name or user.username}'s Store"
            base_slug = slugify(f"{user.username}-store") or f"user-{user.id}-store"
            user_tenant = Tenant.objects.create(
                name=shop_name,
                slug=base_slug,
                owner=user,
                is_active=True,
            )
            CompanySettings.objects.create(
                tenant=user_tenant,
                company_name=shop_name,
            )


def reverse_assignment(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0003_tenant_companysettings_tenant'),
        ('inventory', '0008_remove_jewelleryitem_unique_nonblank_huid_and_more'),
        ('customers', '0002_customer_tenant'),
        ('sales', '0004_enquiry_tenant_oldgoldtransaction_tenant_and_more'),
        ('custom_orders', '0002_customorder_tenant_alter_customorder_order_number_and_more'),
        ('team', '0007_branch_tenant_employee_tenant_and_more'),
        ('karigar', '0003_karigar_tenant_karigarsettlement_tenant_and_more'),
    ]

    operations = [
        migrations.RunPython(assign_existing_records_to_primary_tenant, reverse_assignment),
    ]
