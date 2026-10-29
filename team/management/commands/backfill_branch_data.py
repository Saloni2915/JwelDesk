from django.core.management.base import BaseCommand
from django.db import transaction
from accounts.models import Tenant
from team.models import Branch
from inventory.models import JewelleryItem, StockMovement
from customers.models import Customer
from sales.models import Sale, Payment, OldGoldTransaction, Enquiry
from custom_orders.models import CustomOrder
from karigar.models import Karigar, KarigarWorkAssignment, KarigarSettlement
from wholesale.models import RetailerParty


class Command(BaseCommand):
    help = "Safely ensures default branches exist for all tenants and backfills legacy records to the default branch."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Starting branch backfill process..."))
        total_tenants = 0
        total_updated = 0

        with transaction.atomic():
            for tenant in Tenant.objects.all():
                total_tenants += 1
                default_branch = Branch.ensure_default_branch(tenant)
                self.stdout.write(f"Tenant '{tenant.name}' (ID: {tenant.id}) -> Default Branch: '{default_branch.name}' (Code: {default_branch.code})")

                # Backfill unassigned models
                items = JewelleryItem.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                movements = StockMovement.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                customers = Customer.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                sales = Sale.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                payments = Payment.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                old_golds = OldGoldTransaction.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                enquiries = Enquiry.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                orders = CustomOrder.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                karigars = Karigar.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                assignments = KarigarWorkAssignment.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                settlements = KarigarSettlement.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)
                parties = RetailerParty.objects.filter(tenant=tenant, branch__isnull=True).update(branch=default_branch)

                updated_count = (items + movements + customers + sales + payments +
                                 old_golds + enquiries + orders + karigars +
                                 assignments + settlements + parties)
                total_updated += updated_count

                if updated_count > 0:
                    self.stdout.write(self.style.SUCCESS(
                        f"  -> Backfilled {updated_count} records (Items: {items}, Sales: {sales}, Customers: {customers}, etc.)"
                    ))

        self.stdout.write(self.style.SUCCESS(
            f"Successfully processed {total_tenants} tenants. Total backfilled records: {total_updated}."
        ))
